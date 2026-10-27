from datetime import date

import psycopg
import pytest

from mcp_postgres_starter import queries


async def test_sales_summary_matches_a_direct_sum(conn):
    rows = await queries.sales_summary(conn, date(2026, 8, 1), date(2026, 10, 27), "category", 100)
    cur = await conn.execute(
        """SELECT sum(i.quantity * i.unit_price_cents) FROM orders o JOIN order_items i ON i.order_id = o.id
           WHERE o.status IN ('paid','shipped') AND o.created_at >= '2026-08-01' AND o.created_at < '2026-10-28'"""
    )
    expected_cents = (await cur.fetchone())[0]
    assert round(sum(row["revenue"] for row in rows) * 100) == expected_cents
    assert rows == sorted(rows, key=lambda row: row["revenue"], reverse=True)


async def test_limit_caps_rows(conn):
    assert len(await queries.find_orders(conn, None, None, None, None, 7)) == 7


async def test_overdue_only_lists_unpaid_orders_past_due(conn):
    rows = await queries.overdue_orders(conn, date(2026, 10, 27), 500)
    assert rows and all(row["days_overdue"] > 0 for row in rows)
    ids = [row["id"] for row in rows]
    cur = await conn.execute("SELECT DISTINCT status FROM orders WHERE id = ANY(%s)", (ids,))
    assert [r[0] for r in await cur.fetchall()] == ["pending"]


async def test_reads_cannot_write(conn):
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        await queries._read(conn, "UPDATE products SET stock = 0 RETURNING id", {}, 1)


async def test_status_transitions(conn):
    cur = await conn.execute("SELECT id FROM orders WHERE status = 'pending' ORDER BY id LIMIT 1")
    order_id = (await cur.fetchone())[0]
    assert (await queries.update_order_status(conn, order_id, "paid"))["new_status"] == "paid"
    with pytest.raises(queries.TransitionError):
        await queries.update_order_status(conn, order_id, "pending")
    with pytest.raises(queries.TransitionError):
        await queries.update_order_status(conn, 10**9, "paid")
