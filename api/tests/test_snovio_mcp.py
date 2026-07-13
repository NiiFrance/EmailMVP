"""Tests for the Snov.io MCP OAuth helpers and JSON-RPC parsing."""

import hashlib
import base64
import json

import pytest

from snovio_mcp import (
    SnovioMCPError,
    _parse_rpc_body,
    build_authorize_url,
    make_pkce_pair,
    tool_result_text,
)


def test_pkce_pair_is_valid_s256():
    verifier, challenge = make_pkce_pair()
    assert 43 <= len(verifier) <= 128
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    assert challenge == expected


def test_authorize_url_contains_required_params():
    url = build_authorize_url("client-1", "https://app.example.com/cb", "state-xyz", "challenge-abc")
    assert url.startswith("https://app.snov.io/mcp/authorize?")
    for fragment in (
        "response_type=code",
        "client_id=client-1",
        "state=state-xyz",
        "code_challenge=challenge-abc",
        "code_challenge_method=S256",
        "scope=mcp",
    ):
        assert fragment in url


def test_parse_rpc_body_plain_json():
    body = json.dumps({"jsonrpc": "2.0", "id": 3, "result": {"ok": True}})
    message = _parse_rpc_body(body, "application/json", 3)
    assert message["result"] == {"ok": True}


def test_parse_rpc_body_sse_frames():
    body = (
        "event: message\n"
        'data: {"jsonrpc": "2.0", "id": 1, "result": {"skip": true}}\n\n'
        "event: message\n"
        'data: {"jsonrpc": "2.0", "id": 7, "result": {"tools": []}}\n\n'
    )
    message = _parse_rpc_body(body, "text/event-stream", 7)
    assert message["result"] == {"tools": []}


def test_parse_rpc_body_sse_without_match_raises():
    with pytest.raises(SnovioMCPError):
        _parse_rpc_body('data: {"jsonrpc": "2.0", "id": 1, "result": {}}\n\n', "text/event-stream", 99)


def test_tool_result_text_flattens_content():
    result = {"content": [{"type": "text", "text": "hello"}, {"type": "text", "text": "world"}]}
    assert tool_result_text(result) == "hello\nworld"


def test_tool_result_text_marks_errors():
    result = {"isError": True, "content": [{"type": "text", "text": "boom"}]}
    assert tool_result_text(result).startswith("TOOL ERROR: ")
