from __future__ import annotations

from typing import Any

from medsync_agent.external import Rejected, Unreachable


class FakeExternal:
    """In-process stand-in for the mocks service, with scripted faults.

    fault = "after_commit"  → the side effect happens, then the response is lost (the classic ambiguous timeout)
    fault = "before_commit" → the request never arrives
    fault = "down"          → every call (including lookups and slot reads) fails until cleared
    """

    def __init__(self) -> None:
        self.effects: list[dict[str, Any]] = []
        self.slots: dict[str, dict[str, int]] = {}
        self.fault: str | None = None
        self.calls = 0
        self.slot_reads = 0

    def _check_down(self) -> None:
        if self.fault == "down":
            raise Unreachable("connection refused")

    def slot(self, date: str) -> dict[str, Any]:
        self._check_down()
        self.slot_reads += 1
        return dict(self.slots.setdefault(date, {"available": 5, "version": 1}), date=date)

    def call(self, tool: str, payload: dict[str, Any], ref: str) -> dict[str, Any]:
        self._check_down()
        self.calls += 1
        if self.fault == "before_commit":
            self.fault = None
            raise Unreachable("connect timeout")
        if tool == "book_appointment":
            slot = self.slots.setdefault(payload["date"], {"available": 5, "version": 1})
            if slot["available"] <= 0:
                raise Rejected("slot_full")
            slot["available"] -= 1
            slot["version"] += 1
        effect = {"id": len(self.effects) + 1, "tool": tool, "ref": ref, **payload}
        self.effects.append(effect)
        if self.fault == "after_commit":
            self.fault = None
            raise Unreachable("read timeout")
        return effect

    def lookup(self, tool: str, ref: str) -> dict[str, Any] | None:
        self._check_down()
        return next((e for e in self.effects if e["ref"] == ref and e["tool"] == tool), None)

    def count(self, ref: str) -> int:
        return sum(1 for e in self.effects if e["ref"] == ref)
