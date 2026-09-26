"""Read-only SQL tool.

Defense in depth: a statement allowlist (single SELECT/WITH only), a read-only
transaction on the connection, a statement timeout, and a row cap.
"""
import os
import re
from typing import Any, Optional

import asyncpg

from tools.registry import BaseTool, ToolResult, ToolSchema

MAX_ROWS = 100
STATEMENT_TIMEOUT_MS = 2000

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|copy|"
    r"vacuum|comment|call|do|merge|set|reset|begin|commit|rollback)\b",
    re.IGNORECASE,
)


class ReadOnlySQLTool(BaseTool):
    """Answers questions against the app database without write access."""

    def __init__(
        self,
        dsn: Optional[str] = None,
        allowed_tables: Optional[list[str]] = None,
    ) -> None:
        schema = ToolSchema(
            name="db_query",
            description="Run a read-only SQL query and return up to 100 rows.",
            parameters={
                "query": {"type": "string", "description": "A single SELECT query"}
            },
            allowed_specialists=["data_analyst", "researcher"],
        )
        super().__init__(schema)
        self.dsn = (
            dsn
            or os.getenv("READONLY_DATABASE_URL")
            or os.getenv("DATABASE_URL")
            or "postgresql://orchestra:orchestra@localhost:5432/orchestra"
        )
        self.allowed_tables = set(allowed_tables or [])

    @staticmethod
    def rejection_reason(query: str) -> Optional[str]:
        statement = query.strip().rstrip(";").strip()
        if not statement:
            return "empty query"
        if ";" in statement:
            return "only a single statement is allowed"
        if not re.match(r"^(select|with)\b", statement, re.IGNORECASE):
            return "only SELECT / WITH queries are allowed"
        match = _FORBIDDEN.search(statement)
        if match:
            return f"{match.group(0).upper()} is not allowed in a read-only query"
        return None

    async def run(self, query: str = "", **kwargs: Any) -> ToolResult:
        reason = self.rejection_reason(query)
        if reason:
            return ToolResult(content="", status="error", error=reason)

        try:
            conn = await asyncpg.connect(self.dsn)
        except Exception as exc:
            return ToolResult(content="", status="error", error=f"database unavailable: {exc}")

        try:
            await conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
            await conn.execute("SET default_transaction_read_only = on")
            rows = await conn.fetch(query)
        except Exception as exc:
            return ToolResult(content="", status="error", error=str(exc))
        finally:
            await conn.close()

        if not rows:
            return ToolResult(content="No rows.")

        columns = list(rows[0].keys())
        lines = [" | ".join(columns)]
        for row in rows[:MAX_ROWS]:
            lines.append(" | ".join(str(row[column]) for column in columns))
        if len(rows) > MAX_ROWS:
            lines.append(f"... ({len(rows) - MAX_ROWS} more rows)")
        return ToolResult(content="\n".join(lines))
