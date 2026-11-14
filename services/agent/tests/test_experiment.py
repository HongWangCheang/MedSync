"""The baselines must fail exactly where they are supposed to, or the comparison means nothing."""

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from medsync_agent.api import create_app
from medsync_agent.experiment import Attempts, BaselineRunner, rephrase
from medsync_agent.graph import StepRunner, build_graph
from medsync_agent.models import ActionRequest
from medsync_agent.tool_ledger import InMemoryToolLedger

from .fakes import FakeExternal


def step(mode: str, key: str = "k1") -> ActionRequest:
    return ActionRequest.model_validate({
        "account_id": "acct", "stepKey": key, "planId": "p", "stepIndex": 0, "tool": "book_appointment",
        "payload": {"patient_id": "p1", "department": "cardiology", "date": "2026-11-18", "note": "胃疼"},
        "preconditions": {"toolVersion": "v1"}, "experimentMode": mode})


def test_rephrase_changes_only_free_text_and_only_on_retries() -> None:
    payload = {"date": "2026-11-18", "note": "胃疼"}
    assert rephrase("book_appointment", payload, 0) == payload
    again = rephrase("book_appointment", payload, 1)
    assert again["date"] == payload["date"] and again["note"] != payload["note"]


def test_request_id_baseline_duplicates_on_redispatch_after_lost_response() -> None:
    ext = FakeExternal()
    runner = BaselineRunner(ext, Attempts())
    ext.fault = "after_commit"
    assert runner.run(step("request_id")).status == "PENDING"
    assert runner.run(step("request_id")).status == "DONE"
    assert ext.count("k1") == 2


def test_args_hash_baseline_is_defeated_by_reworded_arguments() -> None:
    ext = FakeExternal()
    runner = BaselineRunner(ext, Attempts())
    runner.run(step("args_hash"))
    runner.run(step("args_hash"))  # same step, re-dispatched: note reworded → different hash
    assert ext.count("k1") == 2


def test_full_mode_rewords_too_but_still_executes_once() -> None:
    ext = FakeExternal()
    attempts = Attempts()
    runner = StepRunner(build_graph(InMemoryToolLedger(), ext, InMemorySaver(), attempts=attempts))
    ext.fault = "after_commit"
    assert runner.run(step("full")).status == "PENDING"
    assert runner.run(step("full")).status == "DONE"
    assert ext.count("k1") == 1


def test_modes_are_refused_unless_experiments_are_enabled(monkeypatch) -> None:
    ext = FakeExternal()
    runner = StepRunner(build_graph(InMemoryToolLedger(), ext, InMemorySaver()))
    app = create_app(runner, BaselineRunner(ext, Attempts()))
    body = step("naive").model_dump(by_alias=True)
    with TestClient(app) as client:
        monkeypatch.delenv("MEDSYNC_EXPERIMENTS", raising=False)
        assert client.post("/v1/actions/run", json=body).status_code == 400
        monkeypatch.setenv("MEDSYNC_EXPERIMENTS", "1")
        assert client.post("/v1/actions/run", json=body).json()["status"] == "DONE"
