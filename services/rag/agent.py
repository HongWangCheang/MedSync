"""Tool-calling medication label agent with session memory and citation checks.

The model can only cite passages that a tool returned in the same session. Answers that cite anything else, or that
make no citation although this turn retrieved evidence, are replaced by a refusal before they reach the client.
"""

import hashlib
import json
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from urllib.parse import urlencode

from label_retrieval import source_url
from medtrack_server import (ApiError, DEFAULT_MODEL, GEMINI_URL, MODEL_ID, gemini_key, names, request_json, values)

MAX_STEPS = 5
KEEP_TURNS = 6
CITATION_GROUP = re.compile(r"\[\s*(S\d{1,4}(?:\s*[,;]\s*S\d{1,4})*)\s*\]")
CITATION_ID = re.compile(r"S\d{1,4}")
NON_WORD = re.compile(r"[^a-z0-9]+")


def plain(text):
    """Lower-case and collapse punctuation so "St. John's" matches "St. John’s" and "co-trimoxazole" matches
    "co trimoxazole"."""
    return " " + NON_WORD.sub(" ", text.casefold()).strip() + " "
# Ordered by how directly the section speaks to combining drugs; used to rank matches when no reranker is loaded.
INTERACTION_SECTIONS = ("do_not_use", "ask_doctor_or_pharmacist", "drug_interactions", "boxed_warning",
                        "warnings_and_cautions", "when_using", "ask_doctor", "warnings")
REFUSAL = ("I can't give a sourced answer to that. Please check the printed label or ask a pharmacist.")
SYSTEM = """You answer questions about over-the-counter and prescription drug labels for a medication tracking app.
Use tools to find evidence. Never answer from general knowledge.
- Every factual sentence must end with citations like [S3] or [S3, S4] that refer to passages returned by tools.
- If a tool says the label does not mention something, say exactly that; do not conclude it is safe.
- If search_label returns needs_selection, ask the user which product they mean, listing the candidate names.
- If the user says "it" or "this", use the medication in focus (shown below) unless they name another one.
- Never give dosing changes, diagnoses, or advice beyond what the cited label text says.
Keep answers short and in the user's language."""

TOOLS = [{"functionDeclarations": [
    {"name": "search_label",
     "description": "Search one drug label for passages that answer a question. Pass drug_name, or label_id and "
                    "version if the product was already chosen.",
     "parameters": {"type": "object", "properties": {
         "question": {"type": "string", "description": "The question in English."},
         "drug_name": {"type": "string"}, "label_id": {"type": "string"}, "version": {"type": "string"}},
         "required": ["question"]}},
    {"name": "get_my_medications",
     "description": "List the signed-in user's own medication records (name, dosage, frequency, time).",
     "parameters": {"type": "object", "properties": {}}},
    {"name": "check_interaction",
     "description": "Find passages on one drug's label that mention another drug or its ingredients. Only reports "
                    "what the label text says.",
     "parameters": {"type": "object", "properties": {
         "drug_name": {"type": "string", "description": "Label to read."},
         "other_drug": {"type": "string", "description": "Drug or ingredient to look for."},
         "question": {"type": "string", "description": "The user's concern in English, used to rank passages."},
         "label_id": {"type": "string"}, "version": {"type": "string"}},
         "required": ["drug_name", "other_drug"]}},
]}]


class GeminiAgentModel:
    """Minimal REST client for Gemini function calling."""

    def generate(self, system, contents, tools):
        key = gemini_key()
        if not key:
            raise ApiError(503, "missing_key", "Set GEMINI_API_KEY on the local server.")
        model = os.environ.get("GEMINI_MODEL", DEFAULT_MODEL).strip()
        if not MODEL_ID.fullmatch(model):
            raise ApiError(503, "invalid_config", "Set GEMINI_MODEL to a valid model ID.")
        payload = {"systemInstruction": {"parts": [{"text": system}]}, "contents": contents}
        if tools:
            payload["tools"] = tools
        result = request_json(GEMINI_URL + model + ":generateContent", timeout=30, data=payload,
                              headers={"Content-Type": "application/json", "x-goog-api-key": key}, gemini=True)
        try:
            content = result["candidates"][0]["content"]
            content.setdefault("role", "model")
            content["parts"] = content.get("parts") or []
        except (KeyError, IndexError, TypeError) as error:
            raise ApiError(502, "invalid_model_output", "The model returned no usable response.") from error
        return content, result.get("usageMetadata", {})


