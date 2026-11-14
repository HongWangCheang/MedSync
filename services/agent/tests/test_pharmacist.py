import json
import threading

import httpx
import pytest
from langgraph.checkpoint.memory import InMemorySaver

from medsync_agent.graph import StepRunner, build_graph
from medsync_agent.models import ActionRequest
from medsync_agent.pharmacist import (PharmacistMisconfigured, PharmacistUnavailable, RagPharmacist, parse_sse)
from medsync_agent.tool_ledger import InMemoryToolLedger

from .fakes import FakeExternal

ANSWER = {
    "text": "布洛芬说明书提到，正在服用阿司匹林时，使用前应先询问医生或药师 [S1]。", "grounded": True,
    "refusal_reason": None, "steps": 2,
    "citations": {"S1": {"label_name": "Advil", "section": "Ask a doctor or pharmacist before use if you are",
                         "text": "taking aspirin for heart attack or stroke, because ibuprofen may decrease this "
                                 "benefit of aspirin" * 10,
                         "source_url": "https://api.fda.gov/drug/label.json?search=id:abc"}},
}


def sse(*events: tuple[str, dict]) -> str:
    return "".join(f"event: {e}\ndata: {json.dumps(d, ensure_ascii=False)}\n\n" for e, d in events)


def rag(handler) -> RagPharmacist:
    return RagPharmacist("http://rag", transport=httpx.MockTransport(handler))


def test_parse_sse_handles_a_stream_without_a_trailing_blank_line() -> None:
    events = list(parse_sse(["event: session", 'data: {"session_id": "x"}', "", "event: done", "data: {}"]))
    assert events == [("session", {"session_id": "x"}), ("done", {})]


def test_grounded_answer_keeps_citations_as_short_excerpts() -> None:
    body = sse(("session", {"session_id": "s"}), ("tool_call", {"name": "check_interaction", "args": {}}),
               ("tool_result", {"name": "check_interaction", "status": "mentioned"}), ("answer", ANSWER), ("done", {}))
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    out = rag(handler).ask("布洛芬能和阿司匹林一起吃吗？")
    assert seen["body"] == {"message": "布洛芬能和阿司匹林一起吃吗？"}
    assert out["grounded"] and out["tools"] == ["check_interaction"]
    assert out["citations"][0]["id"] == "S1" and len(out["citations"][0]["excerpt"]) == 400


@pytest.mark.parametrize("code,kind", [("missing_key", PharmacistMisconfigured), ("rate_limited", PharmacistUnavailable),
                                       ("timeout", PharmacistUnavailable)])
def test_error_events_are_sorted_into_permanent_and_transient(code, kind) -> None:
    body = sse(("session", {}), ("error", {"code": code, "message": "x"}), ("done", {}))
    with pytest.raises(kind):
        rag(lambda r: httpx.Response(200, text=body)).ask("q?")


def test_network_failure_and_truncated_stream_are_transient() -> None:
    def refuse(request):
        raise httpx.ConnectError("refused")

    with pytest.raises(PharmacistUnavailable):
        rag(refuse).ask("q?")
    with pytest.raises(PharmacistUnavailable):
        rag(lambda r: httpx.Response(200, text=sse(("session", {})))).ask("q?")


class FakePharmacist:
    def __init__(self, failures: list[Exception] | None = None, gate: threading.Event | None = None) -> None:
        self.calls = 0
        self.failures = failures or []
        self.gate = gate

    def ask(self, question: str, session_id=None, owner=None) -> dict:
        self.calls += 1
        self.last = {"question": question, "session_id": session_id, "owner": owner}
        if self.gate:
            self.gate.wait(5)
        if self.failures:
            raise self.failures.pop(0)
        return {"answer": "…[S1]", "grounded": True, "refusal_reason": None, "citations": [], "tools": []}


def question(key: str = "q1") -> ActionRequest:
    return ActionRequest.model_validate({"account_id": "acct", "stepKey": key, "planId": "p", "stepIndex": 0,
                                         "tool": "ask_pharmacist", "toolClass": "READ",
                                         "payload": {"question": "布洛芬能和阿司匹林一起吃吗？"},
                                         "preconditions": {"toolVersion": "v1"}})


def runner(pharmacist) -> StepRunner:
    return StepRunner(build_graph(InMemoryToolLedger(), FakeExternal(), InMemorySaver(), pharmacist=pharmacist))


def test_answer_is_stored_so_polling_does_not_call_the_model_again() -> None:
    pharmacist = FakePharmacist()
    r = runner(pharmacist)
    assert r.run(question()).status == "DONE"
    assert r.run(question()).result["grounded"] is True
    assert pharmacist.calls == 1


def test_transient_failure_parks_the_step_and_the_next_dispatch_answers() -> None:
    pharmacist = FakePharmacist([PharmacistUnavailable("rate_limited")])
    r = runner(pharmacist)
    assert r.run(question()).status == "PENDING"
    assert r.run(question()).status == "DONE"
    assert pharmacist.calls == 2


def test_missing_configuration_fails_with_a_readable_reason() -> None:
    assert runner(FakePharmacist([PharmacistMisconfigured("missing_key")])).run(question()).reason == \
        "pharmacist_not_configured: missing_key"
    assert runner(None).run(question()).reason == "pharmacist_not_configured"


def test_a_redispatch_while_the_answer_is_still_running_does_not_start_a_second_call() -> None:
    gate = threading.Event()
    pharmacist = FakePharmacist(gate=gate)
    r = runner(pharmacist)
    first = {}
    worker = threading.Thread(target=lambda: first.setdefault("out", r.run(question())))
    worker.start()
    while pharmacist.calls == 0:
        pass
    second = r.run(question())  # the gateway timed out and re-dispatched while the model is still answering
    gate.set()
    worker.join()
    assert second.status == "PENDING" and second.reason == "step is already running"
    assert first["out"].status == "DONE" and pharmacist.calls == 1


def test_follow_up_carries_the_session_and_a_per_account_owner() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"], seen["auth"] = json.loads(request.content), request.headers.get("authorization")
        body = sse(("session", {"session_id": "11111111-2222-3333-4444-555555555555"}),
                   ("tool_call", {"name": "search_label", "args": {}}),
                   ("tool_result", {"name": "search_label", "status": "needs_selection", "citations": []}),
                   ("answer", {"text": "请问您指的是哪一种 Advil？", "grounded": True, "citations": {}}), ("done", {}))
        return httpx.Response(200, text=body)

    out = rag(handler).ask("ADVIL", session_id="11111111-2222-3333-4444-555555555555", owner="MedSync-Account abc")
    assert seen["body"]["session_id"] == "11111111-2222-3333-4444-555555555555"
    assert seen["auth"] == "MedSync-Account abc"
    assert out["session_id"] == "11111111-2222-3333-4444-555555555555" and out["awaiting_choice"] is True


def test_graph_passes_the_session_and_isolates_accounts() -> None:
    pharmacist = FakePharmacist()
    r = runner(pharmacist)
    step = question("q9").model_dump(by_alias=True)
    step["payload"]["session_id"] = "11111111-2222-3333-4444-555555555555"
    r.run(ActionRequest.model_validate(step))
    first_owner = pharmacist.last["owner"]
    assert pharmacist.last["session_id"] == "11111111-2222-3333-4444-555555555555"
    r.run(ActionRequest.model_validate({**step, "account_id": "someone-else", "stepKey": "q10"}))
    assert pharmacist.last["owner"] != first_owner and not first_owner.startswith("Bearer")
