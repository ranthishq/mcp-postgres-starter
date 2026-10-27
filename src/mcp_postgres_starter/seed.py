"""Create the demo schema and fill it with FAKE data.

WARNING: every customer, product and order generated here is fictional (names from fixed word lists, emails on
example.com). Nothing comes from a real business. Re-running wipes and recreates the demo tables.

Deterministic (fixed random seed), so the numbers in the README are reproducible.
"""

import asyncio
import random
from datetime import UTC, datetime, timedelta
from importlib.resources import files

from psycopg import AsyncConnection

from mcp_postgres_starter.config import load

FIRST = ["Ava", "Ben", "Chloe", "Diego", "Emma", "Farid", "Grace", "Hana", "Ivan", "Julia", "Kenji", "Lena",
         "Marco", "Nora", "Omar", "Priya", "Quinn", "Rosa", "Sam", "Tara"]
LAST = ["Adler", "Brooks", "Costa", "Dubois", "Evans", "Fischer", "Garcia", "Hughes", "Ito", "Jensen"]
COUNTRIES = ["US", "GB", "DE", "FR", "CA", "AU", "NL", "SE", "JP", "SG"]
CATALOG = {
    "Coffee": ["Ethiopia Sidamo beans", "Colombia Huila beans", "Espresso blend", "Decaf blend", "Cold brew pack"],
    "Brewing": ["Pour-over dripper", "Paper filters (100)", "Gooseneck kettle", "Hand grinder", "French press",
                "Scale with timer", "AeroPress kit"],
    "Tea": ["Sencha green tea", "Earl Grey", "Chamomile", "Oolong", "Matcha tin"],
    "Merch": ["Ceramic mug", "Travel tumbler", "Tote bag", "Gift card $25", "Gift card $50"],
}
DAYS = 90
ORDERS = 600
SEED = 20261027


async def seed(conn: AsyncConnection, *, now: datetime | None = None) -> dict[str, int]:
    rng = random.Random(SEED)
    now = now or datetime(2026, 10, 27, 12, tzinfo=UTC)
    await conn.execute("DROP TABLE IF EXISTS audit_log, order_items, orders, products, customers CASCADE")
    await conn.execute(files("mcp_postgres_starter").joinpath("schema.sql").read_text(encoding="utf-8"))

    customers = [
        (f"{first} {last}", f"{first}.{last}.{i}@example.com".lower(), rng.choice(COUNTRIES))
        for i, (first, last) in enumerate((rng.choice(FIRST), rng.choice(LAST)) for _ in range(60))
    ]
    async with conn.cursor() as cur:
        await cur.executemany("INSERT INTO customers (name, email, country) VALUES (%s, %s, %s)", customers)
        products = []
        for category, names in CATALOG.items():
            for n, name in enumerate(names):
                products.append((f"{category[:3].upper()}-{n + 1:03d}", name, category,
                                 rng.randint(4, 120) * 100 - 1, rng.choice([0, 2, 3, 8, 15, 40, 120])))
        await cur.executemany(
            "INSERT INTO products (sku, name, category, price_cents, stock) VALUES (%s, %s, %s, %s, %s)", products)

        for _ in range(ORDERS):
            created = now - timedelta(days=rng.uniform(0, DAYS))
            due = (created + timedelta(days=14)).date()
            status = rng.choices(["paid", "shipped", "pending", "cancelled", "refunded"], [30, 45, 15, 6, 4])[0]
            paid_at = created + timedelta(days=rng.uniform(0, 10)) if status in ("paid", "shipped", "refunded") else None
            await cur.execute(
                """INSERT INTO orders (customer_id, status, created_at, due_date, paid_at)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (rng.randint(1, len(customers)), status, created, due, paid_at),
            )
            order_id = (await cur.fetchone())[0]
            for product_id in rng.sample(range(1, len(products) + 1), rng.randint(1, 4)):
                price = products[product_id - 1][3]
                await cur.execute(
                    "INSERT INTO order_items (order_id, product_id, quantity, unit_price_cents) VALUES (%s, %s, %s, %s)",
                    (order_id, product_id, rng.randint(1, 3), price),
                )
    await conn.commit()
    return {"customers": len(customers), "products": len(products), "orders": ORDERS}


def main() -> None:
    async def run() -> None:
        async with await AsyncConnection.connect(load().database_url) as conn:
            print(await seed(conn))

    asyncio.run(run())