class SyncServerMedications:
    """Reads the signed-in user's medication records from the Spring Boot sync server."""

    def __init__(self, base_url=None):
        self.base_url = (base_url or os.environ.get("MEDTRACK_SYNC_URL", "http://127.0.0.1:8081")).rstrip("/")

    def list(self, token):
        if not token:
            return None
        medications, after = [], 0
        for _ in range(100):
            page = request_json(f"{self.base_url}/v1/sync/changes?" + urlencode({"after": after, "limit": 100}),
                                timeout=8, headers={"Authorization": token})
            for change in page.get("changes", []):
                if change.get("kind") == "medication":
                    body = change.get("body") or {}
                    medications.append({k: body.get(k, "") for k in ("name", "dosage", "frequency", "time", "type")})
            if not page.get("hasMore"):
                return medications
            after = page["nextCursor"]
        return medications


@dataclass
class Session:
    id: str
    owner: str
    summary: str = ""
    focus: dict | None = None
    turns: list = field(default_factory=list)       # [{"user": str, "answer": str}]
    ledger: dict = field(default_factory=dict)      # citation id -> source
    usage: dict = field(default_factory=lambda: {"prompt": 0, "output": 0})


class SessionStore:
    def __init__(self, path=":memory:"):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS agent_session (id TEXT PRIMARY KEY, owner TEXT, state TEXT, "
                        "updated REAL)")
        self.lock = Lock()

    def load(self, session_id, owner):
        with self.lock:
            row = self.db.execute("SELECT owner, state FROM agent_session WHERE id = ?", (session_id,)).fetchone()
        if row is None or row[0] != owner:
            return None
        state = json.loads(row[1])
        return Session(session_id, owner, **state)

    def save(self, session):
        state = {k: getattr(session, k) for k in ("summary", "focus", "turns", "ledger", "usage")}
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO agent_session VALUES (?, ?, ?, ?)",
                            (session.id, session.owner, json.dumps(state), time.time()))


def gemini_summarize(previous, turns):
    """Fold older turns into a short running summary so the prompt stays bounded."""
    from medtrack_server import gemini_text
    return gemini_text(
        "Update the running summary of a medication-label chat in at most 80 words. Keep drug names, product "
        "choices and open questions. Do not add facts that are not in the input.",
        {"previous_summary": previous, "turns": turns})


def owner_of(token):
    return hashlib.sha256(token.encode()).hexdigest() if token else "anonymous"


