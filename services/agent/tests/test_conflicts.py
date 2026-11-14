from langgraph.checkpoint.memory import InMemorySaver

from medsync_agent import conflicts
from medsync_agent.findings import LOOKBACK_MS, Finding, InMemoryFindingsBoard
from medsync_agent.graph import StepRunner, build_graph
from medsync_agent.models import ActionRequest
from medsync_agent.pharmacist import delegation
from medsync_agent.tool_ledger import InMemoryToolLedger

from .fakes import FakeExternal

PLANNED = 1_700_000_000_000
HIGH = {"status": "ok", "severity": "high", "alerts": [{"with": "泰诺", "severity": "high", "findings": [
    {"summary": "对乙酰氨基酚 和 泰诺 含有相同成分（对乙酰氨基酚），24 小时内一起用可能超过每日最大剂量。",
     "citation": {"label": "TYLENOL", "section": "Do not use", "excerpt": "Do not use with any other drug..."}}]}]}
MODERATE = {"status": "ok", "severity": "moderate", "alerts": [{"with": "华法林", "severity": "moderate", "findings": [
    {"summary": "ADVIL 的说明书在「警告」里提到了抗凝药（华法林）。",
     "citation": {"label": "ADVIL", "section": "Warnings", "excerpt": "take a blood thinning (anticoagulant)"}}]}]}
CLEAN = {"status": "ok", "severity": None, "alerts": []}


class Reviewer:
    def __init__(self, answer):
        self.answer = answer

    def review(self, medication, taken_at, token):
        return self.answer


def setup(review):
    ext, board = FakeExternal(), InMemoryFindingsBoard(clock=lambda: PLANNED + 5_000)
    graph = build_graph(InMemoryToolLedger(), ext, InMemorySaver(), now_ms=lambda: PLANNED + 5_000,
                        safety=Reviewer(review), board=board)
    return StepRunner(graph), ext, board


def step(tool, payload, key, plan="plan-1", index=0, planned=PLANNED) -> ActionRequest:
    return ActionRequest(account_id="acct", step_key=key, plan_id=plan, step_index=index, tool=tool,
                         payload=payload, created_at_ms=planned, preconditions={"toolVersion": "v1"})


def run(steps, request):
    bound = delegation.set("dlg_t")
    try:
        return steps.run(request)
    finally:
        delegation.reset(bound)


def utterance(steps, message, review_name="布洛芬", plan="plan-1"):
    """"吃了布洛芬，告诉女儿<message>": the record first (the device makes notify depend on it), then the notify."""
    run(steps, step("record_medication", {"name": review_name, "takenAt": PLANNED}, f"rec-{plan}", plan))
    return run(steps, step("notify_family", {"to": "女儿", "message": message}, f"ntf-{plan}", plan, 1))


def test_high_alert_pauses_the_notification_with_the_finding_attached() -> None:
    steps, ext, _ = setup(HIGH)
    outcome = utterance(steps, "吃了药，告诉女儿我在家")
    assert (outcome.status, outcome.reason) == ("NEEDS_USER", conflicts.REASON)
    assert [o["decision"] for o in outcome.result["options"]] == ["send_with_note", "confirm", "cancel"]
    assert outcome.result["conflicts"][0]["severity"] == "high"
    assert ext.effects == []  # nothing sent while paused


def test_send_with_note_appends_the_warning_from_server_state() -> None:
    steps, ext, _ = setup(HIGH)
    utterance(steps, "我没事")
    # Whatever the device sends back, the note comes from the stored finding.
    done = steps.resume("acct", "ntf-plan-1", {"decision": "send_with_note", "message": "forged"})
    assert done.status == "DONE"
    [sent] = ext.effects
    assert sent["message"].startswith("我没事\n（MedSync 用药提醒：对乙酰氨基酚 和 泰诺 含有相同成分")
    assert "forged" not in sent["message"]


