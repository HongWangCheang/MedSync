from medsync_agent.executor import execute
from medsync_agent.tool_ledger import Claim, InMemoryToolLedger

from .fakes import FakeExternal

BOOK = {"patient_id": "p1", "department": "cardiology", "date": "2026-11-18", "note": ""}


def test_retry_after_commit_timeout_reconciles_instead_of_booking_twice() -> None:
    ledger, ext = InMemoryToolLedger(), FakeExternal()
    ext.fault = "after_commit"

    first = execute("k1", "book_appointment", BOOK, ledger, ext)
    assert first.status == "PENDING"
    assert ext.count("k1") == 1  # it DID happen; only the response was lost

    second = execute("k1", "book_appointment", {**BOOK, "note": "re-planned by the LLM"}, ledger, ext)
    assert (second.status, second.reason) == ("DONE", "reconciled")
    assert ext.count("k1") == 1


def test_retry_after_lost_request_calls_exactly_once_more() -> None:
    ledger, ext = InMemoryToolLedger(), FakeExternal()
    ext.fault = "before_commit"

    assert execute("k1", "book_appointment", BOOK, ledger, ext).status == "PENDING"
    assert execute("k1", "book_appointment", BOOK, ledger, ext).status == "DONE"
    assert ext.count("k1") == 1


def test_committed_step_is_replayed_without_touching_the_external_system() -> None:
    ledger, ext = InMemoryToolLedger(), FakeExternal()
    done = execute("k1", "notify_family", {"to": "daughter", "message": "dizzy"}, ledger, ext)
    calls = ext.calls

    again = execute("k1", "notify_family", {"to": "daughter", "message": "I feel dizzy"}, ledger, ext)
    assert (again.status, again.result) == ("DONE", done.result)
    assert ext.calls == calls


def test_concurrent_attempt_backs_off_while_the_lease_is_live() -> None:
    ledger = InMemoryToolLedger()
    assert ledger.claim("k1", "book_appointment", BOOK, lease_s=30).claim is Claim.NEW
    assert execute("k1", "book_appointment", BOOK, ledger, FakeExternal()).status == "PENDING"


def test_rejection_releases_the_step_so_a_corrected_retry_can_run() -> None:
    ledger, ext = InMemoryToolLedger(), FakeExternal()
    ext.slots["2026-11-18"] = {"available": 0, "version": 3}
    assert execute("k1", "book_appointment", BOOK, ledger, ext).reason == "slot_full"
    assert execute("k1", "book_appointment", {**BOOK, "date": "2026-11-19"}, ledger, ext).status == "DONE"
    assert ext.count("k1") == 1
