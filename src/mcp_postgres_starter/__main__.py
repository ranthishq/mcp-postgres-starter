"""`uv run mcp-postgres-starter` — serve over Streamable HTTP at <MCP_PUBLIC_URL>/mcp.

Refuses to start without at least one token: an HTTP server with write tools must never be open to anyone.
"""

import uvicorn

from mcp_postgres_starter.auth import StaticTokenVerifier
from mcp_postgres_starter.config import load
from mcp_postgres_starter.server import build_server


def main() -> None:
    settings = load()
    verifier = StaticTokenVerifier.from_file(settings.tokens_file)
    if not settings.tokens_file.exists():
        raise SystemExit(
            f"No tokens file at {settings.tokens_file}. Create one: uv run mcp-postgres-starter-token claude-desktop read"
        )
    app = build_server(settings, verifier).streamable_http_app(host=settings.host)
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="info")


if __name__ == "__main__":
    main()
