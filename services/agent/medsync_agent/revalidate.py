"""Is a step that waited in an offline queue still the right thing to do?

Pure function over (request, current world, now) so it can be unit-tested and its thresholds tuned against the
false-block rate, not just the catch rate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .models import TOOL_VERSIONS, ActionRequest


@dataclass
class Decision:
    kind: Literal["PROCEED", "ASK_USER", "CANCEL"]
    reason: str
    options: list[dict[str, Any]] = field(default_factory=list)


def decide(request: ActionRequest, world: dict[str, Any], now_ms: int) -> Decision:
    """`world` is what the graph fetched just now, e.g. {"slot": {...}, "alternatives": [...]}."""
    planned_version = request.preconditions.get("toolVersion")
    if planned_version and planned_version != TOOL_VERSIONS.get(request.tool):
        return Decision("ASK_USER", "tool_changed", [{"decision": "confirm"}, {"decision": "cancel"}])

    if request.expires_at_ms is not None and now_ms > request.expires_at_ms:
        # e.g. "tell my daughter I feel dizzy" arriving six hours late is no longer what the user meant.
        return Decision("ASK_USER", "expired", [{"decision": "confirm"}, {"decision": "cancel"}])

    if request.tool == "book_appointment":
        slot = world.get("slot") or {}
        if slot.get("available", 0) <= 0:
            options = [{"decision": "choose", "date": alt["date"]} for alt in world.get("alternatives", [])]
            return Decision("ASK_USER", "slot_full", options + [{"decision": "cancel"}])
        planned = request.preconditions.get("slotVersion")
        if planned is not None and planned != slot.get("version"):
            return Decision("PROCEED", "precondition_changed_still_valid")

    return Decision("PROCEED", "unchanged")
