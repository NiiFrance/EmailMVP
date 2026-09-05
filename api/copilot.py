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

MAX_AGENT_STEPS = 12
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
    "You are the Email Campaign Generator copilot. You help the signed-in "
    "user run campaigns end-to-end: source leads, draft emails from the app's templates, "
    "review them, sync to Snov.io, and create drip campaigns \u2014 plus manage Snov.io "
    "prospects and lists, and answer questions about their campaigns.\n"
    "Rules:\n"
    "- Snov.io tools act on the user's own Snov.io account. Prefer read operations; "
    "confirm before deleting anything the user did not explicitly name.\n"
    "- Workflow: when the user attaches a lead file the chat shows its jobId. Use "
    "app__start_generation with their chosen template, poll app__get_job_status until "
    "Completed, and show 2-3 sample drafts via app__get_job_output.\n"
    "- For any mutating action, call the controlled tool once all required arguments are "
    "known. The tool creates a server confirmation card; that exact card is the user's "
    "single approval step. Do not ask for an additional chat confirmation, and never say "
    "the action completed until the confirmation endpoint returns a successful result.\n"
    "- Campaigns are created as DRAFTS in Snov.io; nothing sends automatically.\n"
    "- Lists in this app map one-to-one to campaigns; each generated touch is stored "
    "in Subject_TouchN / Body_TouchN custom fields on prospects.\n"
    "- When the user asks to create a Snov.io list, use app_create_list. Never call "
    "app_add_prospects_to_list or app_database_search_prospects_add_to_list until a "
    "confirmed list creation has returned a concrete list ID.\n"
    "- Be concise. Summarise tool results in plain language, never dump raw JSON.\n"
    "- If Snov.io is not connected via OAuth, tell the user to open Settings and connect "
    "the Snov.io Copilot connection."
)


def build_tool_specs(mcp_tools: list[dict[str, Any]], app_tools: dict[str, dict]) -> list[dict[str, Any]]:
    """Convert app-controlled tool definitions into OpenAI function specs."""
    specs: list[dict[str, Any]] = []
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
    """Synchronous wrapper kept for callers without an event loop."""
    import asyncio
    return asyncio.run(run_agent_async(openai_client, deployment, history, mcp_session, app_tools, max_completion_tokens))


async def run_agent_async(
    openai_client: Any,
    deployment: str,
    history: list[dict[str, str]],
    mcp_session: "snovio_mcp.SnovioMCPSession | None",
    app_tools: dict[str, dict],
    max_completion_tokens: int = 4096,
    system_prompt: str = SYSTEM_PROMPT,
    use_responses: bool = False,
) -> dict[str, Any]:
    """Run the tool-calling loop; returns {reply, toolTrace}."""
    if use_responses:
        return await _run_responses_agent(openai_client, deployment, history, mcp_session, app_tools, max_completion_tokens, system_prompt)
    specs = build_tool_specs([], app_tools)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    if mcp_session is None:
        messages.append({
            "role": "system",
            "content": "Note: the user has NOT connected Snov.io via OAuth, so no Snov.io tools are available.",
        })
    messages.extend(history)

    trace: list[dict[str, Any]] = []
    confirmations: list[dict[str, Any]] = []
    for _ in range(MAX_AGENT_STEPS):
        import asyncio
        response = await asyncio.to_thread(openai_client.chat.completions.create,
            model=deployment,
            messages=messages,
            tools=specs or None,
            max_completion_tokens=max_completion_tokens,
        )
        message = response.choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            return {"reply": message.content or "", "toolTrace": trace, "confirmations": confirmations}

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
            result = await _dispatch(name, arguments, mcp_session, app_tools)
            trace.append({"tool": name, "status": "completed"})
            try:
                result_payload = json.loads(result)
                if isinstance(result_payload, dict) and result_payload.get("confirmationRequired"):
                    confirmations.append({
                        "confirmationId": result_payload.get("confirmationId"),
                        "toolName": result_payload.get("toolName"),
                        "category": result_payload.get("category"),
                        "summary": result_payload.get("summary"),
                        "expiresAt": result_payload.get("expiresAt"),
                    })
            except (json.JSONDecodeError, TypeError):
                pass
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result[:MAX_TOOL_RESULT_CHARS]})

    return {
        "reply": "I hit my step limit before finishing — please break the request into smaller steps.",
        "toolTrace": trace,
        "confirmations": confirmations,
    }


async def _dispatch(
    name: str,
    arguments: dict[str, Any],
    mcp_session: "snovio_mcp.SnovioMCPSession | None",
    app_tools: dict[str, dict],
) -> str:
    import inspect
    try:
        if name.startswith("snovio__"):
            return "TOOL ERROR: Direct MCP calls are not permitted; use the app-controlled catalog tools."
        if name.startswith("app__"):
            tool_name = name[len("app__"):]
            definition = app_tools.get(tool_name)
            if not definition:
                return "TOOL ERROR: unknown app tool."
            handler: Callable[[dict[str, Any]], Any] = definition["handler"]
            import asyncio
            outcome = handler(arguments) if inspect.iscoroutinefunction(handler) else await asyncio.to_thread(handler, arguments)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            return json.dumps(outcome, default=str)[:MAX_TOOL_RESULT_CHARS]
        return "TOOL ERROR: unknown tool namespace."
    except snovio_mcp.SnovioMCPError as error:
        return f"TOOL ERROR: {error}"
    except Exception as error:
        logger.exception("Copilot tool %s failed", name)
        return f"TOOL ERROR: {error}"


async def _run_responses_agent(client, deployment, history, session, app_tools, token_limit, system_prompt):
    import asyncio
    tools = [{"type": "function", **spec["function"], "strict": False} for spec in build_tool_specs([], app_tools)]
    inputs = list(history)
    trace = []
    confirmations = []
    for step in range(MAX_AGENT_STEPS):
        response = await asyncio.to_thread(
            client.responses.create, model=deployment, instructions=system_prompt,
            input=list(inputs), tools=tools or None, max_output_tokens=token_limit,
            store=False, reasoning={"effort": "low"},
        )
        if response.status != "completed":
            raise ValueError("Copilot returned an incomplete response. No unconfirmed action was executed.")
        outputs = [item.model_dump(exclude_none=True) for item in response.output]
        inputs.extend(outputs)
        if any(part.get("type") == "refusal" for item in outputs for part in item.get("content", [])):
            return {"reply": "The model declined this request.", "toolTrace": trace, "confirmations": confirmations}
        calls = [item for item in outputs if item.get("type") == "function_call"]
        if not calls:
            return {"reply": response.output_text or "", "toolTrace": trace, "confirmations": confirmations}
        for call in calls:
            try:
                arguments = json.loads(call.get("arguments") or "{}")
                if not isinstance(arguments, dict):
                    raise ValueError("Tool arguments must be an object.")
                result = await _dispatch(call["name"], arguments, session, app_tools)
            except (ValueError, TypeError):
                result = "TOOL ERROR: Invalid tool arguments."
            trace.append({"tool": call["name"], "status": "failed" if result.startswith("TOOL ERROR:") else "completed"})
            try:
                outcome = json.loads(result)
                if isinstance(outcome, dict) and outcome.get("confirmationRequired"):
                    confirmations.append({key: outcome.get(key) for key in (
                        "confirmationId", "toolName", "category", "summary", "expiresAt"
                    )})
            except (ValueError, TypeError):
                pass
            inputs.append({"type": "function_call_output", "call_id": call["call_id"], "output": result})
    return {"reply": "The step limit was reached. Please narrow the request.", "toolTrace": trace, "confirmations": confirmations}
