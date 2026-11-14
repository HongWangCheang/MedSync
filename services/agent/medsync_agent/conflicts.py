"""Does a finding the planner never saw contradict the step about to run? Pure function, like revalidate.decide.

Policy (tool × finding):

    notify_family     high finding                      → pause: the family should not get the message unaware
    notify_family     moderate finding, message says    → pause: "我没事" next to a fresh label warning
                      the user is fine ("没事", "放心")
    notify_family     moderate finding, neutral message → proceed: nothing in the message is contradicted
    book_appointment  any finding                       → proceed: seeing a doctor agrees with any warning

A paused step asks the user, with the finding attached: send the message with the warning appended, send it as it
was, or cancel. Nothing is changed or sent without that answer.
"""

from __future__ import annotations

from typing import Any

from .findings import Finding
from .models import ActionRequest

REASON = "conflict_with_later_finding"
# Phrases that tell someone not to worry. Plain substrings on purpose: the message is the user's own short text.
REASSURING = ("没事", "没关系", "不用担心", "别担心", "放心", "挺好", "好多了", "没问题", "不要紧", "不碍事")
NOTE_LIMIT = 2


def reassuring(message: str) -> bool:
    return any(phrase in message for phrase in REASSURING)


def detect(request: ActionRequest, findings: list[Finding]) -> list[dict[str, Any]]:
    if request.tool != "notify_family":
        return []
    message = str(request.payload.get("message", ""))
    calming = reassuring(message)
    conflicts = []
    for f in findings:
        if f.severity == "high":
            why = "这条消息排队之后，服务器得出了高风险的用药提醒"
        elif calming:
            why = "消息里说一切还好，但随后的审核有用药提醒"
        else:
            continue
        conflicts.append({"source": f.source, "kind": f.kind, "severity": f.severity, "summary": f.summary,
                          "why": why, "step_key": f.step_key, "detail": f.detail})
    return conflicts


def options(conflicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"decision": "send_with_note"}, {"decision": "confirm"}, {"decision": "cancel"}] if conflicts else []


def with_note(message: str, conflicts: list[dict[str, Any]]) -> str:
    """The message with the findings appended; built from server state, never from what the device sends back."""
    notes = "；".join(c["summary"] for c in conflicts[:NOTE_LIMIT])
    return f"{message}\n（MedSync 用药提醒：{notes}）"
