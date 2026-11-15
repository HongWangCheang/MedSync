"""How the executor reaches the outside world: through the MCP tool server, or in-process for tests and experiments.

The exactly-once guarantee lives with the tools, not with the caller: whichever process runs `execute` owns the
tool ledger. With MCP that is the `tools` service, so any MCP client (this agent, an LLM planner, Claude) gets the
same guarantee as long as it passes the step_key.

The link to the MCP server is one more place where a response can be lost after the work was done. It is handled
the same way as hop ③: an unanswered call is "outcome unknown" (Unreachable), the step stays parked, and the next
attempt sends the same step_key, which the server's ledger answers from its COMMITTED row.
"""

from __future__ import annotations

from typing import Any, Protocol

import anyio

from . import tracing
from .executor import ExecResult, execute
from .external import External, Unreachable
from .tool_ledger import ToolLedger

# Which payload fields each MCP tool takes; anything else in the payload is not part of the external call.
TOOL_ARGS = {
    "book_appointment": ("patient_id", "department", "date", "note", "trace"),
    "notify_family": ("to", "message", "trace"),
}


class Tools(Protocol):
    name: str

    def execute(self, step_key: str, tool: str, payload: dict[str, Any]) -> ExecResult: ...
    def slot(self, date: str) -> dict[str, Any]: ...


class LocalTools:
    """In-process: the caller owns the ledger. Unit tests, and the comparison experiment's in-agent baselines."""

    name = "local"

    def __init__(self, ledger: ToolLedger, external: External) -> None:
        self._ledger, self._external = ledger, external

    def execute(self, step_key: str, tool: str, payload: dict[str, Any]) -> ExecResult:
        return execute(step_key, tool, payload, self._ledger, self._external)

    def slot(self, date: str) -> dict[str, Any]:
        return self._external.slot(date)


class McpTools:
    """MCP client. `server` is the tools service URL (streamable HTTP) or, in tests, an MCPServer instance."""

    name = "mcp"

    def __init__(self, server: Any, timeout_s: float = 15.0) -> None:
        self._server, self._timeout_s = server, timeout_s

    def execute(self, step_key: str, tool: str, payload: dict[str, Any]) -> ExecResult:
        args = {k: str(payload[k]) for k in TOOL_ARGS[tool] if payload.get(k) not in (None, "")}
        data = self._call(tool, {"step_key": step_key, **args})
        return ExecResult(data["status"], data.get("result"), data.get("reason"))

    def slot(self, date: str) -> dict[str, Any]:
        return self._call("check_slot", {"date": date})

    def _call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with tracing.span(f"mcp:{name}", input=tracing.redact(arguments)) as span:
            try:
                data = anyio.run(self._acall, name, arguments)
            except Unreachable:
                raise
            except Exception as error:  # transport errors, timeouts, server down: the outcome is unknown
                span.update(level="WARNING", status_message=str(error))
                raise Unreachable(f"mcp {name}: {error!r}") from error
            span.update(output=tracing.redact(data))
            return data

    async def _acall(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        from mcp.client.client import Client

        with anyio.fail_after(self._timeout_s):
            async with Client(self._server) as client:
                result = await client.call_tool(name, arguments)
        if result.is_error:
            text = " ".join(getattr(c, "text", "") for c in result.content)
            # The tool itself failed (e.g. its database is down): nothing says the side effect did not happen.
            raise Unreachable(f"mcp {name} failed: {text[:200]}")
        if not isinstance(result.structured_content, dict):
            raise Unreachable(f"mcp {name}: no structured result")
        return result.structured_content
