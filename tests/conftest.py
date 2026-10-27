"""Tests run against a real PostgreSQL database (TEST_DATABASE_URL), re-seeded with the fake demo data."""

import os

import pytest
from psycopg import AsyncConnection

from mcp_postgres_starter.seed import seed

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres@localhost:5432/mcp_demo_test")


@pytest.fixture
async def conn():
    async with await AsyncConnection.connect(TEST_DATABASE_URL) as connection:
        await seed(connection)
        yield connection
