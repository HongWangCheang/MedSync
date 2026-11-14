"""One LangGraph thread per logical step (thread_id = account:step_key).

    START → revalidate ─┬─ PROCEED  → safety_review → executor ─┬─ DONE → END
                        ├─ ASK_USER → ask_user (interrupt) ──────┤  REJECTED (e.g. slot taken meanwhile) → ask_user
                        └─ CANCEL   → cancel → END               └─ PENDING → raise: node fails, checkpoint kept

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

from .executor import execute
from .experiment import Attempts, rephrase
from .external import External, Unreachable
from .models import EXTERNAL_TOOLS, ActionRequest, Outcome
from .pharmacist import Pharmacist, PharmacistMisconfigured, PharmacistUnavailable, owner_header
from .revalidate import decide
from .tool_ledger import ToolLedger


class StepState(TypedDict, total=False):
    request: dict[str, Any]
    decision: dict[str, Any]
    answer: dict[str, Any]
    outcome: dict[str, Any]


class ExternalPending(Exception):
    """The side effect's outcome is not known yet; the step stays parked at the executor."""


def _alternatives(external: External, day: str, days: int = 3) -> list[dict[str, Any]]:
    start = date.fromisoformat(day)
    found = []
    for offset in range(1, days + 1):
        candidate = (start + timedelta(days=offset)).isoformat()
        slot = external.slot(candidate)
        if slot.get("available", 0) > 0:
            found.append({"date": candidate, "available": slot["available"]})
    return found


def build_graph(ledger: ToolLedger, external: External, checkpointer: Any,
                now_ms: Callable[[], int] = lambda: int(time.time() * 1000), attempts: Attempts | None = None,
                pharmacist: Pharmacist | None = None):
    attempts = attempts or Attempts()

    def ask_pharmacist(request: ActionRequest) -> dict:
        # READ tool: no side effect to deduplicate, but the finished answer is stored in this step's thread, so a
        # re-dispatch returns it instead of paying for another model call.
        if pharmacist is None:
            return {"outcome": {"status": "FAILED", "reason": "pharmacist_not_configured"}}
        try:
            answer = pharmacist.ask(str(request.payload.get("question", "")),
                                    session_id=request.payload.get("session_id") or None,
                                    owner=owner_header(request.account_id))
        except PharmacistUnavailable as error:
            raise ExternalPending(f"pharmacist unavailable: {error}") from error
        except PharmacistMisconfigured as error:
            return {"outcome": {"status": "FAILED", "reason": f"pharmacist_not_configured: {error}"}}
        return {"outcome": {"status": "DONE", "result": answer,
                            "reason": None if answer["grounded"] else "refused_without_evidence"}}

    def revalidate(state: StepState) -> dict:
        request = ActionRequest.model_validate(state["request"])
        world: dict[str, Any] = {}
        if request.tool == "book_appointment":
            day = request.payload.get("date", "")
            world["slot"] = external.slot(day)
            if world["slot"].get("available", 0) <= 0:
                world["alternatives"] = _alternatives(external, day)
        return {"decision": asdict(decide(request, world, now_ms()))}

    def ask_user(state: StepState) -> dict:
        decision = state["decision"]
        answer = interrupt({"reason": decision["reason"], "options": decision["options"]})
        update: dict[str, Any] = {"answer": answer}
        if answer.get("decision") == "choose" and answer.get("date"):
            request = dict(state["request"])
            request["payload"] = {**request["payload"], "date": answer["date"]}
            update["request"] = request
        return update

    def safety_review(state: StepState) -> dict:
        # Phase 3: interaction / conflict checks before irreversible actions. Pass-through for now.
        return {}

    def executor(state: StepState) -> dict:
        request = ActionRequest.model_validate(state["request"])
        if request.tool == "ask_pharmacist":
            return ask_pharmacist(request)
        if request.tool not in EXTERNAL_TOOLS:
            # record_* already reached MySQL through the sync path; no external side effect here.
            return {"outcome": {"status": "DONE", "result": {"tool": request.tool, "accepted": True}}}
        payload = request.payload
        if request.experiment_mode:
            # Same simulated LLM re-planning as the baselines: arguments are reworded on every re-execution.
            payload = rephrase(request.tool, payload, attempts.next(request.step_key))
        result = execute(request.step_key, request.tool, payload, ledger, external)
        if result.status == "PENDING":
            raise ExternalPending(result.reason)
        if result.status == "REJECTED":
            options = [{"decision": "cancel"}]
            if result.reason == "slot_full":
                day = request.payload.get("date", "")
                options = [{"decision": "choose", "date": a["date"]} for a in _alternatives(external, day)] + options
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

    def after_executor(state: StepState) -> str:
        return END if state.get("outcome") else "ask_user"

    graph = StateGraph(StepState)
    for name, node in [("revalidate", revalidate), ("ask_user", ask_user), ("safety_review", safety_review),
                       ("executor", executor), ("cancel", cancel)]:
        graph.add_node(name, node)
    graph.add_edge(START, "revalidate")
    graph.add_conditional_edges("revalidate", after_revalidate, ["safety_review", "ask_user", "cancel"])
    graph.add_conditional_edges("ask_user", after_ask, ["safety_review", "cancel"])
    graph.add_edge("safety_review", "executor")
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
        return self._exclusive(config, lambda: self._run(request, config))

    def resume(self, account_id: str, step_key: str, answer: dict[str, Any]) -> Outcome:
        config = self._config(account_id, step_key)
        return self._exclusive(config, lambda: self._resume(answer, config))

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
            out = self.graph.invoke(payload, config)
        except ExternalPending as pending:
            return Outcome(status="PENDING", reason=str(pending))
        except Unreachable as unreachable:
            return Outcome(status="PENDING", reason=f"cannot read current state: {unreachable}")
        if out.get("__interrupt__"):
            return self._needs_user(out["__interrupt__"][0].value)
        return Outcome(**out["outcome"])

    @staticmethod
    def _needs_user(value: dict[str, Any]) -> Outcome:
        return Outcome(status="NEEDS_USER", result={"options": value.get("options", [])}, reason=value.get("reason"))
