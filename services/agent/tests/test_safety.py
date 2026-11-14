import httpx
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

from medsync_agent.api import create_app
from medsync_agent.graph import StepRunner, build_graph
from medsync_agent.models import ActionRequest
from medsync_agent.pharmacist import delegation
from medsync_agent.safety import RagSafetyReviewer, SafetyUnavailable
from medsync_agent.tool_ledger import InMemoryToolLedger

from .fakes import FakeExternal

ALERT = {"status": "ok", "severity": "moderate", "unresolved": [], "checked": [{"name": "华法林"}],
         "alerts": [{"with": "华法林", "severity": "moderate", "kinds": ["label_warning"],
                     "findings": [{"summary": "ADVIL 的说明书在「警告」里提到了抗凝药（华法林）。",
                                   "citation": {"label": "ADVIL", "section": "Warnings",
                                                "excerpt": "take a blood thinning (anticoagulant) or steroid drug"}}]}]}


class FakeReviewer:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = []

    def review(self, medication, taken_at, token):
        self.calls.append((medication, taken_at, token))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def record(name="布洛芬", key="k-med") -> ActionRequest:
    return ActionRequest(account_id="acct", step_key=key, plan_id="p", step_index=0, tool="record_medication",
                         tool_class="WRITE_IDEMPOTENT", payload={"name": name, "takenAt": 1_700_000_000_000})


def runner(reviewer) -> StepRunner:
    return StepRunner(build_graph(InMemoryToolLedger(), FakeExternal(), InMemorySaver(), safety=reviewer))


def run(steps: StepRunner, request: ActionRequest, token: str | None = "dlg_t"):
    bound = delegation.set(token)
    try:
        return steps.run(request)
    finally:
        delegation.reset(bound)


def test_alert_is_attached_to_the_record_with_its_citation() -> None:
    reviewer = FakeReviewer([ALERT])
    outcome = run(runner(reviewer), record())
    assert outcome.status == "DONE"
    assert outcome.reason == "safety_alert_moderate"
    assert outcome.result["safety"]["alerts"][0]["findings"][0]["citation"]["label"] == "ADVIL"
    assert reviewer.calls == [("布洛芬", 1_700_000_000_000, "dlg_t")]


def test_rag_down_parks_the_step_and_the_retry_reviews_with_the_new_token() -> None:
    reviewer = FakeReviewer([SafetyUnavailable("connect timeout"), ALERT])
    steps = runner(reviewer)
    assert run(steps, record(), token="dlg_first").status == "PENDING"
    outcome = run(steps, record(), token="dlg_second")
    assert (outcome.status, outcome.reason) == ("DONE", "safety_alert_moderate")
    assert [c[2] for c in reviewer.calls] == ["dlg_first", "dlg_second"]
    # Finished: a later poll replays the stored outcome without reviewing (or reading the list) again.
    assert run(steps, record(), token="dlg_third").reason == "safety_alert_moderate"
    assert len(reviewer.calls) == 2


def test_the_token_never_reaches_the_checkpoint() -> None:
    steps = runner(FakeReviewer([ALERT]))
    run(steps, record(), token="dlg_secret_value")
    state = steps.graph.get_state(steps._config("acct", "k-med"))
    assert "dlg_secret_value" not in repr(state.values)


def test_without_a_token_the_record_settles_and_says_it_was_not_checked() -> None:
    reviewer = FakeReviewer([])
    outcome = run(runner(reviewer), record(), token=None)
    assert (outcome.status, outcome.reason) == ("DONE", None)
    assert outcome.result["safety"] == {"status": "skipped", "reason": "no_medication_access"}
    assert reviewer.calls == []


def test_other_tools_are_not_reviewed() -> None:
    reviewer = FakeReviewer([])
    request = record().model_copy(update={"tool": "record_symptom", "payload": {"category": "头晕"}})
    outcome = run(runner(reviewer), request)
    assert outcome.status == "DONE" and "safety" not in outcome.result
    assert reviewer.calls == []


def test_http_client_maps_failures() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer dlg_t"
        name = request.read().decode()
        if "down" in name:
            return httpx.Response(503)
        if "bad" in name:
            return httpx.Response(422)
        return httpx.Response(200, json=ALERT)

    client = RagSafetyReviewer("http://rag", transport=httpx.MockTransport(handler))
    assert client.review("布洛芬", 1, "dlg_t")["alerts"]
    assert client.review("bad", None, "dlg_t") == {"status": "skipped", "reason": "http_422"}
    try:
        client.review("down", None, "dlg_t")
        raise AssertionError("expected SafetyUnavailable")
    except SafetyUnavailable:
        pass


def test_api_binds_the_delegation_for_medication_records_only() -> None:
    seen = []

    class Reviewer:
        def review(self, medication, taken_at, token):
            seen.append(token)
            return {"status": "ok", "alerts": []}

    app = create_app(runner=runner(Reviewer()), baseline=None)
    with TestClient(app) as client:
        body = record().model_dump(by_alias=True)
        response = client.post("/v1/actions/run", json=body, headers={"X-MedSync-Delegation": "dlg_t"})
        assert response.json()["status"] == "DONE"
        symptom = {**body, "stepKey": "k-sym", "tool": "record_symptom", "payload": {"category": "头晕"}}
        client.post("/v1/actions/run", json=symptom, headers={"X-MedSync-Delegation": "dlg_t"})
    assert seen == ["dlg_t"]
