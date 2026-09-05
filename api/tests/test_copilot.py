"""Tests for the in-app copilot agent loop."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import copilot


def _fake_response(content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _tool_call(call_id, name, arguments):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(arguments)))


def test_build_tool_specs_exposes_only_app_controlled_tools():
    mcp_tools = [
        {"name": "app_get_lists", "description": "lists", "inputSchema": {"type": "object", "properties": {}}},
        {"name": "li_send_invite", "description": "linkedin", "inputSchema": {}},  # not allowlisted
    ]
    app_tools = {"list_templates": {"description": "templates", "parameters": {"type": "object", "properties": {}}, "handler": lambda a: {}}}
    specs = copilot.build_tool_specs(mcp_tools, app_tools)
    names = [s["function"]["name"] for s in specs]
    assert "snovio__app_get_lists" not in names
    assert "app__list_templates" in names
    assert all("li_send_invite" not in n for n in names)


def test_run_agent_returns_direct_reply():
    client = MagicMock()
    client.chat.completions.create.return_value = _fake_response(content="Hello!")
    out = copilot.run_agent(client, "gpt-test", [{"role": "user", "content": "hi"}], None, {})
    assert out["reply"] == "Hello!"
    assert out["toolTrace"] == []


def test_run_agent_executes_app_tool_then_replies():
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _fake_response(tool_calls=[_tool_call("c1", "app__list_templates", {})]),
        _fake_response(content="You have 9 templates."),
    ]
    app_tools = {"list_templates": {
        "description": "templates", "parameters": {"type": "object", "properties": {}},
        "handler": lambda args: {"templates": ["a", "b"]},
    }}
    out = copilot.run_agent(client, "gpt-test", [{"role": "user", "content": "how many templates?"}], None, app_tools)
    assert out["reply"] == "You have 9 templates."
    assert out["toolTrace"][0]["tool"] == "app__list_templates"


def test_run_agent_collects_confirmation_without_trace_arguments():
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _fake_response(tool_calls=[_tool_call("c1", "app__execute_snovio_tool", {"toolName": "app_delete_list"})]),
        _fake_response(content="Please confirm."),
    ]
    app_tools = {"execute_snovio_tool": {
        "description": "execute", "parameters": {"type": "object", "properties": {}},
        "handler": lambda args: {
            "confirmationRequired": True, "confirmationId": "confirm-1",
            "toolName": "app_delete_list", "category": "destructive",
            "summary": "Delete list 42", "expiresAt": 1234,
        },
    }}
    out = copilot.run_agent(client, "gpt-test", [{"role": "user", "content": "delete it"}], MagicMock(), app_tools)
    assert out["reply"] == "Please confirm."
    assert out["confirmations"][0]["confirmationId"] == "confirm-1"
    assert "arguments" not in out["toolTrace"][0]
    assert "result" not in out["toolTrace"][0]


def test_dispatch_blocks_non_allowlisted_mcp_tool():
    session = MagicMock()
    result = asyncio.run(copilot._dispatch("snovio__li_send_invite", {}, session, {}))
    assert "Direct MCP calls are not permitted" in result
    session.call_tool.assert_not_called()


def test_dispatch_reports_missing_connection():
    assert "Direct MCP calls are not permitted" in asyncio.run(
        copilot._dispatch("snovio__app_get_lists", {}, None, {})
    )


def test_dispatch_tool_exception_becomes_error_string():
    def boom(_args):
        raise RuntimeError("nope")
    result = asyncio.run(copilot._dispatch("app__x", {}, None, {"x": {"description": "", "handler": boom}}))
    assert result.startswith("TOOL ERROR:")


def test_dispatch_awaits_async_handlers():
    async def async_handler(_args):
        return {"ok": True}
    result = asyncio.run(copilot._dispatch("app__async_tool", {}, None, {"async_tool": {"description": "", "handler": async_handler}}))
    assert json.loads(result) == {"ok": True}


def test_responses_preserves_reasoning_and_function_outputs():
    client = MagicMock()
    reasoning = MagicMock()
    reasoning.model_dump.return_value = {"type": "reasoning", "id": "r1", "encrypted_content": "opaque"}
    call = MagicMock()
    call.model_dump.return_value = {"type": "function_call", "call_id": "c1", "name": "app__check", "arguments": "{}"}
    client.responses.create.side_effect = [
        SimpleNamespace(status="completed", output=[reasoning, call]),
        SimpleNamespace(status="completed", output=[], output_text="Done"),
    ]
    result = asyncio.run(copilot.run_agent_async(client, "luna", [{"role": "user", "content": "check"}], None, {
        "check": {"description": "Check", "handler": lambda args: {"confirmationRequired": True, "confirmationId": "confirm-1"}}
    }, use_responses=True))
    assert result["reply"] == "Done"
    assert result["confirmations"][0]["confirmationId"] == "confirm-1"
    sent = client.responses.create.call_args.kwargs
    assert sent["store"] is False
    assert reasoning.model_dump.return_value in sent["input"]
    assert sent["input"][-1]["call_id"] == "c1"
