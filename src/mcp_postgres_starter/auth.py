"""Bearer tokens with scopes.

Tokens are random strings handed to each client (a person, a team, a Claude workspace). The server keeps only
their SHA-256 hash plus the client id and scopes, so a leaked `tokens.json` does not leak working tokens.

Scopes:
- `read`  — every read tool.
- `write` — tools that change data (also needs `read`).

This is the smallest auth that is safe for a private deployment. For many users, swap `StaticTokenVerifier`
for a verifier that checks JWTs from your identity provider (OAuth 2.1 + PKCE); the tools do not change,
because they only look at `AccessToken.scopes`.
"""

import hashlib
import json
import secrets
import sys
from pathlib import Path

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver.exceptions import ToolError

READ = "read"
WRITE = "write"


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class StaticTokenVerifier:
    """`TokenVerifier` backed by a JSON file of hashed tokens (see module docstring)."""

    def __init__(self, grants: dict[str, dict]) -> None:
        self._grants = grants

    @classmethod
    def from_file(cls, path: Path) -> "StaticTokenVerifier":
        return cls(json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})

    async def verify_token(self, token: str) -> AccessToken | None:
        grant = self._grants.get(hash_token(token))
        if grant is None:
            return None
        return AccessToken(token=token, client_id=grant["client_id"], scopes=list(grant["scopes"]))


def current_client() -> tuple[str, list[str]]:
    """Client id and scopes of the request being served; anonymous callers never reach tools over HTTP."""
    token = get_access_token()
    return (token.client_id, token.scopes) if token else ("local", [READ, WRITE])


def require(scope: str, scopes: list[str]) -> None:
    if scope not in scopes:
        raise ToolError(f"This token is missing the '{scope}' scope.")


def main() -> None:
    """`uv run mcp-postgres-starter-token <client_id> [read|read,write] [tokens.json]` — print a new token once
    and store only its hash."""
    if len(sys.argv) < 2:
        raise SystemExit("usage: mcp-postgres-starter-token <client_id> [scopes] [tokens_file]")
    client_id = sys.argv[1]
    scopes = (sys.argv[2] if len(sys.argv) > 2 else READ).split(",")
    path = Path(sys.argv[3] if len(sys.argv) > 3 else "tokens.json")
    grants = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    token = secrets.token_urlsafe(32)
    grants[hash_token(token)] = {"client_id": client_id, "scopes": scopes}
    path.write_text(json.dumps(grants, indent=2), encoding="utf-8")
    path.chmod(0o600)
    print(token)
