"""Client for the external systems (hospital booking, notifications). In Compose the base URL is the Toxiproxy hop."""

from __future__ import annotations

from typing import Any, Protocol

import httpx


class Unreachable(Exception):
    """Timeout, connection error or 5xx: the call may or may not have taken effect."""


class Rejected(Exception):
    """A definite 4xx answer: the call did NOT take effect (e.g. slot_full)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class External(Protocol):
    def call(self, tool: str, payload: dict[str, Any], ref: str) -> dict[str, Any]: ...
    def lookup(self, tool: str, ref: str) -> dict[str, Any] | None: ...
    def slot(self, date: str) -> dict[str, Any]: ...


class HttpExternal:
    def __init__(self, base_url: str, timeout_s: float = 5.0) -> None:
        self._http = httpx.Client(base_url=base_url, timeout=timeout_s)

    def call(self, tool: str, payload: dict[str, Any], ref: str) -> dict[str, Any]:
        if tool == "book_appointment":
            body = {k: payload.get(k, "") for k in ("patient_id", "department", "date", "note", "trace")}
            return self._send("POST", "/hospital/bookings", json={**body, "ref": ref})
        if tool == "notify_family":
            body = {k: payload.get(k, "") for k in ("to", "message", "trace")}
            return self._send("POST", "/notify", json={**body, "ref": ref})
        raise ValueError(f"not an external tool: {tool}")

    def lookup(self, tool: str, ref: str) -> dict[str, Any] | None:
        path = {"book_appointment": "/hospital/bookings", "notify_family": "/notify"}[tool]
        found = self._send("GET", path, params={"ref": ref})
        return found[0] if found else None

    def slot(self, date: str) -> dict[str, Any]:
        return self._send("GET", f"/hospital/slots/{date}")

    def _send(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, path, **kwargs)
        except httpx.TransportError as error:  # connect/read timeouts, resets
            raise Unreachable(str(error)) from error
        if response.status_code >= 500:
            raise Unreachable(f"HTTP {response.status_code}")
        if response.status_code >= 400:
            raise Rejected(str(response.json().get("detail", response.status_code)))
        return response.json()
