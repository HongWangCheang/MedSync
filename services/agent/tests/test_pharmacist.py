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

    def ask(self, question: str, session_id=None, owner=None, token=None, selection=None) -> dict:
        self.calls += 1
        self.last = {"question": question, "session_id": session_id, "owner": owner, "token": token,
                     "selection": selection}
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


def test_follow_up_carries_the_session_owner_and_delegated_token() -> None:
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"], seen["headers"] = json.loads(request.content), request.headers
        body = sse(("session", {"session_id": "11111111-2222-3333-4444-555555555555"}),
                   ("tool_call", {"name": "search_label", "args": {}}),
                   ("tool_result", {"name": "search_label", "status": "needs_selection", "citations": []}),
                   ("answer", {"text": "请问您指的是哪一种 Advil？", "grounded": True, "citations": {}}), ("done", {}))
        return httpx.Response(200, text=body)

    out = rag(handler).ask("ADVIL", session_id="11111111-2222-3333-4444-555555555555", owner="o.sig",
                           token="dlg_abc")
    assert seen["body"]["session_id"] == "11111111-2222-3333-4444-555555555555"
    assert seen["headers"]["x-medsync-owner"] == "o.sig"
    assert seen["headers"]["authorization"] == "Bearer dlg_abc"
    assert out["session_id"] == "11111111-2222-3333-4444-555555555555" and out["awaiting_choice"] is True


def test_signed_owner_is_stable_per_account_and_verifiable() -> None:
    import hashlib
    import hmac
    from medsync_agent.pharmacist import signed_owner

    a1, a2, b = signed_owner("alice", "s3cret"), signed_owner("alice", "s3cret"), signed_owner("bob", "s3cret")
    assert a1 == a2 and a1 != b
    owner, signature = a1.split(".")
    assert hmac.compare_digest(signature, hmac.new(b"s3cret", owner.encode(), hashlib.sha256).hexdigest())
    assert signed_owner("alice", "") is None  # no shared secret → no owner claim at all


def test_delegated_token_reaches_the_pharmacist_but_never_the_checkpoint(monkeypatch) -> None:
    from fastapi.testclient import TestClient
    from medsync_agent.api import create_app

    monkeypatch.setenv("MEDSYNC_INTERNAL_SECRET", "s3cret")
    pharmacist = FakePharmacist()
    saver = InMemorySaver()
    r = StepRunner(build_graph(InMemoryToolLedger(), FakeExternal(), saver, pharmacist=pharmacist))
    body = question("q9").model_dump(by_alias=True)
    body["payload"]["session_id"] = "11111111-2222-3333-4444-555555555555"
    with TestClient(create_app(r)) as client:
        reply = client.post("/v1/actions/run", json=body, headers={"X-MedSync-Delegation": "dlg_secret_token"})
    assert reply.json()["status"] == "DONE"
    assert pharmacist.last["token"] == "dlg_secret_token"
    assert pharmacist.last["session_id"] == "11111111-2222-3333-4444-555555555555"
    assert pharmacist.last["owner"].count(".") == 1
    stored = repr(list(saver.list({"configurable": {"thread_id": "acct:q9"}})))
    assert "dlg_secret_token" not in stored  # not in state, writes or metadata


def test_other_tools_never_see_a_delegation(monkeypatch) -> None:
    from medsync_agent.pharmacist import delegation
    assert delegation.get() is None


def test_candidates_become_choices_and_a_selection_is_forwarded() -> None:
    seen = {}
    candidates = [{"label_id": "a1", "version": "2", "name": "Tylenol Extra Strength", "manufacturer": "Kenvue"},
                  {"label_id": "b2", "version": "11", "name": "TYLENOL Extra Strength", "manufacturer": "Kenvue"}]

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, text=sse(
            ("session", {"session_id": "11111111-2222-3333-4444-555555555555"}),
            ("tool_result", {"name": "search_label", "status": "needs_selection", "citations": [],
                             "candidates": candidates}),
            ("answer", {"text": "请问是哪一款？", "grounded": True, "citations": {}})))

    out = rag(handler).ask("Tylenol 能喝酒吗", selection={"label_id": "b2", "version": "11", "extra": "x"})
    assert seen["body"]["selection"] == {"label_id": "b2", "version": "11"}
    assert out["awaiting_choice"] and [c["label_id"] for c in out["choices"]] == ["a1", "b2"]


def test_graph_forwards_only_a_well_formed_selection() -> None:
    pharmacist = FakePharmacist()
    r = runner(pharmacist)
    step = question("q20").model_dump(by_alias=True)
    step["payload"]["selection"] = {"label_id": "b2", "version": "11", "evil": "<script>"}
    r.run(ActionRequest.model_validate(step))
    assert pharmacist.last["selection"] == {"label_id": "b2", "version": "11"}
    step = question("q21").model_dump(by_alias=True)
    step["payload"]["selection"] = "b2"
    r.run(ActionRequest.model_validate(step))
    assert pharmacist.last["selection"] is None
