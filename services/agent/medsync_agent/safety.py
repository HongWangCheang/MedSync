"""Safety review agent: the check a medication record goes through before the step is settled.

When a record_medication step arrives (often in a batch, after the device was offline), the label RAG service compares
the new medication with the user's other recent records (`POST /v1/safety/review`). The service reads that list
itself with the gateway's delegated, read-only token, and grounds every alert in label text. No model is involved.

The step cannot be blocked: the user already took the medication. The review is attached to the step's result so the
device shows it next to the record, with the label excerpt behind each alert.

    SafetyUnavailable   RAG (or the gateway behind it) unreachable or 5xx: the step parks and resumes on re-dispatch,
                        so the review is never skipped silently
    a 4xx answer        the request itself is wrong; retrying will not help, so the step settles with the reason
"""

from __future__ import annotations

from typing import Any, Protocol

import httpx

DELEGATED_TOOLS = {"ask_pharmacist", "record_medication"}  # the only steps that may read the medication list


class SafetyUnavailable(Exception):
    pass


class SafetyReviewer(Protocol):
    def review(self, medication: str, taken_at: int | None, token: str) -> dict[str, Any]: ...


class RagSafetyReviewer:
    def __init__(self, base_url: str, timeout_s: float = 15.0, transport: httpx.BaseTransport | None = None) -> None:
        self._http = httpx.Client(base_url=base_url, transport=transport,
                                  timeout=httpx.Timeout(timeout_s, connect=3.0))

    def review(self, medication: str, taken_at: int | None, token: str) -> dict[str, Any]:
        body = {"medication": medication[:80], **({"taken_at": taken_at} if taken_at is not None else {})}
        try:
            response = self._http.post("/v1/safety/review", json=body, headers={"Authorization": f"Bearer {token}"})
        except httpx.TransportError as error:
            raise SafetyUnavailable(str(error) or type(error).__name__) from error
        if response.status_code >= 500:
            raise SafetyUnavailable(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            return {"status": "skipped", "reason": f"http_{response.status_code}"}
        return response.json()
