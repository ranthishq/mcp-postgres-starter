"""The MCP server: tool definitions, auth wiring, audit logging.

Request path: Claude -> HTTP (Streamable HTTP, bearer token) -> tool below -> scope check -> queries.py -> Postgres,
and every call (allowed or refused) is written to `audit_log`.
"""

import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import date
from typing import Annotated, Any

from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from psycopg import AsyncConnection
from psycopg_pool import AsyncConnectionPool
from pydantic import Field

from mcp_postgres_starter import queries
from mcp_postgres_starter.auth import READ, WRITE, StaticTokenVerifier, current_client, require
from mcp_postgres_starter.config import Settings

INSTRUCTIONS = (
    "Tools over a store database (customers, products, orders). Amounts are US dollars. "
    "Dates are YYYY-MM-DD in UTC. Results are capped; narrow the filters if a list looks cut off."
)
READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)


def build_server(settings: Settings, verifier: StaticTokenVerifier | None = None) -> MCPServer:
    pool = AsyncConnectionPool(settings.database_url, min_size=1, max_size=5, open=False)

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        await pool.open()
        try:
            yield
        finally:
            await pool.close()

    auth = None
    if verifier is not None:
        auth = AuthSettings(
            issuer_url=settings.public_url,
            resource_server_url=settings.public_url,
            required_scopes=[READ],
            validate_token_resource=False,  # static tokens are issued for this server only
        )
    server = MCPServer(
        name="mcp-postgres-starter",
        instructions=INSTRUCTIONS,
        token_verifier=verifier,
        auth=auth,
        lifespan=lifespan,
    )

    async def run(
        tool: str,
        scope: str,
        arguments: dict[str, Any],
        work: Callable[[AsyncConnection], Awaitable[Any]],
    ) -> Any:
        """Scope check, run, audit — the same for every tool, so no tool can forget one of them."""
        client_id, scopes = current_client()
        started = time.perf_counter()
        result: Any = None
        error: str | None = None
        try:
            require(scope, scopes)
            async with pool.connection() as conn:
                result = await work(conn)
            return result
        except queries.TransitionError as exc:
            error = str(exc)
            raise ToolError(error) from exc
        except ToolError as exc:
            error = str(exc)
            raise
        finally:
            rows = len(result) if isinstance(result, list) else (1 if result is not None else None)
            async with pool.connection() as conn:
                await queries.audit(
                    conn,
                    client_id=client_id,
                    tool=tool,
                    arguments=json.dumps(arguments, default=str),
                    ok=error is None,
                    rows=rows,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                    error=error,
                )

    def cap(limit: int) -> int:
        return max(1, min(limit, settings.max_rows))

    Limit = Annotated[int, Field(description="Maximum rows to return.", ge=1)]

    @server.tool(annotations=READ_ONLY)
    async def search_products(
        query: Annotated[str, Field(description="Text to match in product name, SKU or category.")],
        limit: Limit = 20,
    ) -> list[dict[str, Any]]:
        """Find products by name, SKU or category, with price and stock."""
        return await run("search_products", READ, {"query": query, "limit": limit},
                         lambda c: queries.search_products(c, query, cap(limit)))

    @server.tool(annotations=READ_ONLY)
    async def low_stock(
        threshold: Annotated[int, Field(description="List products with stock at or below this.", ge=0)] = 5,
        limit: Limit = 50,
    ) -> list[dict[str, Any]]:
        """Products that are running out, lowest stock first."""
        return await run("low_stock", READ, {"threshold": threshold, "limit": limit},
                         lambda c: queries.low_stock(c, threshold, cap(limit)))

    @server.tool(annotations=READ_ONLY)
    async def sales_summary(
        date_from: date,
        date_to: date,
        group_by: Annotated[str, Field(description="One of: day, product, category.")] = "day",
        limit: Limit = 100,
    ) -> list[dict[str, Any]]:
        """Revenue, order count and units of paid or shipped orders between two dates (inclusive)."""
        if group_by not in queries.SALES_GROUPS:
            raise ToolError(f"group_by must be one of: {', '.join(queries.SALES_GROUPS)}")
        args = {"date_from": date_from, "date_to": date_to, "group_by": group_by, "limit": limit}
        return await run("sales_summary", READ, args,
                         lambda c: queries.sales_summary(c, date_from, date_to, group_by, cap(limit)))

    @server.tool(annotations=READ_ONLY)
    async def find_orders(
        customer: Annotated[str | None, Field(description="Part of the customer's name or email.")] = None,
        status: Annotated[str | None, Field(description=f"One of: {', '.join(queries.ORDER_STATUSES)}.")] = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: Limit = 20,
    ) -> list[dict[str, Any]]:
        """Orders matching the filters, newest first, with customer and total."""
        if status is not None and status not in queries.ORDER_STATUSES:
            raise ToolError(f"status must be one of: {', '.join(queries.ORDER_STATUSES)}")
        args = {"customer": customer, "status": status, "date_from": date_from, "date_to": date_to, "limit": limit}
        return await run("find_orders", READ, args,
                         lambda c: queries.find_orders(c, customer, status, date_from, date_to, cap(limit)))

    @server.tool(annotations=READ_ONLY)
    async def overdue_orders(
        as_of: Annotated[date | None, Field(description="Day to measure from; default today (UTC).")] = None,
        limit: Limit = 50,
    ) -> list[dict[str, Any]]:
        """Unpaid orders past their due date, with days overdue and amount owed."""
        day = as_of or date.today()
        return await run("overdue_orders", READ, {"as_of": day, "limit": limit},
                         lambda c: queries.overdue_orders(c, day, cap(limit)))

    @server.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True, openWorldHint=False))
    async def update_order_status(
        order_id: int,
        new_status: Annotated[str, Field(description="pending->paid/cancelled, paid->shipped/refunded, "
                                                     "shipped->refunded.")],
    ) -> dict[str, Any]:
        """Change an order's status. Needs a token with the 'write' scope; only the listed transitions work."""
        return await run("update_order_status", WRITE, {"order_id": order_id, "new_status": new_status},
                         lambda c: queries.update_order_status(c, order_id, new_status))

    return server
