"""One LangGraph thread per logical step (thread_id = account:step_key).

    START → revalidate ─┬─ PROCEED  → safety_review → executor ─┬─ DONE → END
                        ├─ ASK_USER → ask_user (interrupt) ──────┤  REJECTED (e.g. slot taken meanwhile) → ask_user
                        └─ CANCEL   → cancel → END               └─ PENDING → raise: node fails, checkpoint kept

Durable execution: a node that raises (external unreachable) leaves the thread parked at that node. Re-dispatching
the same step resumes from there (`invoke(None)`), so revalidate is not re-run and the executor's ledger decides
whether the side effect already happened. A finished thread just returns its stored outcome.
"""

from __future__ import annotations

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
                now_ms: Callable[[], int] = lambda: int(time.time() * 1000), attempts: Attempts | None = None):
    attempts = attempts or Attempts()

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
        if request.tool not in EXTERNAL_TOOLS:
            # record_* already reached MySQL through the sync path; ask_pharmacist is wired to the RAG service in
            # phase 1 week 2. Neither creates an external side effect here.
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
    """What the gateway talks to. Safe to call any number of times for the same step."""

    def __init__(self, graph) -> None:
        self.graph = graph

    @staticmethod
    def _config(account_id: str, step_key: str) -> dict:
        return {"configurable": {"thread_id": f"{account_id}:{step_key}"}}

    def run(self, request: ActionRequest) -> Outcome:
        config = self._config(request.account_id, request.step_key)
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            return self._invoke({"request": request.model_dump()}, config)
        if snapshot.interrupts:
            return self._needs_user(snapshot.interrupts[0].value)
        if snapshot.next:
            return self._invoke(None, config)  # parked mid-way (crash or PENDING): resume from the checkpoint
        return Outcome(**snapshot.values["outcome"])

    def resume(self, account_id: str, step_key: str, answer: dict[str, Any]) -> Outcome:
        config = self._config(account_id, step_key)
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
