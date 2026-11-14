"""Simulated external systems: a hospital booking desk and a family-notification service.

They deliberately do NOT deduplicate. Like many real third-party APIs, every POST is a real side effect, so a
duplicate booking or a second SMS is visible in /metrics/side_effects. That endpoint is the ground truth for IVR
(Idempotency Violation Rate): the evaluation never trusts what the app or the agent *think* happened.

`ref` is the caller's step_key. The systems store it and let callers look a side effect up by it (the "did my call
land?" query the agent's executor uses after an ambiguous timeout), but they never use it to drop a request.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import Counter

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

DEFAULT_CAPACITY = 5

app = FastAPI(title="MedSync external mocks")
_lock = threading.Lock()
_slots: dict[str, dict] = {}  # date -> {"available": int, "version": int}
_bookings: list[dict] = []
_notifications: list[dict] = []
_faults: dict[str, dict] = {}  # path -> {"delay_s": float, "remaining": int}


class BookingIn(BaseModel):
    patient_id: str
    department: str
    date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str = ""
    ref: str
    trace: str = ""  # evaluation episode id; survives baselines that change ref on every retry


class NotifyIn(BaseModel):
    to: str
    message: str
    ref: str
    trace: str = ""


class SlotSet(BaseModel):
    available: int = Field(ge=0)


class FaultSet(BaseModel):
    path: str
    delay_s: float = Field(gt=0, le=120)
    count: int = Field(default=1, ge=1)


def _after_commit(path: str) -> None:
    """'Lost response': the side effect is already committed; only the reply is late. Toxiproxy can't target a
    single endpoint, so this one fault lives here."""
    with _lock:
        fault = _faults.get(path)
        if not fault:
            return
        fault["remaining"] -= 1
        if fault["remaining"] <= 0:
            del _faults[path]
        delay = fault["delay_s"]
    time.sleep(delay)


def _slot(date: str) -> dict:
    return _slots.setdefault(date, {"available": DEFAULT_CAPACITY, "version": 1})


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/hospital/slots/{date}")
def get_slot(date: str) -> dict:
    with _lock:
        slot = _slot(date)
        return {"date": date, **slot}


@app.post("/hospital/bookings")
def book(body: BookingIn) -> dict:
    with _lock:
        slot = _slot(body.date)
        if slot["available"] <= 0:
            raise HTTPException(status_code=409, detail="slot_full")
        slot["available"] -= 1
        slot["version"] += 1
        booking = {"booking_id": uuid.uuid4().hex[:12], "created_at": time.time(), **body.model_dump()}
        _bookings.append(booking)
    _after_commit("/hospital/bookings")
    return booking


@app.get("/hospital/bookings")
def find_bookings(ref: str) -> list[dict]:
    with _lock:
        return [b for b in _bookings if b["ref"] == ref]


@app.post("/notify")
def notify(body: NotifyIn) -> dict:
    with _lock:
        sent = {"notification_id": uuid.uuid4().hex[:12], "sent_at": time.time(), **body.model_dump()}
        _notifications.append(sent)
    _after_commit("/notify")
    return sent


@app.get("/notify")
def find_notifications(ref: str) -> list[dict]:
    with _lock:
        return [n for n in _notifications if n["ref"] == ref]


@app.get("/metrics/side_effects")
def side_effects() -> dict:
    """Ground truth for the evaluation: how many side effects happened, and which refs happened more than once."""
    with _lock:
        booking_refs = Counter(b["ref"] for b in _bookings)
        notify_refs = Counter(n["ref"] for n in _notifications)
        return {
            "bookings": len(_bookings),
            "notifications": len(_notifications),
            "distinct_refs": len(set(booking_refs) | set(notify_refs)),
            "duplicated": {
                "bookings": {ref: n for ref, n in booking_refs.items() if n > 1},
                "notifications": {ref: n for ref, n in notify_refs.items() if n > 1},
            },
        }


@app.get("/metrics/trace/{trace}")
def by_trace(trace: str) -> dict:
    """Side effects caused by one evaluation episode, however many refs (step keys) the system under test used."""
    with _lock:
        bookings = [b for b in _bookings if b["trace"] == trace]
        notifications = [n for n in _notifications if n["trace"] == trace]
        return {"bookings": len(bookings), "notifications": len(notifications),
                "refs": sorted({e["ref"] for e in bookings + notifications})}


@app.post("/admin/slots/{date}")
def set_slot(date: str, body: SlotSet) -> dict:
    """Lets a scenario change the world while a step waits in the offline queue (e.g. the slot gets taken)."""
    with _lock:
        slot = _slot(date)
        slot["available"] = body.available
        slot["version"] += 1
        return {"date": date, **slot}


@app.post("/admin/faults")
def set_fault(body: FaultSet) -> dict:
    """Next `count` POSTs to `path` commit, then answer only after `delay_s` (past the caller's timeout)."""
    with _lock:
        _faults[body.path] = {"delay_s": body.delay_s, "remaining": body.count}
        return {"faults": _faults}


@app.post("/admin/faults/clear")
def clear_faults() -> dict:
    with _lock:
        _faults.clear()
        return {"ok": True}


@app.post("/admin/reset")
def reset() -> dict:
    with _lock:
        _faults.clear()
        _slots.clear()
        _bookings.clear()
        _notifications.clear()
        return {"ok": True}