class LabelAgent:
    def __init__(self, index, model=None, medications=None, store=None, summarize=None):
        self.index = index
        self.model = model or GeminiAgentModel()
        self.medications = medications or SyncServerMedications()
        self.store = store or SessionStore(os.environ.get("MEDTRACK_AGENT_DB", ":memory:"))
        self.summarize = summarize
        self.turn_blocked = set()
        self.mode = os.environ.get("MEDTRACK_AGENT_MODE", "rerank" if index.reranker is not None else "keyword")

    # ----- tools ---------------------------------------------------------------------------------------------
    def _cite(self, session, label, passage_source):
        for cid, existing in session.ledger.items():
            if (existing["label_id"], existing["version"], existing["passage_id"]) == (
                    label["id"], label["version"], passage_source["id"]):
                return cid
        cid = f"S{len(session.ledger) + 1}"
        session.ledger[cid] = {
            "label_id": label["id"], "version": label["version"], "label_name": label["name"],
            "passage_id": passage_source["id"], "section": passage_source["section"], "text": passage_source["text"],
            "source_url": source_url(label["id"], label["version"]) if self.index.snapshot.public else None,
        }
        return cid

    def _resolve(self, session, drug_name=None, label_id=None, version=None):
        if label_id and version and (label_id, version) in self.turn_blocked:
            # Same turn as a needs_selection result: the user has not chosen yet, so the model may not choose.
            return {"status": "user_must_choose", "note": "Ask the user which product they mean."}, None
        if label_id and version:
            record = self.index.snapshot.get(label_id, version)
            if record is None:
                return {"status": "no_match"}, None
            return None, {"id": label_id, "version": version, "name": next(iter(names(record)), "Drug label")}
        if not drug_name:
            if session.focus:
                return None, session.focus
            return {"status": "needs_drug_name"}, None
        candidates = self.index.catalog.search(drug_name)["labels"]
        if not candidates:
            return {"status": "no_match", "drug_name": drug_name}, None
        if version and len([c for c in candidates if c["version"] == version]) == 1:
            # The name alone is ambiguous but the model (or the user, echoed back by the model) also gave a
            # version, which is enough to pick a candidate without needing its opaque label_id.
            candidates = [c for c in candidates if c["version"] == version]
        if len(candidates) > 1:
            # Name search is a substring match, so "ADVIL" also returns "ADVIL COLD AND SINUS". A name the user typed
            # exactly wins; if the exact matches are versions of one label, the newest version is the current one.
            exact = [c for c in candidates if c["name"].casefold().strip() == drug_name.casefold().strip()]
            if exact and len({c["id"] for c in exact}) == 1:
                candidates = [max(exact, key=lambda c: int(c["version"]) if c["version"].isdigit() else -1)]
        if len(candidates) > 1:
            self.turn_blocked.update((c["id"], c["version"]) for c in candidates)
            return {"status": "needs_selection", "candidates": [
                {"label_id": c["id"], "version": c["version"], "name": c["name"], "manufacturer": c["manufacturer"]}
                for c in candidates[:8]]}, None
        c = candidates[0]
        return None, {"id": c["id"], "version": c["version"], "name": c["name"]}

    def tool_search_label(self, session, question, drug_name=None, label_id=None, version=None, **_):
        problem, label = self._resolve(session, drug_name, label_id, version)
        if problem:
            return problem
        session.focus = label
        result = self.index.answer(question=question, mode=self.mode, label_id=label["id"], version=label["version"])
        out = {"status": result["status"], "label": label["name"]}
        if result["status"] == "answered":
            out["passages"] = [{"cite": self._cite(session, label, s), "section": s["section"], "text": s["text"]}
                               for s in result["sources"]]
        return out

    def tool_get_my_medications(self, session, token=None, **_):
        meds = self.medications.list(token)
        if meds is None:
            return {"status": "not_signed_in"}
        return {"status": "ok", "medications": meds}

    def _terms(self, other_drug):
        terms = {other_drug.casefold()}
        for c in self.index.catalog.search(other_drug)["labels"][:3] if 1 <= len(other_drug) <= 80 else []:
            record = self.index.snapshot.get(c["id"], c["version"])
            terms.update(n.casefold() for n in values(record.get("openfda") or {}, "generic_name"))
            terms.update(n.casefold() for n in values(record.get("openfda") or {}, "substance_name"))
        # split combination products such as "acetaminophen and diphenhydramine"
        parts = set()
        for term in terms:
            parts.update(p.strip() for p in re.split(r",| and |/", term) if len(p.strip()) >= 4)
        return sorted(terms | parts)

    def tool_check_interaction(self, session, drug_name, other_drug, question=None, label_id=None, version=None, **_):
        problem, label = self._resolve(session, drug_name, label_id, version)
        if problem:
            return problem
        session.focus = label
        terms = self._terms(other_drug)
        needles = [plain(t) for t in terms if plain(t).strip()]
        matches = [p for p in (self.index.passages[i] for i in self.index.by_label[(label["id"], label["version"])])
                   if p.field in INTERACTION_SECTIONS and any(n in plain(p.text) for n in needles)]
        if len(matches) > 4 and self.index.reranker is not None:
            query = question or f"Can {other_drug} be taken with {label['name']}?"
            scores = list(self.index.reranker.rerank(query, [p.searchable for p in matches]))
            matches = [p for _, p in sorted(zip(scores, matches), key=lambda item: -item[0])]
        elif len(matches) > 4:
            matches.sort(key=lambda p: INTERACTION_SECTIONS.index(p.field))
        hits = [{"cite": self._cite(session, label, p.source()), "section": p.section, "text": p.text}
                for p in matches[:4]]
        status = "mentioned" if hits else "not_mentioned"
        return {"status": status, "label": label["name"], "searched_terms": terms, "passages": hits,
                "note": None if hits else "The label text does not mention these terms. This is not evidence "
                                          "that the combination is safe."}

    # ----- loop ----------------------------------------------------------------------------------------------
    def _system(self, session):
        extra = []
        if session.summary:
            extra.append("Summary of earlier conversation: " + session.summary)
        if session.focus:
            extra.append(f"Medication in focus: {session.focus['name']} (label_id {session.focus['id']}, "
                         f"version {session.focus['version']}).")
        return SYSTEM + ("\n\n" + "\n".join(extra) if extra else "")

    def _history(self, session):
        contents = []
        for turn in session.turns[-KEEP_TURNS:]:
            contents.append({"role": "user", "parts": [{"text": turn["user"]}]})
            contents.append({"role": "model", "parts": [{"text": turn["answer"]}]})
        return contents

    def _compact(self, session):
        if len(session.turns) <= KEEP_TURNS:
            return
        old, session.turns = session.turns[:-KEEP_TURNS], session.turns[-KEEP_TURNS:]
        if self.summarize is not None:
            session.summary = self.summarize(session.summary, old)
        else:
            text = " ".join(f"User asked: {t['user']}" for t in old)
            session.summary = (session.summary + " " + text).strip()[-1500:]

    def validate(self, session, text, turn_citations, tools_called):
        cited = list(dict.fromkeys(cid for group in CITATION_GROUP.findall(text) for cid in CITATION_ID.findall(group)))
        unknown = [c for c in cited if c not in session.ledger]
        if unknown:
            return False, "unknown_citation", cited
        if not cited and (turn_citations or not tools_called):
            # Uncited text is only allowed to relay a tool outcome (no match, needs selection, not mentioned...).
            return False, "uncited_answer", cited
        return True, None, cited

    def run(self, message, session_id=None, token=None):
        """Yields (event, data) pairs. The final answer is only emitted after citation validation."""
        owner = owner_of(token)
        session = self.store.load(session_id, owner) if session_id else None
        if session is None:
            session = Session(str(uuid.uuid4()), owner)
        yield "session", {"session_id": session.id}
        contents = self._history(session) + [{"role": "user", "parts": [{"text": message}]}]
        turn_citations, steps, text, tools_called = set(), 0, None, 0
        self.turn_blocked = set()
        tools = {"search_label": self.tool_search_label, "get_my_medications": self.tool_get_my_medications,
                 "check_interaction": self.tool_check_interaction}
        while steps < MAX_STEPS:
            steps += 1
            content, usage = self.model.generate(self._system(session), contents, TOOLS)
            session.usage["prompt"] += usage.get("promptTokenCount", 0)
            session.usage["output"] += usage.get("candidatesTokenCount", 0)
            calls = [p["functionCall"] for p in content["parts"] if "functionCall" in p]
            if not calls:
                text = "".join(p.get("text", "") for p in content["parts"] if not p.get("thought")).strip()
                break
            contents.append(content)
            responses = []
            for call in calls:
                name, args = call.get("name"), call.get("args") or {}
                tools_called += 1
                yield "tool_call", {"name": name, "args": args}
                tool = tools.get(name)
                try:
                    result = tool(session, token=token, **args) if tool else {"status": "unknown_tool"}
                except TypeError:
                    result = {"status": "bad_arguments"}
                except ApiError as error:
                    result = {"status": "tool_error", "code": error.payload["code"]}
                turn_citations.update(p["cite"] for p in result.get("passages", []))
                yield "tool_result", {"name": name, "status": result.get("status"),
                                      "citations": [p["cite"] for p in result.get("passages", [])]}
                part = {"name": name, "response": result}
                if call.get("id"):
                    part["id"] = call["id"]
                responses.append({"functionResponse": part})
            contents.append({"role": "user", "parts": responses})
        if text is None:
            ok, reason, cited = False, "step_limit", []
        elif not text:
            ok, reason, cited = False, "empty_answer", []
        else:
            ok, reason, cited = self.validate(session, text, turn_citations, tools_called)
        self.last_rejected = None if ok else {"reason": reason, "text": text}
        answer = text if ok else REFUSAL
        session.turns.append({"user": message, "answer": answer})
        self._compact(session)
        self.store.save(session)
        yield "answer", {"text": answer, "grounded": ok, "refusal_reason": reason, "steps": steps,
                         "citations": {c: session.ledger[c] for c in cited if c in session.ledger} if ok else {},
                         "usage": dict(session.usage)}
