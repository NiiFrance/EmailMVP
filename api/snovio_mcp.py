"""Snov.io MCP integration — OAuth 2.1 (PKCE) client + minimal MCP JSON-RPC caller.

Snov.io's MCP server (https://mcp.snov.io/mcp) uses the MCP streamable-HTTP
transport protected by OAuth 2.1:

  - resource metadata:  https://mcp.snov.io/.well-known/oauth-protected-resource
  - authorize:          https://app.snov.io/mcp/authorize            (PKCE S256)
  - token:              https://app.snov.io/back/mcp/oauth/token     (public client)
  - dynamic client reg: https://app.snov.io/back/mcp/oauth/register  (RFC 7591)

The app registers itself once per host (client id cached in Table storage),
sends users through the browser consent flow, and stores their access/refresh
tokens encrypted at rest. Backend calls then speak JSON-RPC 2.0 to the MCP
endpoint with the user's bearer token.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MCP_ENDPOINT = "https://mcp.snov.io/mcp"
AUTHORIZE_ENDPOINT = "https://app.snov.io/mcp/authorize"
TOKEN_ENDPOINT = "https://app.snov.io/back/mcp/oauth/token"
REGISTER_ENDPOINT = "https://app.snov.io/back/mcp/oauth/register"
OAUTH_SCOPE = "mcp"
PROTOCOL_VERSION = "2025-03-26"
_TIMEOUT = 60


class SnovioMCPError(RuntimeError):
    """Raised when the MCP server or OAuth endpoints return an error."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# OAuth 2.1 helpers (public client + PKCE S256)
# ---------------------------------------------------------------------------

def make_pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for PKCE S256."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def register_client(client_name: str, redirect_uri: str) -> str:
    """Dynamically register a public OAuth client; returns the client_id."""
    body = json.dumps({
        "client_name": client_name,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": OAUTH_SCOPE,
    }).encode("utf-8")
    payload = _http_json(REGISTER_ENDPOINT, body, {"Content-Type": "application/json"})
    client_id = str(payload.get("client_id") or "")
    if not client_id:
        raise SnovioMCPError(f"Client registration returned no client_id: {payload}")
    return client_id


def build_authorize_url(client_id: str, redirect_uri: str, state: str, code_challenge: str) -> str:
    query = urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": OAUTH_SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "resource": MCP_ENDPOINT,
    })
    return f"{AUTHORIZE_ENDPOINT}?{query}"


def exchange_code(client_id: str, redirect_uri: str, code: str, code_verifier: str) -> dict[str, Any]:
    """Exchange an authorization code for tokens."""
    return _token_request({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "code": code,
        "code_verifier": code_verifier,
    })


def refresh_tokens(client_id: str, refresh_token: str) -> dict[str, Any]:
    """Exchange a refresh token for a new access token."""
    return _token_request({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh_token,
    })


def _token_request(fields: dict[str, str]) -> dict[str, Any]:
    body = urlencode(fields).encode("utf-8")
    payload = _http_json(TOKEN_ENDPOINT, body, {"Content-Type": "application/x-www-form-urlencoded"})
    if not payload.get("access_token"):
        raise SnovioMCPError(f"Token endpoint returned no access token: {payload}")
    return payload


