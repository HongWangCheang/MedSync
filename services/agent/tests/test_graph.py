from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from medsync_agent.api import create_app
from medsync_agent.graph import StepRunner, build_graph
from medsync_agent.models import ActionRequest
from medsync_agent.tool_ledger import InMemoryToolLedger

from .fakes import FakeExternal


def make(now_ms: int = 0) -> tuple[StepRunner, FakeExternal]:
    ext = FakeExternal()
    return StepRunner(build_graph(InMemoryToolLedger(), ext, InMemorySaver(), now_ms=lambda: now_ms)), ext


def booking(key: str = "k1", **overrides) -> ActionRequest:
    body = {"account_id": "acct", "stepKey": key, "planId": "p1", "stepIndex": 0, "tool": "book_appointment",
            "toolClass": "IRREVERSIBLE", "payload": {"patient_id": "p1", "department": "cardiology",
                                                      "date": "2026-11-18"},
            "preconditions": {"slotVersion": 1, "toolVersion": "v1"}}
    return ActionRequest.model_validate({**body, **overrides})


def test_redispatching_a_finished_step_returns_the_stored_outcome() -> None:
    runner, ext = make()
    first = runner.run(booking())
    again = runner.run(booking())
    assert first.status == again.status == "DONE"
    assert again.result == first.result
    assert ext.count("k1") == 1


def test_pending_step_resumes_at_the_executor_without_re_running_revalidate() -> None:
    runner, ext = make()
    ext.fault = "after_commit"
    assert runner.run(booking()).status == "PENDING"
    reads = ext.slot_reads

    resumed = runner.run(booking())
    assert (resumed.status, resumed.reason) == ("DONE", "reconciled")
    assert ext.slot_reads == reads  # durable execution: parked at executor, revalidate not repeated
    assert ext.count("k1") == 1


def test_slot_taken_offline_interrupts_then_user_picks_another_day() -> None:
    runner, ext = make()
    ext.slots["2026-11-18"] = {"available": 0, "version": 4}

    waiting = runner.run(booking())
    assert (waiting.status, waiting.reason) == ("NEEDS_USER", "slot_full")
    assert runner.run(booking()).status == "NEEDS_USER"  # polling while waiting does not re-ask or re-run

    done = runner.resume("acct", "k1", {"decision": "choose", "date": "2026-11-19"})
    assert done.status == "DONE" and done.result["date"] == "2026-11-19"
    assert ext.count("k1") == 1


def test_expired_notification_is_cancelled_by_the_user_and_never_sent() -> None:
    runner, ext = make(now_ms=10_000)
    step = booking(tool="notify_family", payload={"to": "daughter", "message": "dizzy"}, expiresAtMs=5_000,
                   preconditions={})
    assert runner.run(step).reason == "expired"
    assert runner.resume("acct", "k1", {"decision": "cancel"}).status == "CANCELLED"
    assert ext.calls == 0


def test_http_api_round_trip() -> None:
    runner, ext = make()
    ext.slots["2026-11-18"] = {"available": 0, "version": 4}
    with TestClient(create_app(runner)) as client:
        body = booking().model_dump(by_alias=True)
        assert client.post("/v1/actions/run", json=body).json()["status"] == "NEEDS_USER"
        resumed = client.post("/v1/actions/k1/resume", json={"account_id": "acct", "decision": "choose",
                                                             "date": "2026-11-20"})
        assert resumed.json()["status"] == "DONE"


def test_a_decision_cut_off_mid_execution_is_finished_when_sent_again() -> None:
    # Found by eval/run_matrix.py: the user chose, the external call could not complete, the app re-sent the choice.
    runner, ext = make()
    ext.slots["2026-11-18"] = {"available": 0, "version": 4}
    assert runner.run(booking()).status == "NEEDS_USER"
    ext.fault = "down"
    assert runner.resume("acct", "k1", {"decision": "choose", "date": "2026-11-19"}).status == "PENDING"
    ext.fault = None
    # A different answer the second time does not replace the first: that one is already under way.
    again = runner.resume("acct", "k1", {"decision": "cancel"})
    assert again.status == "DONE" and again.result["date"] == "2026-11-19"
    assert ext.count("k1") == 1
