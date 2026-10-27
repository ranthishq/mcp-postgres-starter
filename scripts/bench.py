"""Median latency of each read tool over real HTTP, measured from the client side.

    MCP_URL=http://127.0.0.1:8765/mcp MCP_TOKEN=... uv run python scripts/bench.py [runs]

Prints one JSON line per tool: median and p90 milliseconds over `runs` calls on one session (default 30).
"""

import asyncio
import json
import os
import statistics
import sys
import time

import httpx2
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

CALLS = {
    "search_products": {"query": "blend", "limit": 10},
    "low_stock": {"threshold": 3},
    "sales_summary": {"date_from": "2026-07-29", "date_to": "2026-10-27", "group_by": "category"},
    "find_orders": {"status": "pending", "limit": 20},
    "overdue_orders": {"as_of": "2026-10-27"},
}


async def main(runs: int) -> None:
    headers = {"Authorization": f"Bearer {os.environ['MCP_TOKEN']}"}
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(os.environ["MCP_URL"], http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                for tool, arguments in CALLS.items():
                    timings = []
                    for _ in range(runs):
                        started = time.perf_counter()
                        result = await session.call_tool(tool, arguments)
                        timings.append((time.perf_counter() - started) * 1000)
                        assert not result.is_error, result.content
                    timings.sort()
                    print(json.dumps({
                        "tool": tool,
                        "runs": runs,
                        "median_ms": round(statistics.median(timings), 1),
                        "p90_ms": round(timings[int(len(timings) * 0.9) - 1], 1),
                    }))


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 30))
