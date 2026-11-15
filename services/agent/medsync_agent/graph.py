"""One LangGraph thread per logical step (thread_id = account:step_key).

    START → revalidate ─┬─ PROCEED  → safety_review ─┬─ pass ─→ executor ─┬─ DONE → END
                        │                             └─ pause ─→ ask_user  │  REJECTED (e.g. slot taken) → ask_user
                        ├─ ASK_USER → ask_user (interrupt) ─→ safety_review └─ PENDING → raise: checkpoint kept
                        └─ CANCEL   → cancel → END

safety_review is where agents meet: a medication record is reviewed and the result posted to the findings board;
an irreversible step is checked against findings its (offline) planner never saw, and paused if they contradict it.

Durable execution: a node that raises (external unreachable) leaves the thread parked at that node. Re-dispatching
the same step resumes from there (`invoke(None)`), so revalidate is not re-run and the executor's ledger decides
whether the side effect already happened. A finished thread just returns its stored outcome.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict
from datetime import date, timedelta
from typing import Any, Callable, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from . import conflicts, tracing
from .experiment import Attempts, rephrase
from .external import External, Unreachable
from .findings import Finding, FindingsBoard
from .models import EXTERNAL_TOOLS, ActionRequest, Outcome
from .pharmacist import Pharmacist, PharmacistMisconfigured, PharmacistUnavailable, delegation, signed_owner
from .revalidate import decide
from .safety import SafetyReviewer, SafetyUnavailable
from .tool_ledger import ToolLedger
from .tools import LocalTools, Tools


class StepState(TypedDict, total=False):
    request: dict[str, Any]
    decision: dict[str, Any]
    answer: dict[str, Any]
    review: dict[str, Any]
    conflicts: list[dict[str, Any]]  # findings that contradict this step (shown to the user when it pauses)
    conflicts_acknowledged: bool     # the user answered the pause; do not ask again
    gate: str                        # "pass" | "pause", set by safety_review
    outcome: dict[str, Any]


def _selection(value: Any) -> dict[str, str] | None:
    """A tapped candidate from the device: only label_id + version strings are forwarded."""
    if isinstance(value, dict) and isinstance(value.get("label_id"), str) and isinstance(value.get("version"), str):
        return {"label_id": value["label_id"], "version": value["version"]}
    return None


class ExternalPending(Exception):
    """The side effect's outcome is not known yet; the step stays parked at the executor."""


def _alternatives(tools: Tools, day: str, days: int = 3) -> list[dict[str, Any]]:
    start = date.fromisoformat(day)
    found = []
    for offset in range(1, days + 1):
        candidate = (start + timedelta(days=offset)).isoformat()
        slot = tools.slot(candidate)
        if slot.get("available", 0) > 0:
            found.append({"date": candidate, "available": slot["available"]})
    return found


