"""Run synthetic model compatibility checks; never invoke Snov.io tools."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from openai import AzureOpenAI, OpenAI

import copilot
from prompt_templates import PROMPT_REGISTRY, email_output_schema
from template_builder import preview_brief


def main():
    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
    key = os.environ["AZURE_OPENAI_API_KEY"]
    chat = AzureOpenAI(api_key=key, azure_endpoint=endpoint, api_version="2024-12-01-preview", max_retries=0, timeout=90)
    responses = OpenAI(api_key=key, base_url=endpoint.rstrip("/") + "/openai/v1/", max_retries=0, timeout=90)
    results = []
    synthetic = {"first_name": "Alex", "last_name": "Test", "organization": "Example Company",
                 "license_renewal": "Microsoft 365 Business Premium", "engagement_objectives": "Discuss renewal options"}
    for deployment in ("gpt-5.4-mini", "emailmvp-luna-canary"):
        for template_id in ("leads", "csp_renewal_with_license", "cold_email"):
            template = PROMPT_REGISTRY[template_id]
            started = time.monotonic()
            record = {"deployment": deployment, "check": template_id}
            try:
                response = chat.chat.completions.create(
                    model=deployment, max_completion_tokens=6000,
                    response_format=email_output_schema(template["num_emails"]),
                    messages=[{"role": "system", "content": template["system_prompt"] +
                               f"\nOutput contract: JSON object with emails array of exactly {template['num_emails']} subject/body objects. "
                               "This overrides earlier format instructions. Never invent missing customer facts."},
                              {"role": "user", "content": template["build_user_prompt"](synthetic)}],
                )
                choice = response.choices[0]
                emails = template["parse_response"](choice.message.content or "")
                record.update(passed=choice.finish_reason == "stop", emails=len(emails),
                              inputTokens=response.usage.prompt_tokens, outputTokens=response.usage.completion_tokens)
            except Exception as error:
                record.update(passed=False, errorType=type(error).__name__, error=str(error)[:500])
            record["seconds"] = round(time.monotonic() - started, 2)
            results.append(record)
            print(json.dumps(record), flush=True)
        started = time.monotonic()
        called = []
        tools = {"read_test_status": {"description": "Read the status of a synthetic test, with no external side effects.",
                                     "parameters": {"type": "object", "properties": {}},
                                     "handler": lambda args: called.append(True) or {"status": "ready"}}}
        record = {"deployment": deployment, "check": "responses_tool_loop"}
        try:
            outcome = asyncio.run(copilot.run_agent_async(
                responses, deployment, [{"role": "user", "content": "Call read_test_status, then report its status."}],
                None, tools, max_completion_tokens=6000, use_responses=True,
            ))
            record.update(passed=bool(called) and bool(outcome["reply"]), toolCalls=len(called))
        except Exception as error:
            record.update(passed=False, errorType=type(error).__name__, error=str(error)[:500])
        record["seconds"] = round(time.monotonic() - started, 2)
        results.append(record)
        print(json.dumps(record), flush=True)
        record = {"deployment": deployment, "check": "admin_brief_preview"}
        started = time.monotonic()
        try:
            preview = preview_brief(chat, deployment, {"audience": "IT managers", "offer": "License review",
                "facts": "A review is available; no guaranteed savings or discounts.", "cta": "Book a call", "numEmails": 2})
            record.update(passed=len(preview["sampleEmails"]) == 2)
        except Exception as error:
            record.update(passed=False, errorType=type(error).__name__, error=str(error)[:500])
        record["seconds"] = round(time.monotonic() - started, 2)
        results.append(record)
        print(json.dumps(record), flush=True)
    print(json.dumps({"passed": sum(item["passed"] for item in results), "total": len(results)}))
    return 0 if all(item["passed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())