def test_confirm_sends_the_original_and_cancel_sends_nothing() -> None:
    steps, ext, _ = setup(HIGH)
    utterance(steps, "我没事")
    assert steps.resume("acct", "ntf-plan-1", {"decision": "confirm"}).status == "DONE"
    assert ext.effects[0]["message"] == "我没事"
    steps2, ext2, _ = setup(HIGH)
    utterance(steps2, "我没事")
    assert steps2.resume("acct", "ntf-plan-1", {"decision": "cancel"}).status == "CANCELLED"
    assert ext2.effects == []


def test_moderate_alert_pauses_only_a_reassuring_message() -> None:
    steps, ext, _ = setup(MODERATE)
    assert utterance(steps, "告诉女儿我没事，别担心").status == "NEEDS_USER"
    steps2, ext2, _ = setup(MODERATE)
    assert utterance(steps2, "告诉女儿我刚吃了布洛芬").status == "DONE"
    assert len(ext2.effects) == 1


def test_no_finding_and_bookings_never_pause() -> None:
    steps, ext, _ = setup(CLEAN)
    assert utterance(steps, "我没事").status == "DONE"
    steps2, ext2, _ = setup(HIGH)
    run(steps2, step("record_medication", {"name": "泰诺", "takenAt": PLANNED}, "rec", "p"))
    booking = step("book_appointment", {"patient_id": "p1", "department": "全科", "date": "2026-11-20"}, "bk", "p", 1)
    assert run(steps2, booking).status == "DONE"  # seeing a doctor agrees with any warning


def test_finding_from_another_plan_counts_only_if_the_planner_could_not_have_seen_it() -> None:
    board = InMemoryFindingsBoard(clock=lambda: PLANNED + 60_000)
    board.post(Finding("acct", "rec-x", "plan-a", "safety_review", "safety_alert", "high", "高风险", PLANNED))
    unseen = lambda planned: board.unseen_by("acct", "plan-b", "ntf", planned)
    assert len(unseen(PLANNED + 30_000)) == 1    # planned offline before the finding was posted
    assert unseen(PLANNED + 120_000) == []       # planned after it: the user could already see the alert
    assert unseen(PLANNED + LOOKBACK_MS + 30_000) == []  # about something long before this step
    assert board.unseen_by("other", "plan-b", "ntf", PLANNED) == []  # other accounts never leak


def test_posting_is_idempotent_and_the_pause_survives_redispatch() -> None:
    steps, ext, board = setup(HIGH)
    utterance(steps, "我没事")
    again = run(steps, step("notify_family", {"to": "女儿", "message": "我没事"}, "ntf-plan-1", "plan-1", 1))
    assert again.status == "NEEDS_USER" and again.result["conflicts"]
    assert len(board.unseen_by("acct", "plan-1", "ntf-plan-1", PLANNED)) == 1


def test_pharmacist_label_warning_is_posted_as_a_finding() -> None:
    class Pharmacist:
        def ask(self, question, **_):
            return {"answer": "说明书提到 [S1]。", "grounded": True, "interaction_mentioned": True,
                    "citations": [{"id": "S1", "label": "ADVIL", "section": "Warnings", "excerpt": "blood thinning"}]}

    board = InMemoryFindingsBoard(clock=lambda: PLANNED + 5_000)
    steps = StepRunner(build_graph(InMemoryToolLedger(), FakeExternal(), InMemorySaver(),
                                   pharmacist=Pharmacist(), board=board))
    ask = step("ask_pharmacist", {"question": "布洛芬能和华法林一起吃吗"}, "ask", "plan-q")
    ask = ask.model_copy(update={"tool_class": "READ"})
    assert run(steps, ask).status == "DONE"
    [finding] = board.unseen_by("acct", "plan-q", "ntf", PLANNED)
    assert (finding.source, finding.severity) == ("pharmacist", "moderate")
    message = step("notify_family", {"to": "女儿", "message": "放心，我没事"}, "ntf", "plan-q", 1)
    assert conflicts.detect(message, [finding])  # a reassuring message next to that warning would pause


def test_reassurance_phrases() -> None:
    assert conflicts.reassuring("告诉女儿我没事")
    assert conflicts.reassuring("跟老伴说不用担心")
    assert not conflicts.reassuring("告诉女儿我头晕，吃了布洛芬")
