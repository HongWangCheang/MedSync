"""The exactly-once tools as an MCP server. The agent's executor calls them through an MCP client
(`tools.McpTools`); any other MCP client (Claude, Cursor, an LLM planner) can call the same tools.

Every side-effecting tool takes a step_key. Calling it twice with the same key returns the first result instead of
booking twice: the guarantee comes from the tool ledger this server owns, not from the caller behaving well.
With MEDSYNC_PG_DSN set the ledger is the Postgres `tool_ledger` table, shared by every replica of this server.

    uv run python -m medsync_agent.mcp_server                       # stdio, in-memory ledger
    uv run python -m medsync_agent.mcp_server --http --port 8200    # streamable HTTP at /mcp (Compose service "tools")
"""

from __future__ import annotations

import argparse
import os
from typing import Any

from mcp.server.mcpserver import MCPServer

from .executor import execute
from .external import External, HttpExternal
from .tool_ledger import InMemoryToolLedger, PostgresToolLedger, ToolLedger

INSTRUCTIONS = (
    "Medication-management tools. Side-effecting tools require a step_key: reuse the same key when retrying the "
    "same logical step, and generate a new one only for a genuinely new step. A result with status PENDING means "
    "the outcome is not known yet: retry later with the same step_key, never with a new one.")


def build_server(ledger: ToolLedger, external: External) -> MCPServer:
    server = MCPServer("medsync-tools", instructions=INSTRUCTIONS)

    def run(step_key: str, tool: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = execute(step_key, tool, {k: v for k, v in payload.items() if v != ""}, ledger, external)
        return {"status": result.status, "result": result.result, "reason": result.reason}

    @server.tool()
    def book_appointment(step_key: str, patient_id: str, department: str, date: str, note: str = "",
                         trace: str = "") -> dict[str, Any]:
        """Book a hospital follow-up. date is YYYY-MM-DD. Irreversible: retries must reuse the same step_key.
        status is DONE (booked, or the earlier booking for this step_key), REJECTED (e.g. slot_full) or PENDING."""
        return run(step_key, "book_appointment",
                   {"patient_id": patient_id, "department": department, "date": date, "note": note, "trace": trace})

    @server.tool()
    def notify_family(step_key: str, to: str, message: str, trace: str = "") -> dict[str, Any]:
        """Send a message to a family contact. Irreversible: retries must reuse the same step_key."""
        return run(step_key, "notify_family", {"to": to, "message": message, "trace": trace})

    @server.tool()
    def check_slot(date: str) -> dict[str, Any]:
        """Read-only: remaining appointment slots for a date (YYYY-MM-DD)."""
        return external.slot(date)

    return server


def _ledger_from_env() -> ToolLedger:
    dsn = os.environ.get("MEDSYNC_PG_DSN")
    if not dsn:
        return InMemoryToolLedger()
    from psycopg.rows import dict_row
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(dsn, max_size=10, open=True,
                          kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row})
    return PostgresToolLedger(pool)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--http", action="store_true", help="streamable HTTP instead of stdio")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8200)
    args = parser.parse_args()
    external = HttpExternal(os.environ.get("MEDSYNC_EXTERNAL_URL", "http://127.0.0.1:9000"),
                            float(os.environ.get("MEDSYNC_EXTERNAL_TIMEOUT_S", "5")))
    server = build_server(_ledger_from_env(), external)
    if args.http:
        server.run("streamable-http", host=args.host, port=args.port, stateless_http=True, json_response=True)
    else:
        server.run("stdio")


if __name__ == "__main__":
    main()