def _http_json(url: str, body: bytes, headers: dict[str, str]) -> dict[str, Any]:
    request = Request(url, data=body, headers={"Accept": "application/json", **headers}, method="POST")
    try:
        with urlopen(request, timeout=_TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = ""
        try:
            detail = error.read().decode("utf-8")[:500]
        except Exception:
            pass
        raise SnovioMCPError(f"HTTP {error.code} from {url}: {detail}", status_code=error.code) from error
    except URLError as error:
        raise SnovioMCPError(f"Network error calling {url}: {error.reason}") from error


# ---------------------------------------------------------------------------
# Minimal MCP client (streamable HTTP, JSON-RPC 2.0)
# ---------------------------------------------------------------------------

class SnovioMCPSession:
    """One short-lived MCP session: initialize once, then list/call tools."""

    def __init__(self, access_token: str):
        self.access_token = access_token
        self.session_id: str | None = None
        self._request_id = 0
        self._initialized = False

    # -- public API ---------------------------------------------------------
    def list_tools(self) -> list[dict[str, Any]]:
        self._ensure_initialized()
        tools: list[dict[str, Any]] = []
        cursor = None
        for _ in range(20):  # paginate defensively
            params: dict[str, Any] = {"cursor": cursor} if cursor else {}
            result = self._rpc("tools/list", params)
            tools.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        self._ensure_initialized()
        return self._rpc("tools/call", {"name": name, "arguments": arguments or {}})

    # -- plumbing -----------------------------------------------------------
    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        self._rpc("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "cloudware-email-campaign-generator", "version": "1.0"},
        })
        self._notify("notifications/initialized")
        self._initialized = True

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _notify(self, method: str) -> None:
        body = json.dumps({"jsonrpc": "2.0", "method": method}).encode("utf-8")
        request = Request(MCP_ENDPOINT, data=body, headers=self._headers(), method="POST")
        try:
            with urlopen(request, timeout=_TIMEOUT) as response:
                response.read()
        except HTTPError as error:
            if error.code not in (200, 202, 204):
                # Notifications are best-effort; some servers 4xx them harmlessly.
                error.read()
        except URLError:
            pass

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request_id = self._next_id()
        body = json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}).encode("utf-8")
        request = Request(MCP_ENDPOINT, data=body, headers=self._headers(), method="POST")
        try:
            with urlopen(request, timeout=_TIMEOUT) as response:
                session_id = response.headers.get("Mcp-Session-Id")
                if session_id:
                    self.session_id = session_id
                raw = response.read().decode("utf-8")
                content_type = (response.headers.get("Content-Type") or "").lower()
        except HTTPError as error:
            detail = ""
            try:
                detail = error.read().decode("utf-8")[:500]
            except Exception:
                pass
            raise SnovioMCPError(f"MCP {method} failed: HTTP {error.code} {detail}", status_code=error.code) from error
        except URLError as error:
            raise SnovioMCPError(f"MCP network error: {error.reason}") from error

        message = _parse_rpc_body(raw, content_type, request_id)
        if "error" in message:
            err = message["error"] or {}
            raise SnovioMCPError(f"MCP {method} error {err.get('code')}: {err.get('message')}")
        return message.get("result") or {}


def _parse_rpc_body(raw: str, content_type: str, request_id: int) -> dict[str, Any]:
    """Parse a plain-JSON or SSE-framed JSON-RPC response body."""
    if "text/event-stream" in content_type:
        matched: dict[str, Any] | None = None
        for line in raw.splitlines():
            if not line.startswith("data:"):
                continue
            chunk = line[len("data:"):].strip()
            if not chunk:
                continue
            try:
                candidate = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if isinstance(candidate, dict) and candidate.get("id") == request_id:
                matched = candidate
        if matched is None:
            raise SnovioMCPError("MCP SSE response contained no matching JSON-RPC message.")
        return matched
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise SnovioMCPError(f"MCP returned invalid JSON: {raw[:300]}") from error
    if isinstance(parsed, list):  # batched responses
        for item in parsed:
            if isinstance(item, dict) and item.get("id") == request_id:
                return item
        raise SnovioMCPError("MCP batch response contained no matching message.")
    return parsed


def tool_result_text(result: dict[str, Any]) -> str:
    """Flatten an MCP tools/call result into text for LLM/tool consumers."""
    if result.get("isError"):
        prefix = "TOOL ERROR: "
    else:
        prefix = ""
    parts: list[str] = []
    for item in result.get("content") or []:
        if item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
        else:
            parts.append(json.dumps(item))
    structured = result.get("structuredContent")
    if structured is not None and not parts:
        parts.append(json.dumps(structured))
    return prefix + "\n".join(parts)
