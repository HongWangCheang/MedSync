"""Pharmacist agent = MedTrack's label RAG agent (services/rag, `POST /v1/agent/chat`), called as a READ tool.

The RAG agent already does the hard part: it searches the openFDA label snapshot, answers in the user's language,
and replaces any answer whose citations don't point at retrieved passages with a fixed refusal. This module only
turns its SSE stream into one result and sorts failures into the two kinds the step graph cares about:

    PharmacistUnavailable   transient (timeout, rate limit, network): the step parks and resumes on re-dispatch
    PharmacistMisconfigured permanent (no API key, model gone): the step fails with a reason the user can read
"""

from __future__ import annotations

import contextvars
import hashlib
import hmac
import json
import os
from typing import Any, Iterable, Iterator, Protocol

import httpx

# Error codes the RAG service reports that no amount of retrying will fix.
PERMANENT = {"missing_key", "invalid_config", "gemini_access_denied", "gemini_model_unavailable",
             "gemini_request_rejected"}
EXCERPT_CHARS = 400
# Tool outcomes meaning "the user has to pick a product before I can answer"; the next message continues the session.
CHOICE_STATUSES = {"needs_selection", "user_must_choose"}


OWNER_HEADER = "X-MedSync-Owner"
# The gateway's per-dispatch delegated token ("read this user's medications"). Lives in a context variable for the
# duration of one request so it never becomes part of the step's state, and therefore never reaches a checkpoint.
delegation: contextvars.ContextVar[str | None] = contextvars.ContextVar("medsync_delegation", default=None)


def signed_owner(account_id: str, secret: str | None = None) -> str | None:
    """Session owner for RAG, signed so a caller that reaches RAG directly cannot claim someone else's conversation.

    RAG used to derive the owner from the Authorization header, but that header now carries a delegated token that
    changes on every dispatch; follow-ups need an owner that stays the same for the account.
    """
    secret = secret if secret is not None else os.environ.get("MEDSYNC_INTERNAL_SECRET", "")
    if not secret:
        return None
    owner = hashlib.sha256(f"medsync-rag-owner:{account_id}".encode()).hexdigest()[:32]
    return owner + "." + hmac.new(secret.encode(), owner.encode(), hashlib.sha256).hexdigest()


class PharmacistUnavailable(Exception):
    pass


class PharmacistMisconfigured(Exception):
    pass


class Pharmacist(Protocol):
    def ask(self, question: str, session_id: str | None = None, owner: str | None = None,
            token: str | None = None, selection: dict[str, str] | None = None) -> dict[str, Any]: ...


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict[str, Any]]]:
    event, data = None, []
    for line in lines:
        if line == "":
            if event is not None:
                yield event, json.loads("\n".join(data) or "{}")
            event, data = None, []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].strip())
    if event is not None:
        yield event, json.loads("\n".join(data) or "{}")


def summarize(answer: dict[str, Any], tools: list[str], session_id: str | None = None,
              awaiting_choice: bool = False, choices: list[dict[str, Any]] | None = None,
              interaction_mentioned: bool = False) -> dict[str, Any]:
    """What the device stores and shows: the answer, whether it is grounded, and short excerpts of each source."""
    citations = [
        {"id": cid, "label": c.get("label_name"), "section": c.get("section"),
         "excerpt": (c.get("text") or "")[:EXCERPT_CHARS], "source_url": c.get("source_url")}
        for cid, c in (answer.get("citations") or {}).items()
    ]
    return {"answer": answer.get("text", ""), "grounded": bool(answer.get("grounded")),
            "refusal_reason": answer.get("refusal_reason"), "citations": citations, "tools": tools,
            "session_id": session_id, "awaiting_choice": awaiting_choice,
            # check_interaction found label text about the combination; posted to the findings board when grounded.
            "interaction_mentioned": interaction_mentioned,
            # Exact products the user can tap; each carries label_id + version so the pick is unambiguous.
            "choices": [{k: c.get(k) for k in ("label_id", "version", "name", "manufacturer")} for c in choices or []]
            if awaiting_choice else []}


class RagPharmacist:
    def __init__(self, base_url: str, timeout_s: float = 60.0, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(base_url=base_url, transport=transport,
                                  timeout=httpx.Timeout(timeout_s, connect=3.0))

    def ask(self, question: str, session_id: str | None = None, owner: str | None = None,
            token: str | None = None, selection: dict[str, str] | None = None) -> dict[str, Any]:
        tools: list[str] = []
        answer, session, awaiting, choices, mentioned = None, session_id, False, [], False
        body = {"message": question[:1000], **({"session_id": session_id} if session_id else {}),
                **({"selection": {"label_id": selection["label_id"], "version": selection["version"]}}
                   if selection else {})}
        headers = {**({OWNER_HEADER: owner} if owner else {}), **({"Authorization": f"Bearer {token}"} if token else {})}
        try:
            with self._http.stream("POST", "/v1/agent/chat", json=body, headers=headers) as response:
                if response.status_code >= 500:
                    raise PharmacistUnavailable(f"HTTP {response.status_code}")
                if response.status_code >= 400:
                    raise PharmacistMisconfigured(f"HTTP {response.status_code}")
                for event, data in parse_sse(response.iter_lines()):
                    if event == "session":
                        session = data.get("session_id") or session
                    elif event == "tool_call":
                        tools.append(str(data.get("name")))
                    elif event == "tool_result":
                        awaiting = awaiting or data.get("status") in CHOICE_STATUSES
                        mentioned = mentioned or (data.get("name") == "check_interaction"
                                                  and data.get("status") == "mentioned")
                        if data.get("candidates"):
                            choices = data["candidates"]  # the latest ambiguity is the one the answer asks about
                    elif event == "answer":
                        answer = data
                    elif event == "error":
                        code = str(data.get("code", "unknown"))
                        raise (PharmacistMisconfigured if code in PERMANENT else PharmacistUnavailable)(code)
        except httpx.TransportError as error:
            raise PharmacistUnavailable(str(error) or type(error).__name__) from error
        if answer is None:
            raise PharmacistUnavailable("stream ended without an answer")
        # Only a turn that ended without citations is still waiting on the choice; a later tool call may resolve it.
        return summarize(answer, tools, session, awaiting and not answer.get("citations"), choices, mentioned)
