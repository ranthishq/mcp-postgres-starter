# Demo session: Claude asking questions over this MCP server

Recorded 2026-10-27 with Claude Code CLI (`claude -p`, model Sonnet) connected to a local server
(`http://127.0.0.1:8000/mcp`, read-only bearer token) over the **fake** demo data from `seed.py`.

**Prompt**

> It is 2026-10-27. Which three customers owe us the most in overdue orders right now, how many days overdue is each, and which products are almost out of stock (3 or fewer left)? Then give me revenue by category for the last 90 days. Use the store tools only.

**Run**

| | |
|---|---|
| Turns (model ↔ tools) | 5 |
| Wall time | 19.1 s |
| Output tokens | 1,961 |
| Input tokens (cache read / cache write / fresh) | 91,715 / 17,739 / 8 |
| Cost at API prices (as reported by Claude Code) | $0.10 |

Every number in the answer was checked against direct SQL on the same database: the top three debtors and their
totals, days overdue, the 13 products with 3 or fewer left, and revenue/orders/units per category all match.

**Claude's answer (verbatim)**

**Top three customers by overdue balance** (as of 2026-10-27, summed across all their unpaid past-due orders):

| # | Customer | Overdue orders | Total owed | Days overdue |
|---|---|---|---|---|
| 1 | Hana Garcia (hana.garcia.21@example.com) | 4 | $1,626.78 | 70 (oldest), 63, 31, 4 |
| 2 | Emma Adler (emma.adler.0@example.com) | 4 | $1,360.74 | 72 (oldest), 20, 20, 3 |
| 3 | Tara Garcia (tara.garcia.18@example.com) | 4 | $1,010.81 | 74 (oldest), 60, 43, 31 |

Sam Costa is close behind at $969.83. I grouped by email address, because some names repeat across different accounts. For example, there are two different Hana Hughes and two different Diego Garcias. The totals are my own sums of the order amounts the tool returned.

**Almost out of stock (3 or fewer)**
- **Out of stock (0):** AeroPress kit (BRE-007), Matcha tin (TEA-005), Sencha green tea (TEA-001)
- **2 left:** Cold brew pack (COF-005), Colombia Huila beans (COF-002), Espresso blend (COF-003), Gift card $25 (MER-004), Gift card $50 (MER-005), Paper filters (BRE-002), Pour-over dripper (BRE-001), Tote bag (MER-003)
- **3 left:** Ceramic mug (MER-001), Earl Grey (TEA-002)

**Revenue by category, last 90 days** (2026-07-29 to 2026-10-27, paid or shipped orders)

| Category | Revenue | Orders | Units |
|---|---|---|---|
| Coffee | $37,973.83 | 221 | 517 |
| Merch | $33,782.11 | 209 | 489 |
| Brewing | $25,686.14 | 270 | 686 |
| Tea | $17,112.15 | 194 | 485 |
| **Total** | **$114,554.23** | | |

Coffee brings in the most revenue. Brewing has the most orders and units, but each sale is worth less. Three coffee products are nearly out of stock, so a restock there would protect your top category.