def build_graph(ledger: ToolLedger | None, external: External | None, checkpointer: Any,
                now_ms: Callable[[], int] = lambda: int(time.time() * 1000), attempts: Attempts | None = None,
                pharmacist: Pharmacist | None = None, safety: SafetyReviewer | None = None,
                board: FindingsBoard | None = None, tools: Tools | None = None):
    """`tools` is how the executor reaches the outside world: the MCP tool server in Compose, or (default) the
    given ledger and external system in-process."""
    attempts = attempts or Attempts()
    tools = tools or LocalTools(ledger, external)

    def post(finding: Finding) -> None:
        if board is not None:
            board.post(finding)

    def ask_pharmacist(request: ActionRequest) -> dict:
        # READ tool: no side effect to deduplicate, but the finished answer is stored in this step's thread, so a
        # re-dispatch returns it instead of paying for another model call.
        if pharmacist is None:
            return {"outcome": {"status": "FAILED", "reason": "pharmacist_not_configured"}}
        try:
            answer = pharmacist.ask(str(request.payload.get("question", "")),
                                    session_id=request.payload.get("session_id") or None,
                                    owner=signed_owner(request.account_id), token=delegation.get(),
                                    selection=_selection(request.payload.get("selection")))
        except PharmacistUnavailable as error:
            raise ExternalPending(f"pharmacist unavailable: {error}") from error
        except PharmacistMisconfigured as error:
            return {"outcome": {"status": "FAILED", "reason": f"pharmacist_not_configured: {error}"}}
        if answer["grounded"] and answer.get("interaction_mentioned"):
            # The pharmacist found label text about combining drugs: other queued steps should know.
            question = str(request.payload.get("question", ""))
            post(Finding(request.account_id, request.step_key, request.plan_id, "pharmacist", "label_interaction",
                         "moderate", f"药学问答：说明书对“{question[:40]}”有相关提醒",
                         request.created_at_ms or now_ms(),
                         {"citations": [{k: c.get(k) for k in ("label", "section", "excerpt")}
                                        for c in answer.get("citations", [])[:2]]}))
        return {"outcome": {"status": "DONE", "result": answer,
                            "reason": None if answer["grounded"] else "refused_without_evidence"}}

    def revalidate(state: StepState) -> dict:
        request = ActionRequest.model_validate(state["request"])
        world: dict[str, Any] = {}
        if request.tool == "book_appointment":
            day = request.payload.get("date", "")
            world["slot"] = tools.slot(day)
            if world["slot"].get("available", 0) <= 0:
                world["alternatives"] = _alternatives(tools, day)
        return {"decision": asdict(decide(request, world, now_ms()))}

    def ask_user(state: StepState) -> dict:
        decision = state["decision"]
        paused = decision["reason"] == conflicts.REASON
        question = {"reason": decision["reason"], "options": decision["options"]}
        if paused:
            question["conflicts"] = state.get("conflicts", [])
        answer = interrupt(question)
        update: dict[str, Any] = {"answer": answer}
        request = dict(state["request"])
        if answer.get("decision") == "choose" and answer.get("date"):
            request["payload"] = {**request["payload"], "date": answer["date"]}
            update["request"] = request
        if paused and answer.get("decision") in ("confirm", "send_with_note"):
            update["conflicts_acknowledged"] = True
            if answer["decision"] == "send_with_note":
                message = str(request["payload"].get("message", ""))
                request["payload"] = {**request["payload"],
                                      "message": conflicts.with_note(message, state.get("conflicts", []))}
                update["request"] = request
        return update

    def safety_review(state: StepState) -> dict:
        request = ActionRequest.model_validate(state["request"])
        if request.tool in EXTERNAL_TOOLS:
            return gate(request, state)
        if request.tool == "record_medication" and state.get("review") is None:
            return review_record(request)
        return {"gate": "pass"}

    def gate(request: ActionRequest, state: StepState) -> dict:
        # Irreversible step: does anything the planner never saw contradict it? (policy in conflicts.py)
        if board is None or state.get("conflicts_acknowledged"):
            return {"gate": "pass"}
        found = conflicts.detect(request, board.unseen_by(request.account_id, request.plan_id, request.step_key,
                                                          request.created_at_ms))
        if not found:
            return {"gate": "pass"}
        return {"gate": "pause", "conflicts": found,
                "decision": {"kind": "ASK_USER", "reason": conflicts.REASON, "options": conflicts.options(found)}}

    def review_record(request: ActionRequest) -> dict:
        # A medication record is compared with the user's other recent records (see safety.py). The result is kept
        # in the thread, so a step that parks later (or is re-dispatched) does not review again.
        if safety is None:
            return {"review": {"status": "skipped", "reason": "not_configured"}, "gate": "pass"}
        token = delegation.get()
        if not token:
            return {"review": {"status": "skipped", "reason": "no_medication_access"}, "gate": "pass"}
        taken_at = request.payload.get("takenAt")
        try:
            review = safety.review(str(request.payload.get("name", "")),
                                   int(taken_at) if isinstance(taken_at, (int, float)) else None, token)
        except SafetyUnavailable as error:
            raise ExternalPending(f"safety review unavailable: {error}") from error
        alerts = review.get("alerts") or []
        if alerts:
            post(Finding(request.account_id, request.step_key, request.plan_id, "safety_review", "safety_alert",
                         "high" if review.get("severity") == "high" else "moderate",
                         (alerts[0].get("findings") or [{}])[0].get("summary") or f"{request.payload.get('name')} 有用药提醒",
                         int(taken_at) if isinstance(taken_at, (int, float)) else now_ms(),
                         {"medication": request.payload.get("name"),
                          "alerts": [{"with": a.get("with"), "severity": a.get("severity")} for a in alerts]}))
        return {"review": review, "gate": "pass"}

    def executor(state: StepState) -> dict:
        request = ActionRequest.model_validate(state["request"])
        if request.tool == "ask_pharmacist":
            return ask_pharmacist(request)
        if request.tool not in EXTERNAL_TOOLS:
            # record_* steps live in the gateway's action_ledger (the pharmacist reads them back through a delegated,
            # read-only token); there is no external side effect to run here.
            result: dict[str, Any] = {"tool": request.tool, "accepted": True}
            review = state.get("review")
            if review is not None:
                result["safety"] = review
            alerted = bool(review and review.get("alerts"))
            return {"outcome": {"status": "DONE", "result": result,
                                "reason": f"safety_alert_{review.get('severity') or 'moderate'}" if alerted else None}}
        payload = request.payload
        if request.experiment_mode:
            # Same simulated LLM re-planning as the baselines: arguments are reworded on every re-execution.
            payload = rephrase(request.tool, payload, attempts.next(request.step_key))
        result = tools.execute(request.step_key, request.tool, payload)
        if result.status == "PENDING":
            raise ExternalPending(result.reason)
        if result.status == "REJECTED":
            options = [{"decision": "cancel"}]
            if result.reason == "slot_full":
                day = request.payload.get("date", "")
                options = [{"decision": "choose", "date": a["date"]} for a in _alternatives(tools, day)] + options
            return {"decision": {"kind": "ASK_USER", "reason": result.reason, "options": options}}
        return {"outcome": {"status": "DONE", "result": result.result, "reason": result.reason}}

    def cancel(state: StepState) -> dict:
        reason = state.get("decision", {}).get("reason") if state.get("decision", {}).get("kind") == "CANCEL" \
            else "cancelled_by_user"
        return {"outcome": {"status": "CANCELLED", "reason": reason}}

    def after_revalidate(state: StepState) -> str:
        return {"PROCEED": "safety_review", "ASK_USER": "ask_user", "CANCEL": "cancel"}[state["decision"]["kind"]]

    def after_ask(state: StepState) -> str:
        return "cancel" if state["answer"].get("decision") == "cancel" else "safety_review"

    def after_safety(state: StepState) -> str:
        return "ask_user" if state.get("gate") == "pause" else "executor"

    def after_executor(state: StepState) -> str:
        return END if state.get("outcome") else "ask_user"

    graph = StateGraph(StepState)
    for name, node in [("revalidate", revalidate), ("ask_user", ask_user), ("safety_review", safety_review),
                       ("executor", executor), ("cancel", cancel)]:
        graph.add_node(name, node)
    graph.add_edge(START, "revalidate")
    graph.add_conditional_edges("revalidate", after_revalidate, ["safety_review", "ask_user", "cancel"])
    graph.add_conditional_edges("ask_user", after_ask, ["safety_review", "cancel"])
    graph.add_conditional_edges("safety_review", after_safety, ["executor", "ask_user"])
    graph.add_conditional_edges("executor", after_executor, [END, "ask_user"])
    graph.add_edge("cancel", END)
    return graph.compile(checkpointer=checkpointer)


