"""In-app copilot — an Azure OpenAI tool-calling agent over app + Snov.io MCP tools.

The agent loop is deliberately small: the model sees a curated subset of the
user's Snov.io MCP tools (their own OAuth token) plus read-only app tools, and
iterates tool calls until it produces a final reply. Nothing here launches
campaigns or sends email — mutating Snov.io actions are limited to list and
prospect management, and app actions are read-only.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

import snovio_mcp

logger = logging.getLogger("emailmvp.copilot")

MAX_AGENT_STEPS = 8
MAX_TOOL_RESULT_CHARS = 9000

# Snov.io MCP tools the copilot may use (their own account, their own token).
MCP_TOOL_ALLOWLIST = {
    "app_get_user_info",
    "app_get_lists",
    "app_search_lists",
    "app_create_list",
    "app_rename_list",
    "app_delete_list",
    "app_restore_list",
    "app_list_prospects",
    "app_get_prospect",
    "app_add_prospects_to_list",
    "app_remove_prospects_from_list",
    "app_database_search_ai",
    "app_database_search_filters",
    "app_database_search_prospects",
    "app_database_search_prospects_add_to_list",
    "app_verify_email",
    "app_bulk_verify_emails",
    "app_bulk_verification_status",
    "app_find_email",
}

SYSTEM_PROMPT = (
    "You are the Cloudware Email Campaign Generator copilot. You help the signed-in "
    "user manage Snov.io prospects, lists, and lead sourcing, and you answer questions "
    "about their campaigns in this app.\n"
    "Rules:\n"
    "- Snov.io tools act on the user's own Snov.io account. Prefer read operations; "
    "confirm before deleting anything the user did not explicitly name.\n"
    "- You cannot generate emails, sync jobs, or create drip campaigns yourself; for "
    "those, point the user to the campaign wizard (steps 1-4) and explain what to click.\n"
    "- Lists in this app map one-to-one to campaigns; each generated touch is stored "
    "in Subject_TouchN / Body_TouchN custom fields on prospects.\n"
    "- Be concise. Summarise tool results in plain language, never dump raw JSON.\n"
    "- If Snov.io is not connected via OAuth, tell the user to click 'Connect Snov.io' "
    "in step 4 of the wizard."
)


def build_tool_specs(mcp_tools: list[dict[str, Any]], app_tools: dict[str, dict]) -> list[dict[str, Any]]:
    """Convert MCP + app tool definitions into OpenAI function-calling specs."""
    specs: list[dict[str, Any]] = []
    for tool in mcp_tools:
        name = str(tool.get("name") or "")
        if name not in MCP_TOOL_ALLOWLIST:
            continue
        specs.append({
            "type": "function",
            "function": {
                "name": f"snovio__{name}",
                "description": (tool.get("description") or "")[:1024],
                "parameters": tool.get("inputSchema") or {"type": "object", "properties": {}},
            },
        })
    for name, definition in app_tools.items():
        specs.append({
            "type": "function",
            "function": {
                "name": f"app__{name}",
                "description": definition["description"],
                "parameters": definition.get("parameters") or {"type": "object", "properties": {}},
            },
        })
    return specs


def run_agent(
    openai_client: Any,
    deployment: str,
    history: list[dict[str, str]],
    mcp_session: "snovio_mcp.SnovioMCPSession | None",
    app_tools: dict[str, dict],
    max_completion_tokens: int = 4096,
) -> dict[str, Any]:
    """Run the tool-calling loop; returns {reply, toolTrace}."""
    mcp_tools = []
    if mcp_session is not None:
        try:
            mcp_tools = mcp_session.list_tools()
        except snovio_mcp.SnovioMCPError as error:
            logger.warning("Copilot could not list MCP tools: %s", error)

    specs = build_tool_specs(mcp_tools, app_tools)
    messages: list[dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if mcp_session is None:
        messages.append({
            "role": "system",
            "content": "Note: the user has NOT connected Snov.io via OAuth, so no Snov.io tools are available.",
        })
    messages.extend(history)

    trace: list[dict[str, Any]] = []
    for _ in range(MAX_AGENT_STEPS):
        response = openai_client.chat.completions.create(
            model=deployment,
            messages=messages,
            tools=specs or None,
            max_completion_tokens=max_completion_tokens,
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return {"reply": message.content or "", "toolTrace": trace}

        messages.append({
            "role": "assistant",
            "content": message.content or "",
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {"name": call.function.name, "arguments": call.function.arguments},
                }
                for call in tool_calls
            ],
        })
        for call in tool_calls:
            name = call.function.name
            try:
                arguments = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            result = _dispatch(name, arguments, mcp_session, app_tools)
            trace.append({"tool": name, "arguments": arguments, "result": result[:400]})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result[:MAX_TOOL_RESULT_CHARS]})

    return {
        "reply": "I hit my step limit before finishing — please break the request into smaller steps.",
        "toolTrace": trace,
    }


def _dispatch(
    name: str,
    arguments: dict[str, Any],
    mcp_session: "snovio_mcp.SnovioMCPSession | None",
    app_tools: dict[str, dict],
) -> str:
    try:
        if name.startswith("snovio__"):
            if mcp_session is None:
                return "TOOL ERROR: Snov.io is not connected."
            tool_name = name[len("snovio__"):]
            if tool_name not in MCP_TOOL_ALLOWLIST:
                return "TOOL ERROR: tool not permitted."
            result = mcp_session.call_tool(tool_name, arguments)
            return snovio_mcp.tool_result_text(result) or "(empty result)"
        if name.startswith("app__"):
            tool_name = name[len("app__"):]
            definition = app_tools.get(tool_name)
            if not definition:
                return "TOOL ERROR: unknown app tool."
            handler: Callable[[dict[str, Any]], Any] = definition["handler"]
            outcome = handler(arguments)
            return json.dumps(outcome, default=str)[:MAX_TOOL_RESULT_CHARS]
        return "TOOL ERROR: unknown tool namespace."
    except snovio_mcp.SnovioMCPError as error:
        return f"TOOL ERROR: {error}"
    except Exception as error:  # tool failures must not kill the agent loop
        logger.exception("Copilot tool %s failed", name)
        return f"TOOL ERROR: {error}"
