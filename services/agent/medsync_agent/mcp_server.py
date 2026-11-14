"""The same exactly-once tools, exposed over MCP so any MCP client (Claude, Cursor, an LLM planner) can call them.

Every side-effecting tool takes a step_key. Calling it twice with the same key returns the first result instead of
booking twice — the guarantee comes from the tool ledger, not from the caller behaving well.

    uv run python -m medsync_agent.mcp_server            # stdio
"""

from __future__ import annotations

import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from .executor import execute
from .external import HttpExternal
from .tool_ledger import InMemoryToolLedger

server = MCPServer("medsync-tools", instructions=(
    "Medication-management tools. Side-effecting tools require a step_key: reuse the same key when retrying the "
    "same logical step, and generate a new one only for a genuinely new step."))
_external = HttpExternal(os.environ.get("MEDSYNC_EXTERNAL_URL", "http://127.0.0.1:9000"))
# TODO(phase 1 week 2): share PostgresToolLedger with the API process instead of a per-process in-memory ledger.
_ledger = InMemoryToolLedger()


def _run(step_key: str, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
    result = execute(step_key, tool, payload, _ledger, _external)
    return {"status": result.status, "result": result.result, "reason": result.reason}


@server.tool()
def book_appointment(step_key: str, patient_id: str, department: str, date: str, note: str = "") -> dict[str, Any]:
    """Book a hospital follow-up. date is YYYY-MM-DD. Irreversible: retries must reuse the same step_key."""
    return _run(step_key, "book_appointment",
                {"patient_id": patient_id, "department": department, "date": date, "note": note})


@server.tool()
def notify_family(step_key: str, to: str, message: str) -> dict[str, Any]:
    """Send a message to a family contact. Irreversible: retries must reuse the same step_key."""
    return _run(step_key, "notify_family", {"to": to, "message": message})


@server.tool()
def check_slot(date: str) -> dict[str, Any]:
    """Read-only: remaining appointment slots for a date (YYYY-MM-DD)."""
    return _external.slot(date)


if __name__ == "__main__":
    server.run("stdio")