class StepRunner:
    """What the gateway talks to. Safe to call any number of times for the same step.

    A step whose graph is still running (e.g. a slow pharmacist answer after the gateway already timed out and
    re-dispatched) is not started a second time: the second caller gets PENDING and asks again later.
    The busy set is per process; running several agent replicas would need a Postgres advisory lock instead.
    """

    def __init__(self, graph) -> None:
        self.graph = graph
        self._busy: set[str] = set()
        self._lock = threading.Lock()

    def _claim(self, config: dict) -> bool:
        with self._lock:
            thread = config["configurable"]["thread_id"]
            if thread in self._busy:
                return False
            self._busy.add(thread)
            return True

    def _release(self, config: dict) -> None:
        with self._lock:
            self._busy.discard(config["configurable"]["thread_id"])

    @staticmethod
    def _config(account_id: str, step_key: str) -> dict:
        return {"configurable": {"thread_id": f"{account_id}:{step_key}"}}

    def run(self, request: ActionRequest) -> Outcome:
        config = self._config(request.account_id, request.step_key)
        with tracing.step(request, "run") as observation:
            outcome = self._exclusive(config, lambda: self._run(request, config))
            observation.update(output=outcome.model_dump())
        return outcome

    def resume(self, account_id: str, step_key: str, answer: dict[str, Any]) -> Outcome:
        config = self._config(account_id, step_key)
        stored = self.graph.get_state(config).values.get("request")
        if stored is None:
            return self._exclusive(config, lambda: self._resume(answer, config))
        with tracing.step(ActionRequest.model_validate(stored), "resume") as observation:
            outcome = self._exclusive(config, lambda: self._resume(answer, config))
            observation.update(output=outcome.model_dump())
        return outcome

    def _exclusive(self, config: dict, body: Callable[[], Outcome]) -> Outcome:
        # Guards reading the state as well as running it: a half-finished thread looks like neither "parked"
        # nor "done", so a second caller must not even interpret it.
        if not self._claim(config):
            return Outcome(status="PENDING", reason="step is already running")
        try:
            return body()
        finally:
            self._release(config)

    def _run(self, request: ActionRequest, config: dict) -> Outcome:
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            return self._invoke({"request": request.model_dump()}, config)
        if snapshot.interrupts:
            return self._needs_user(snapshot.interrupts[0].value)
        if snapshot.next:
            return self._invoke(None, config)  # parked mid-way (crash or PENDING): resume from the checkpoint
        return Outcome(**snapshot.values["outcome"])

    def _resume(self, answer: dict[str, Any], config: dict) -> Outcome:
        snapshot = self.graph.get_state(config)
        if not snapshot.interrupts:
            if snapshot.values.get("outcome"):
                return Outcome(**snapshot.values["outcome"])
            raise LookupError("step is not waiting for the user")
        return self._invoke(Command(resume=answer), config)

    def _invoke(self, payload: Any, config: dict) -> Outcome:
        try:
            out = self.graph.invoke(payload, {**config, "callbacks": tracing.callbacks()})
        except ExternalPending as pending:
            return Outcome(status="PENDING", reason=str(pending))
        except Unreachable as unreachable:
            return Outcome(status="PENDING", reason=f"cannot read current state: {unreachable}")
        if out.get("__interrupt__"):
            return self._needs_user(out["__interrupt__"][0].value)
        return Outcome(**out["outcome"])

    @staticmethod
    def _needs_user(value: dict[str, Any]) -> Outcome:
        result = {"options": value.get("options", [])}
        if value.get("conflicts"):
            result["conflicts"] = value["conflicts"]
        return Outcome(status="NEEDS_USER", result=result, reason=value.get("reason"))
