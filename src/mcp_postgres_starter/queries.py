"""Every SQL statement the tools run. Reads run in READ ONLY transactions with a statement timeout, so a
tool can never change data or hold the database for long, even if a bug slips in.

Money is integer cents in the database and plain dollars (2 decimals) in tool results, because that is what
the model reads to people.
"""

from datetime import date
from typing import Any

from psycopg import AsyncConnection
from psycopg.rows import dict_row

ORDER_STATUSES = ("pending", "paid", "shipped", "cancelled", "refunded")
#: Allowed status changes for `update_order_status`; anything else is refused.
TRANSITIONS = {
    "pending": {"paid", "cancelled"},
    "paid": {"shipped", "refunded"},
    "shipped": {"refunded"},
}
STATEMENT_TIMEOUT_MS = 5000


async def _read(conn: AsyncConnection, sql: str, params: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    async with conn.transaction():
        await conn.execute("SET TRANSACTION READ ONLY")
        await conn.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(sql, params)
            return await cur.fetchmany(limit)


def _dollars(cents: int | None) -> float | None:
    return None if cents is None else round(cents / 100, 2)


async def search_products(conn: AsyncConnection, query: str, limit: int) -> list[dict[str, Any]]:
    rows = await _read(
        conn,
        """SELECT sku, name, category, price_cents, stock FROM products
           WHERE name ILIKE %(q)s OR sku ILIKE %(q)s OR category ILIKE %(q)s
           ORDER BY name""",
        {"q": f"%{query}%"},
        limit,
    )
    return [{**row, "price": _dollars(row.pop("price_cents"))} for row in rows]


async def low_stock(conn: AsyncConnection, threshold: int, limit: int) -> list[dict[str, Any]]:
    return await _read(
        conn,
        "SELECT sku, name, category, stock FROM products WHERE stock <= %(t)s ORDER BY stock, name",
        {"t": threshold},
        limit,
    )


SALES_GROUPS = {
    "day": "to_char(o.created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')",
    "product": "p.name",
    "category": "p.category",
}


async def sales_summary(
    conn: AsyncConnection, date_from: date, date_to: date, group_by: str, limit: int
) -> list[dict[str, Any]]:
    """Revenue of paid/shipped orders created in [date_from, date_to], grouped by day, product or category."""
    key = SALES_GROUPS[group_by]  # caller validates group_by; the column text never comes from the user
    rows = await _read(
        conn,
        f"""SELECT {key} AS "group", count(DISTINCT o.id) AS orders, sum(i.quantity) AS units,
                   sum(i.quantity * i.unit_price_cents) AS revenue_cents
            FROM orders o JOIN order_items i ON i.order_id = o.id JOIN products p ON p.id = i.product_id
            WHERE o.status IN ('paid', 'shipped')
              AND o.created_at >= %(f)s AND o.created_at < %(t)s::date + 1
            GROUP BY 1 ORDER BY {"1" if group_by == "day" else "revenue_cents DESC"}""",
        {"f": date_from, "t": date_to},
        limit,
    )
    return [{**row, "revenue": _dollars(row.pop("revenue_cents"))} for row in rows]


async def find_orders(
    conn: AsyncConnection,
    customer: str | None,
    status: str | None,
    date_from: date | None,
    date_to: date | None,
    limit: int,
) -> list[dict[str, Any]]:
    rows = await _read(
        conn,
        """SELECT o.id, c.name AS customer, c.email, o.status, o.created_at, o.due_date, o.paid_at,
                  sum(i.quantity * i.unit_price_cents) AS total_cents
           FROM orders o JOIN customers c ON c.id = o.customer_id JOIN order_items i ON i.order_id = o.id
           WHERE (%(cust)s::text IS NULL OR c.name ILIKE %(cust_like)s OR c.email ILIKE %(cust_like)s)
             AND (%(status)s::text IS NULL OR o.status = %(status)s)
             AND (%(f)s::date IS NULL OR o.created_at >= %(f)s)
             AND (%(t)s::date IS NULL OR o.created_at < %(t)s::date + 1)
           GROUP BY o.id, c.name, c.email ORDER BY o.created_at DESC""",
        {"cust": customer, "cust_like": f"%{customer}%", "status": status, "f": date_from, "t": date_to},
        limit,
    )
    return [{**row, "total": _dollars(row.pop("total_cents"))} for row in rows]


async def overdue_orders(conn: AsyncConnection, as_of: date, limit: int) -> list[dict[str, Any]]:
    """Unpaid (pending) orders past their due date, oldest debt first."""
    rows = await _read(
        conn,
        """SELECT o.id, c.name AS customer, c.email, o.due_date, %(d)s::date - o.due_date AS days_overdue,
                  sum(i.quantity * i.unit_price_cents) AS total_cents
           FROM orders o JOIN customers c ON c.id = o.customer_id JOIN order_items i ON i.order_id = o.id
           WHERE o.status = 'pending' AND o.due_date < %(d)s
           GROUP BY o.id, c.name, c.email ORDER BY o.due_date""",
        {"d": as_of},
        limit,
    )
    return [{**row, "total": _dollars(row.pop("total_cents"))} for row in rows]


class TransitionError(ValueError):
    pass


async def update_order_status(conn: AsyncConnection, order_id: int, new_status: str) -> dict[str, Any]:
    """Change one order's status if the transition is allowed. Row lock prevents two clients racing."""
    async with conn.transaction():
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT id, status FROM orders WHERE id = %(id)s FOR UPDATE", {"id": order_id})
            row = await cur.fetchone()
            if row is None:
                raise TransitionError(f"Order {order_id} does not exist.")
            if new_status not in TRANSITIONS.get(row["status"], set()):
                raise TransitionError(f"Order {order_id} is '{row['status']}'; it cannot become '{new_status}'.")
            await cur.execute(
                """UPDATE orders SET status = %(s)s,
                          paid_at = CASE WHEN %(s)s = 'paid' THEN now() ELSE paid_at END
                   WHERE id = %(id)s""",
                {"s": new_status, "id": order_id},
            )
    return {"id": order_id, "old_status": row["status"], "new_status": new_status}


async def audit(
    conn: AsyncConnection,
    *,
    client_id: str,
    tool: str,
    arguments: str,
    ok: bool,
    rows: int | None,
    duration_ms: int,
    error: str | None,
) -> None:
    await conn.execute(
        """INSERT INTO audit_log (client_id, tool, arguments, ok, rows, duration_ms, error)
           VALUES (%s, %s, %s::jsonb, %s, %s, %s, %s)""",
        (client_id, tool, arguments, ok, rows, duration_ms, error),
    )
    await conn.commit()
