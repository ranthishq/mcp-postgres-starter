"""End to end over real HTTP: a uvicorn server in a thread, the official MCP client, real bearer tokens."""

import asyncio
import socket
import threading
import time
from pathlib import Path

import httpx2
import pytest
import uvicorn
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

from mcp_postgres_starter.auth import StaticTokenVerifier, hash_token
from mcp_postgres_starter.config import Settings
from mcp_postgres_starter.server import build_server
from tests.conftest import TEST_DATABASE_URL

READER = "reader-token-for-tests"
WRITER = "writer-token-for-tests"


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
async def url(conn):
    port = free_port()
    settings = Settings(TEST_DATABASE_URL, Path("unused.json"), 50, "127.0.0.1", port, f"http://127.0.0.1:{port}")
    verifier = StaticTokenVerifier({
        hash_token(READER): {"client_id": "reader", "scopes": ["read"]},
        hash_token(WRITER): {"client_id": "writer", "scopes": ["read", "write"]},
    })
    app = build_server(settings, verifier).streamable_http_app(host="127.0.0.1")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


async def call(url: str, token: str | None, tool: str, arguments: dict):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with httpx2.AsyncClient(headers=headers, timeout=30) as http:
        async with streamable_http_client(url, http_client=http) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await session.call_tool(tool, arguments)


async def test_no_token_is_rejected(url):
    async with httpx2.AsyncClient(timeout=10) as http:
        response = await http.post(url, json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
                                   headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 401


async def test_reader_can_read(url):
    result = await call(url, READER, "search_products", {"query": "beans", "limit": 5})
    assert not result.is_error
    assert "Ethiopia" in str(result.structured_content or result.content)


async def test_reader_cannot_write_and_refusal_is_audited(url, conn):
    cur = await conn.execute("SELECT id FROM orders WHERE status = 'pending' ORDER BY id LIMIT 1")
    order_id = (await cur.fetchone())[0]
    refused = await call(url, READER, "update_order_status", {"order_id": order_id, "new_status": "paid"})
    assert refused.is_error and "write" in str(refused.content)
    done = await call(url, WRITER, "update_order_status", {"order_id": order_id, "new_status": "paid"})
    assert not done.is_error
    await asyncio.sleep(0.1)
    cur = await conn.execute("SELECT client_id, ok FROM audit_log WHERE tool = 'update_order_status' ORDER BY id")
    assert await cur.fetchall() == [("reader", False), ("writer", True)]
