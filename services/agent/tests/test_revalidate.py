from medsync_agent.models import ActionRequest
from medsync_agent.revalidate import decide


def request(**overrides) -> ActionRequest:
    base = {"account_id": "a", "stepKey": "k", "planId": "p", "stepIndex": 0, "tool": "book_appointment",
            "payload": {"date": "2026-11-18"}, "preconditions": {"slotVersion": 1, "toolVersion": "v1"}}
    return ActionRequest.model_validate({**base, **overrides})


def test_slot_taken_while_offline_asks_user_with_alternatives() -> None:
    world = {"slot": {"available": 0, "version": 9}, "alternatives": [{"date": "2026-11-19", "available": 2}]}
    d = decide(request(), world, now_ms=0)
    assert (d.kind, d.reason) == ("ASK_USER", "slot_full")
    assert {"decision": "choose", "date": "2026-11-19"} in d.options


def test_changed_but_still_valid_precondition_proceeds() -> None:
    d = decide(request(), {"slot": {"available": 2, "version": 7}}, now_ms=0)
    assert (d.kind, d.reason) == ("PROCEED", "precondition_changed_still_valid")


def test_expired_step_goes_back_to_the_user() -> None:
    d = decide(request(tool="notify_family", payload={}, expiresAtMs=1_000), {}, now_ms=2_000)
    assert (d.kind, d.reason) == ("ASK_USER", "expired")


def test_step_planned_against_an_old_tool_contract_is_not_executed() -> None:
    d = decide(request(preconditions={"toolVersion": "v0"}), {"slot": {"available": 3}}, now_ms=0)
    assert d.reason == "tool_changed"
