"""Settings, read once from environment variables. The only module that knows variable names."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    #: JSON file mapping sha256(token) -> {"client_id": ..., "scopes": [...]}. Raw tokens are never stored.
    tokens_file: Path
    #: Hard cap on rows any tool returns, whatever the caller asks for.
    max_rows: int
    host: str
    port: int
    #: Public base URL clients use (https in production); also the OAuth resource identifier.
    public_url: str


def load() -> Settings:
    port = int(os.environ.get("MCP_PORT", "8000"))
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    return Settings(
        database_url=os.environ.get("DATABASE_URL", "postgresql://localhost:5432/mcp_demo"),
        tokens_file=Path(os.environ.get("MCP_TOKENS_FILE", "tokens.json")),
        max_rows=int(os.environ.get("MCP_MAX_ROWS", "200")),
        host=host,
        port=port,
        public_url=os.environ.get("MCP_PUBLIC_URL", f"http://{host}:{port}"),
    )
