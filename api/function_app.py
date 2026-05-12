"""Azure Functions app — Email MVP with Durable Functions orchestration.

Endpoints:
  POST /api/upload        — Upload CSV, start email generation
  GET  /api/status/{jobId} — Check processing progress
  GET  /api/download/{jobId} — Download enriched CSV
  GET  /api/templates     — List available prompt templates
"""

import json
import logging
import os
import uuid
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import azure.functions as func
import azure.durable_functions as df
from azure.storage.blob import BlobServiceClient, generate_blob_sas, BlobSasPermissions
from azure.identity import DefaultAzureCredential
from openai import AzureOpenAI

from prompt_templates import (
    SYSTEM_PROMPT,
    build_user_prompt,
    PROMPT_REGISTRY,
    get_template,
    list_templates,
)
from csv_processor import (
    parse_csv,
    parse_file,
    dataframe_to_csv_bytes,
    extract_all_leads,
    assemble_enriched_csv,
)
from column_mapper import resolve_columns
from snovio_client import SnovioAPIError, SnovioClient, SnovioConfigError
from snovio_workflows import (
    build_job_rows,
    build_prospect_payload,
    classify_verification,
    estimate_usage,
    find_campaign,
    is_sending_campaign,
    is_suppressed,
    summarize_report,
    verification_lookup,
)

app = df.DFApp(http_auth_level=func.AuthLevel.ANONYMOUS)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
STORAGE_CONN_STR = os.environ.get("STORAGE_CONNECTION_STRING", os.environ.get("AzureWebJobsStorage", ""))
STORAGE_ACCOUNT_NAME = os.environ.get("AzureWebJobsStorage__accountName", "")
STORAGE_CLIENT_ID = os.environ.get("AzureWebJobsStorage__clientId", "")
INPUT_CONTAINER = os.environ.get("CSV_INPUT_CONTAINER", "csv-input")
OUTPUT_CONTAINER = os.environ.get("CSV_OUTPUT_CONTAINER", "csv-output")
AZURE_OPENAI_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "")
AZURE_OPENAI_API_KEY = os.environ.get("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-5.5")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "100"))
SNOVIO_CLIENT_ID = os.environ.get("SNOVIO_CLIENT_ID", "")
SNOVIO_CLIENT_SECRET = os.environ.get("SNOVIO_CLIENT_SECRET", "")
SNOVIO_API_BASE_URL = os.environ.get("SNOVIO_API_BASE_URL", "https://api.snov.io")
SNOVIO_REQUESTS_PER_MINUTE = int(os.environ.get("SNOVIO_REQUESTS_PER_MINUTE", "60"))
SNOVIO_WEBHOOK_SECRET = os.environ.get("SNOVIO_WEBHOOK_SECRET", "")
SNOVIO_TEMPLATE_MAPPINGS = os.environ.get("SNOVIO_TEMPLATE_MAPPINGS", "{}")
SNOVIO_ALLOW_UNKNOWN_VERIFICATION = os.environ.get("SNOVIO_ALLOW_UNKNOWN_VERIFICATION", "false").lower() == "true"
SNOVIO_LOW_CREDIT_THRESHOLD = int(os.environ.get("SNOVIO_LOW_CREDIT_THRESHOLD", "0"))
MAX_CSV_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

logger = logging.getLogger("emailmvp")


# ---------------------------------------------------------------------------
# Helper — Blob Storage client
# ---------------------------------------------------------------------------
def _blob_service() -> BlobServiceClient:
    if STORAGE_ACCOUNT_NAME:
        # Production: use user-assigned managed identity
        credential = DefaultAzureCredential(managed_identity_client_id=STORAGE_CLIENT_ID) if STORAGE_CLIENT_ID else DefaultAzureCredential()
        return BlobServiceClient(f"https://{STORAGE_ACCOUNT_NAME}.blob.core.windows.net", credential=credential)
    return BlobServiceClient.from_connection_string(STORAGE_CONN_STR)


def _upload_blob(container: str, blob_name: str, data: bytes) -> None:
    client = _blob_service().get_container_client(container)
    try:
        client.create_container()
    except Exception:
        pass  # container already exists
    client.upload_blob(name=blob_name, data=data, overwrite=True)


def _download_blob(container: str, blob_name: str) -> bytes:
    client = _blob_service().get_blob_client(container, blob_name)
    return client.download_blob().readall()


def _json_response(payload: dict | list, status_code: int = 200) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload), status_code=status_code, mimetype="application/json")


def _request_json(req: func.HttpRequest) -> dict:
    try:
        data = req.get_json()
        return data if isinstance(data, dict) else {}
    except Exception:
        try:
            body = req.get_body()
            return json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            return {}


def _query_params(req: func.HttpRequest) -> dict:
    params = getattr(req, "params", {}) or {}
    return params if isinstance(params, dict) else {}


def _parse_bool(value, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_template_mappings() -> dict:
    try:
        mappings = json.loads(SNOVIO_TEMPLATE_MAPPINGS or "{}")
        return mappings if isinstance(mappings, dict) else {}
    except json.JSONDecodeError:
        return {}


def _download_job_csv(job_id: str, prefer_output: bool = True) -> bytes:
    blob_name = f"{job_id}.csv"
    if prefer_output:
        try:
            return _download_blob(OUTPUT_CONTAINER, blob_name)
        except Exception:
            pass
    return _download_blob(INPUT_CONTAINER, blob_name)


def _upload_snovio_report(job_id: str, report_name: str, payload: dict) -> str:
    blob_name = f"snovio-reports/{job_id}/{report_name}.json"
    _upload_blob(OUTPUT_CONTAINER, blob_name, json.dumps(payload, indent=2).encode("utf-8"))
    return blob_name


def _snovio_configured() -> bool:
    return bool(SNOVIO_CLIENT_ID and SNOVIO_CLIENT_SECRET)


def _snovio_required_response() -> func.HttpResponse | None:
    if _snovio_configured():
        return None
    return _json_response({"configured": False, "error": "Snov.io credentials are not configured."}, 503)


def _snovio_client() -> SnovioClient:
    return SnovioClient(
        client_id=SNOVIO_CLIENT_ID,
        client_secret=SNOVIO_CLIENT_SECRET,
        base_url=SNOVIO_API_BASE_URL,
        requests_per_minute=SNOVIO_REQUESTS_PER_MINUTE,
    )


def _snovio_campaign_list_id(campaign: dict | None) -> str:
    if not campaign:
        return ""
    return str(campaign.get("list_id") or campaign.get("listId") or "").strip()


def _snovio_list_name(payload: dict, job_id: str) -> str:
    explicit_name = str(payload.get("listName") or payload.get("list_name") or "").strip()
    if explicit_name:
        return explicit_name[:120]

    template_name = str(payload.get("templateName") or payload.get("templateId") or "Generated Leads").strip()
    source_file = str(payload.get("sourceFileName") or "").strip()
    date_suffix = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    parts = ["Cloudware", template_name]
    if source_file:
        parts.append(source_file.rsplit(".", 1)[0])
    parts.append(date_suffix)
    name = " - ".join(part for part in parts if part)
    return (name or f"Cloudware - {job_id[:8]} - {date_suffix}")[:120]


def _snovio_created_list_id(response: Any) -> str:
    payload = response[0] if isinstance(response, list) and response else response
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    return str(data.get("id") or payload.get("id") or "").strip()


# ===========================================================================
# 1. UPLOAD — HTTP Trigger
# ===========================================================================
@app.route(route="upload", methods=["POST"])
@app.durable_client_input(client_name="client")
async def upload_csv(req: func.HttpRequest, client) -> func.HttpResponse:
    """Accept a CSV file upload, store it, and start the orchestration."""
    try:
        file = req.files.get("file")
        if not file:
            return func.HttpResponse(
                json.dumps({"error": "No file provided. Use form field 'file'."}),
                status_code=400,
                mimetype="application/json",
            )

        filename = file.filename or ""
        if not filename.lower().endswith((".csv", ".xlsx")):
            return func.HttpResponse(
                json.dumps({"error": "Only .csv and .xlsx files are accepted."}),
                status_code=400,
                mimetype="application/json",
            )

        file_bytes = file.read()
        if len(file_bytes) > MAX_CSV_SIZE_BYTES:
            return func.HttpResponse(
                json.dumps({"error": f"File too large. Maximum size is {MAX_CSV_SIZE_BYTES // (1024*1024)} MB."}),
                status_code=400,
                mimetype="application/json",
            )

        # Resolve prompt template
        prompt_id = req.form.get("prompt_id", "cold_email")

        try:
            template = get_template(prompt_id)
        except KeyError:
            return func.HttpResponse(
                json.dumps({"error": f"Unknown template: {prompt_id}. Use GET /api/templates to list available templates."}),
                status_code=400,
                mimetype="application/json",
            )

        # Parse the file (CSV or Excel)
        try:
            df_check = parse_file(file_bytes, filename)
            total_leads = len(df_check)
            if total_leads == 0:
                return func.HttpResponse(
                    json.dumps({"error": "File has no data rows."}),
                    status_code=400,
                    mimetype="application/json",
                )
        except Exception as e:
            return func.HttpResponse(
                json.dumps({"error": f"Invalid file: {str(e)}"}),
                status_code=400,
                mimetype="application/json",
            )

        # Smart column detection — skip for custom templates (no required_fields)
        column_map = None
        required_fields = template.get("required_fields")
        if required_fields:
            headers = df_check.columns.tolist()
            try:
                openai_client = AzureOpenAI(
                    api_key=AZURE_OPENAI_API_KEY,
                    azure_endpoint=AZURE_OPENAI_ENDPOINT,
                    api_version="2024-12-01-preview",
                )
                column_map = resolve_columns(
                    headers,
                    client=openai_client,
                    deployment=AZURE_OPENAI_DEPLOYMENT,
                    required_fields=required_fields,
                )
            except ValueError as e:
                return func.HttpResponse(
                    json.dumps({"error": str(e)}),
                    status_code=400,
                    mimetype="application/json",
                )

        # Always store as CSV in blob storage (convert Excel if needed)
        if filename.lower().endswith(".xlsx"):
            csv_bytes = dataframe_to_csv_bytes(df_check)
        else:
            csv_bytes = file_bytes

        job_id = str(uuid.uuid4())
        blob_name = f"{job_id}.csv"

        _upload_blob(INPUT_CONTAINER, blob_name, csv_bytes)
        logger.info("Uploaded %s (%d leads) as %s [template=%s]", filename, total_leads, blob_name, template["id"])

        # Store template config for use by activities
        template_config = {"id": prompt_id}

        # Start orchestration
        orchestrator_input = {
            "job_id": job_id,
            "column_map": column_map,
            "template_config": template_config,
        }
        instance_id = await client.start_new("orchestrate_emails", client_input=orchestrator_input, instance_id=job_id)

        return func.HttpResponse(
            json.dumps({
                "jobId": job_id,
                "totalLeads": total_leads,
                "templateId": template["id"],
                "templateName": template["name"],
                "statusUrl": f"/api/status/{job_id}",
                "downloadUrl": f"/api/download/{job_id}",
            }),
            status_code=202,
            mimetype="application/json",
        )

    except Exception as e:
        logger.exception("Upload failed")
        return func.HttpResponse(
            json.dumps({"error": f"Upload failed: {str(e)}"}),
            status_code=500,
            mimetype="application/json",
        )


# ===========================================================================
# 2. ORCHESTRATOR — Durable Function (fan-out / fan-in)
# ===========================================================================
@app.orchestration_trigger(context_name="context")
def orchestrate_emails(context: df.DurableOrchestrationContext):
    """Fan-out email generation across all leads, then assemble results."""
    input_data = context.get_input()

    # Support both new dict input and legacy string input
    if isinstance(input_data, dict):
        job_id = input_data["job_id"]
        column_map = input_data.get("column_map")
        template_config = input_data.get("template_config", {"id": "cold_email"})
    else:
        job_id = input_data
        column_map = None
        template_config = {"id": "cold_email"}

    # Step 1: Read CSV and extract leads (activity — deterministic requirement)
    extract_input = {"job_id": job_id, "column_map": column_map}
    leads = yield context.call_activity("extract_leads_activity", extract_input)

    total = len(leads)
    results = []
    context.set_custom_status({"processedLeads": 0, "totalLeads": total, "phase": "processing"})

    # Step 2: Process in batches to respect rate limits
    for batch_start in range(0, total, BATCH_SIZE):
        batch = leads[batch_start : batch_start + BATCH_SIZE]

        # Fan-out: process all leads in this batch in parallel
        # Attach template_config to each lead for the activity
        tasks = [
            context.call_activity(
                "process_lead_activity",
                {"lead_data": lead, "template_config": template_config},
            )
            for lead in batch
        ]
        batch_results = yield context.task_all(tasks)
        results.extend(batch_results)

        # Update progress after each batch completes
        context.set_custom_status({"processedLeads": len(results), "totalLeads": total, "phase": "processing"})

        # Rate-limit pause between batches (skip after last batch)
        if batch_start + BATCH_SIZE < total:
            next_fire = context.current_utc_datetime + timedelta(seconds=2)
            yield context.create_timer(next_fire)

    context.set_custom_status({"processedLeads": total, "totalLeads": total, "phase": "assembling"})

    # Step 3: Assemble enriched CSV
    assemble_input = {"job_id": job_id, "results": results, "template_config": template_config}
    output_blob = yield context.call_activity("assemble_csv_activity", assemble_input)

    return {"status": "completed", "totalLeads": total, "outputBlob": output_blob}


# ===========================================================================
# 3. ACTIVITY — Extract leads from CSV
# ===========================================================================
@app.activity_trigger(input_name="extractInput")
def extract_leads_activity(extractInput: dict) -> list:
    """Read the uploaded CSV from Blob Storage and extract lead data."""
    job_id = extractInput["job_id"]
    column_map = extractInput.get("column_map")
    csv_bytes = _download_blob(INPUT_CONTAINER, f"{job_id}.csv")
    dataframe = parse_csv(csv_bytes)
    leads = extract_all_leads(dataframe, column_map)
    logger.info("Extracted %d leads for job %s", len(leads), job_id)
    return leads


# ===========================================================================
# Helper — Resolve template from config
# ===========================================================================
def _resolve_template(template_config: dict) -> dict:
    """Resolve a template dict from the config passed through the orchestrator."""
    template_id = template_config.get("id", "cold_email")
    return get_template(template_id)


# ===========================================================================
# 4. ACTIVITY — Process a single lead (call Azure OpenAI)
# ===========================================================================
@app.activity_trigger(input_name="leadInput")
def process_lead_activity(leadInput: dict) -> dict:
    """Generate content for a single lead using the selected template."""
    # Unpack lead data and template config
    lead_data = leadInput.get("lead_data", leadInput)  # backward compat
    template_config = leadInput.get("template_config", {"id": "cold_email"})

    row_index = lead_data.get("row_index", -1)
    first_name = lead_data.get("first_name", "Unknown")
    organization = lead_data.get("organization", lead_data.get("organisation_name", "Unknown"))

    logger.info("Processing lead %d: %s at %s", row_index, first_name, organization)

    try:
        template = _resolve_template(template_config)

        client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_version="2024-12-01-preview",
        )

        user_prompt_builder = template["build_user_prompt"]
        user_prompt = user_prompt_builder(lead_data)

        completion = client.chat.completions.create(
            model=AZURE_OPENAI_DEPLOYMENT,
            messages=[
                {"role": "system", "content": template["system_prompt"]},
                {"role": "user", "content": user_prompt},
            ],
            max_completion_tokens=8192,
        )

        response_text = completion.choices[0].message.content or ""

        # Parse using template's parser
        parse_response = template["parse_response"]
        parsed = parse_response(response_text)

        logger.info("Successfully generated content for lead %d [template=%s]", row_index, template["id"])

        return {"row_index": row_index, "parsed": parsed}

    except json.JSONDecodeError as e:
        logger.error("JSON parse error for lead %d: %s", row_index, str(e))
        return {"row_index": row_index, "error": f"Invalid JSON from model: {str(e)}"}
    except ValueError as e:
        logger.error("Validation error for lead %d: %s", row_index, str(e))
        return {"row_index": row_index, "error": str(e)}
    except Exception as e:
        logger.error("Error processing lead %d: %s", row_index, str(e))
        return {"row_index": row_index, "error": str(e)}


# ===========================================================================
# 5. ACTIVITY — Assemble enriched CSV
# ===========================================================================
@app.activity_trigger(input_name="assembleInput")
def assemble_csv_activity(assembleInput: dict) -> str:
    """Merge generated content into the original CSV and upload the result."""
    job_id = assembleInput["job_id"]
    results = assembleInput["results"]
    template_config = assembleInput.get("template_config", {"id": "cold_email"})

    template = _resolve_template(template_config)

    # Get output headers and flatten function from the template
    output_headers_fn = template.get("output_headers")
    flatten_result_fn = template.get("flatten_result")
    output_headers = output_headers_fn()

    csv_bytes = _download_blob(INPUT_CONTAINER, f"{job_id}.csv")
    enriched_bytes = assemble_enriched_csv(
        csv_bytes,
        results,
        output_headers=output_headers,
        flatten_result=flatten_result_fn,
    )

    output_blob_name = f"{job_id}.csv"
    _upload_blob(OUTPUT_CONTAINER, output_blob_name, enriched_bytes)

    logger.info("Assembled enriched CSV for job %s (%d bytes) [template=%s]", job_id, len(enriched_bytes), template["id"])
    return output_blob_name


# ===========================================================================
# 6. TEMPLATES — HTTP Trigger (list available prompt templates)
# ===========================================================================
@app.route(route="templates", methods=["GET"])
async def get_templates(req: func.HttpRequest) -> func.HttpResponse:
    """Return the list of available prompt templates."""
    templates = list_templates()
    return func.HttpResponse(
        json.dumps({"templates": templates}),
        status_code=200,
        mimetype="application/json",
    )


# ===========================================================================
# 7. SNOV.IO — HTTP Triggers (configuration and balance preflight)
# ===========================================================================
@app.route(route="snovio/status", methods=["GET"])
async def get_snovio_status(req: func.HttpRequest) -> func.HttpResponse:
    """Return Snov.io integration status without exposing secrets."""
    return _json_response({
        "configured": _snovio_configured(),
        "apiBaseUrl": SNOVIO_API_BASE_URL,
        "rateLimitPerMinute": SNOVIO_REQUESTS_PER_MINUTE,
        "allowUnknownVerification": SNOVIO_ALLOW_UNKNOWN_VERIFICATION,
        "webhookSecretConfigured": bool(SNOVIO_WEBHOOK_SECRET),
        "templateMappingsConfigured": bool(_parse_template_mappings()),
    })


@app.route(route="snovio/balance", methods=["GET"])
async def get_snovio_balance(req: func.HttpRequest) -> func.HttpResponse:
    """Return Snov.io account balance as a preflight check."""
    missing = _snovio_required_response()
    if missing:
        return missing

    try:
        balance = _snovio_client().get_balance()
        return _json_response({"configured": True, "balance": balance})
    except SnovioConfigError as error:
        return _json_response({"configured": False, "error": str(error)}, 503)
    except SnovioAPIError as error:
        status_code = 429 if error.status_code == 429 else 502
        return _json_response({"configured": True, "error": str(error), "statusCode": error.status_code}, status_code)


@app.route(route="snovio/options", methods=["GET"])
async def get_snovio_options(req: func.HttpRequest) -> func.HttpResponse:
    """Return Snov.io lists, campaigns, custom fields, and template mappings."""
    missing = _snovio_required_response()
    if missing:
        return _json_response({
            "configured": False,
            "lists": [],
            "campaigns": [],
            "customFields": [],
            "templateMappings": _parse_template_mappings(),
        })

    try:
        client = _snovio_client()
        return _json_response({
            "configured": True,
            "lists": client.get_user_lists(),
            "campaigns": client.get_user_campaigns(),
            "customFields": client.get_custom_fields(),
            "templateMappings": _parse_template_mappings(),
            "templates": list_templates(),
        })
    except SnovioAPIError as error:
        return _json_response({"configured": True, "error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/preflight", methods=["GET"])
async def get_snovio_preflight(req: func.HttpRequest) -> func.HttpResponse:
    """Estimate credit/rate impact before a Snov.io operation."""
    params = _query_params(req)
    operation = params.get("operation", "sync")
    job_id = params.get("jobId", "")

    try:
        if job_id:
            dataframe = parse_csv(_download_job_csv(job_id))
            lead_count = len(dataframe)
        else:
            lead_count = int(params.get("leadCount", "0"))
    except Exception as error:
        return _json_response({"error": f"Unable to calculate preflight: {str(error)}"}, 400)

    estimate = estimate_usage(lead_count, operation)
    response = {"configured": _snovio_configured(), "estimate": estimate, "rateLimitPerMinute": SNOVIO_REQUESTS_PER_MINUTE}

    if _snovio_configured():
        try:
            balance = _snovio_client().get_balance()
            balance_value = float((balance.get("data") or {}).get("balance", 0))
            response["balance"] = balance
            response["lowCredit"] = balance_value < estimate["estimatedCredits"] + SNOVIO_LOW_CREDIT_THRESHOLD
        except Exception as error:
            response["balanceError"] = str(error)

    return _json_response(response)


@app.route(route="jobs/{jobId}/snovio/verify", methods=["POST"])
async def verify_job_emails(req: func.HttpRequest) -> func.HttpResponse:
    """Start Snov.io email verification for a generated job."""
    missing = _snovio_required_response()
    if missing:
        return missing

    job_id = req.route_params.get("jobId", "")
    payload = _request_json(req)
    dry_run = _parse_bool(payload.get("dryRun"), default=True)
    poll = _parse_bool(payload.get("poll"), default=False)
    allow_unknown = _parse_bool(payload.get("allowUnknown"), SNOVIO_ALLOW_UNKNOWN_VERIFICATION)
    webhook_url = payload.get("webhookUrl")

    try:
        dataframe = parse_csv(_download_job_csv(job_id))
        rows, columns = build_job_rows(dataframe)
        emails = [row["email"] for row in rows if row.get("email")]
        report = {
            "jobId": job_id,
            "dryRun": dry_run,
            "columns": columns,
            "estimate": estimate_usage(len(emails), "verify"),
            "tasks": [],
            "results": [],
        }

        if dry_run:
            report["results"] = [{"rowIndex": row["rowIndex"], "email": row["email"], "eligible": False, "blockedReason": "dry_run"} for row in rows]
            report["summary"] = summarize_report(report["results"])
            return _json_response(report)

        client = _snovio_client()
        for start in range(0, len(emails), 10):
            batch = emails[start:start + 10]
            task = client.start_email_verification(batch, webhook_url=webhook_url)
            task_hash = (task.get("data") or {}).get("task_hash") or (task.get("meta") or {}).get("task_hash")
            task_entry = {"emails": batch, "taskHash": task_hash, "response": task}
            if poll and task_hash:
                result = client.get_email_verification_result(task_hash)
                task_entry["result"] = result
                for item in result.get("data", []):
                    report["results"].append(classify_verification(item, allow_unknown=allow_unknown))
            report["tasks"].append(task_entry)

        report["summary"] = summarize_report(report["results"])
        report["reportBlob"] = _upload_snovio_report(job_id, "verification", report)
        return _json_response(report)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)
    except Exception as error:
        logger.exception("Snov.io verification failed for %s", job_id)
        return _json_response({"error": f"Snov.io verification failed: {str(error)}"}, 500)


@app.route(route="snovio/verification-result", methods=["POST"])
async def get_snovio_verification_result(req: func.HttpRequest) -> func.HttpResponse:
    """Fetch and classify a Snov.io email verification task result."""
    missing = _snovio_required_response()
    if missing:
        return missing
    payload = _request_json(req)
    task_hash = payload.get("taskHash") or payload.get("task_hash")
    allow_unknown = _parse_bool(payload.get("allowUnknown"), SNOVIO_ALLOW_UNKNOWN_VERIFICATION)
    if not task_hash:
        return _json_response({"error": "taskHash is required."}, 400)
    try:
        result = _snovio_client().get_email_verification_result(task_hash)
        classified = [classify_verification(item, allow_unknown=allow_unknown) for item in result.get("data", [])]
        return _json_response({"taskHash": task_hash, "status": result.get("status"), "results": classified, "raw": result})
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="jobs/{jobId}/snovio/sync", methods=["POST"])
async def sync_job_to_snovio(req: func.HttpRequest) -> func.HttpResponse:
    """Dry-run or execute post-generation prospect sync into a Snov.io list."""
    missing = _snovio_required_response()
    if missing:
        return missing

    job_id = req.route_params.get("jobId", "")
    payload = _request_json(req)
    list_id = str(payload.get("listId") or payload.get("list_id") or "").strip()
    campaign_id = str(payload.get("campaignId") or payload.get("campaign_id") or "").strip()
    dry_run = _parse_bool(payload.get("dryRun"), default=True)
    auto_create_list = _parse_bool(payload.get("createListIfMissing", payload.get("autoCreateList")), default=False)
    require_verification = _parse_bool(payload.get("requireVerification"), default=True)
    confirm_active_campaign = _parse_bool(payload.get("confirmActiveCampaign"), default=False)
    allow_unknown = _parse_bool(payload.get("allowUnknown"), SNOVIO_ALLOW_UNKNOWN_VERIFICATION)
    suppressed_emails = {str(item).strip().lower() for item in payload.get("suppressedEmails", [])}
    suppressed_domains = {str(item).strip().lower() for item in payload.get("suppressedDomains", [])}

    try:
        client = _snovio_client()
        campaigns = client.get_user_campaigns() if campaign_id else []
        campaign = find_campaign(campaigns, campaign_id) if campaign_id else None
        campaign_list_id = _snovio_campaign_list_id(campaign)
        list_source = "selected" if list_id else ""
        if not list_id and campaign_list_id:
            list_id = campaign_list_id
            list_source = "campaign"

        list_name = _snovio_list_name(payload, job_id)
        planned_list_creation = not list_id and auto_create_list
        created_list = None

        if not list_id and not auto_create_list:
            return _json_response({
                "error": "listId is required unless autoCreateList=true or the selected campaign includes list_id.",
                "campaign": campaign,
            }, 400)

        active_campaign = is_sending_campaign(campaign)
        if active_campaign and not dry_run and not confirm_active_campaign:
            return _json_response({
                "error": "Active campaign sync requires confirmActiveCampaign=true.",
                "campaign": campaign,
                "dryRunRecommended": True,
            }, 409)

        if planned_list_creation:
            list_source = "planned_create"

        dataframe = parse_csv(_download_job_csv(job_id))
        rows, columns = build_job_rows(dataframe)
        custom_fields = client.get_custom_fields() if payload.get("includeGeneratedCustomFields", True) else []
        verification = verification_lookup(payload.get("verificationResults", []), allow_unknown=allow_unknown)
        report_rows = []
        sync_candidates = []

        for row_info in rows:
            row_index = row_info["rowIndex"]
            email = row_info.get("email", "")
            blocked_reason = is_suppressed(email, suppressed_emails, suppressed_domains)
            verification_result = verification.get(email.lower()) if email else None
            if not blocked_reason and require_verification and not verification_result:
                blocked_reason = "verification_required"
            if not blocked_reason and verification_result and not verification_result.get("eligible"):
                blocked_reason = verification_result.get("blockedReason") or "verification_blocked"

            row_report = {
                "rowIndex": row_index,
                "email": email,
                "eligible": not bool(blocked_reason),
                "blockedReason": blocked_reason,
                "verification": verification_result,
                "status": "skipped" if blocked_reason or dry_run else "pending",
            }

            if row_report["eligible"] and not dry_run:
                sync_candidates.append((row_info, row_report))

            report_rows.append(row_report)

        if planned_list_creation and sync_candidates:
            created_list = client.create_prospect_list(list_name)
            list_id = _snovio_created_list_id(created_list)
            if not list_id:
                return _json_response({"error": "Snov.io list was created but no list ID was returned.", "createdList": created_list}, 502)
            list_source = "created"

        for row_info, row_report in sync_candidates:
            row_index = row_info["rowIndex"]
            email = row_info.get("email", "")
            if row_report["eligible"]:
                try:
                    duplicate = client.get_prospects_by_email(email) if email else {"data": []}
                    existing_in_target = any(
                        str(item.get("id")) == list_id
                        for prospect in duplicate.get("data", [])
                        for item in prospect.get("lists", [])
                    )
                    if existing_in_target:
                        row_report.update({"eligible": False, "blockedReason": "duplicate_in_target_list", "status": "skipped"})
                    else:
                        prospect_payload = build_prospect_payload(dataframe.iloc[row_index], columns, list_id, custom_fields)
                        response = client.add_prospect_to_list(list_id, prospect_payload)
                        row_report["response"] = response
                        row_report["snovioProspectId"] = response.get("id")
                        row_report["status"] = "updated" if response.get("updated") else "added" if response.get("added") else "failed"
                except Exception as error:
                    row_report.update({"status": "failed", "error": str(error)})

        report = {
            "jobId": job_id,
            "listId": list_id,
            "listSource": list_source,
            "listName": list_name if planned_list_creation or list_source == "created" else "",
            "plannedListCreation": planned_list_creation and not created_list,
            "createdList": created_list,
            "campaignId": campaign_id,
            "campaign": campaign,
            "activeCampaign": active_campaign,
            "dryRun": dry_run,
            "requireVerification": require_verification,
            "columns": columns,
            "summary": summarize_report(report_rows),
            "rows": report_rows,
        }
        report["reportBlob"] = _upload_snovio_report(job_id, "sync", report)
        return _json_response(report)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)
    except Exception as error:
        logger.exception("Snov.io sync failed for %s", job_id)
        return _json_response({"error": f"Snov.io sync failed: {str(error)}"}, 500)


@app.route(route="jobs/{jobId}/snovio/enrich", methods=["POST"])
async def enrich_job_with_snovio(req: func.HttpRequest) -> func.HttpResponse:
    """Dry-run or start optional Snov.io enrichment tasks for a job."""
    missing = _snovio_required_response()
    if missing:
        return missing

    job_id = req.route_params.get("jobId", "")
    payload = _request_json(req)
    dry_run = _parse_bool(payload.get("dryRun"), default=True)
    webhook_url = payload.get("webhookUrl")
    operations = set(payload.get("operations") or ["company_domain", "email_finder", "linkedin_profile"])

    try:
        dataframe = parse_csv(_download_job_csv(job_id, prefer_output=False))
        rows, columns = build_job_rows(dataframe)
        company_names = [row["companyName"] for row in rows if row.get("companyName") and not row.get("companySite")]
        email_finder_rows = [
            {"first_name": row["firstName"], "last_name": row["lastName"], "domain": row["companySite"]}
            for row in rows
            if not row.get("email") and row.get("firstName") and row.get("lastName") and row.get("companySite")
        ]
        linkedin_urls = [row["linkedin"] for row in rows if row.get("linkedin")]
        report = {
            "jobId": job_id,
            "dryRun": dry_run,
            "columns": columns,
            "estimate": estimate_usage(len(rows), "enrich"),
            "availableWork": {
                "companyDomainNames": len(company_names),
                "emailFinderRows": len(email_finder_rows),
                "linkedinUrls": len(linkedin_urls),
            },
            "tasks": [],
        }
        if dry_run:
            return _json_response(report)

        client = _snovio_client()
        if "company_domain" in operations:
            for start in range(0, len(company_names), 10):
                batch = company_names[start:start + 10]
                if batch:
                    report["tasks"].append({"kind": "company_domain", "response": client.start_company_domain_by_name(batch, webhook_url)})
        if "email_finder" in operations:
            for start in range(0, len(email_finder_rows), 10):
                batch = email_finder_rows[start:start + 10]
                if batch:
                    report["tasks"].append({"kind": "email_finder", "response": client.start_emails_by_name_domain(batch, webhook_url)})
        if "linkedin_profile" in operations:
            for start in range(0, len(linkedin_urls), 10):
                batch = linkedin_urls[start:start + 10]
                if batch:
                    report["tasks"].append({"kind": "linkedin_profile", "response": client.start_linkedin_profiles_by_urls(batch, webhook_url)})
        report["reportBlob"] = _upload_snovio_report(job_id, "enrichment", report)
        return _json_response(report)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)
    except Exception as error:
        logger.exception("Snov.io enrichment failed for %s", job_id)
        return _json_response({"error": f"Snov.io enrichment failed: {str(error)}"}, 500)


@app.route(route="snovio/enrichment-result", methods=["POST"])
async def get_snovio_enrichment_result(req: func.HttpRequest) -> func.HttpResponse:
    """Fetch a Snov.io enrichment task result."""
    missing = _snovio_required_response()
    if missing:
        return missing
    payload = _request_json(req)
    kind = payload.get("kind")
    task_hash = payload.get("taskHash") or payload.get("task_hash")
    if not kind or not task_hash:
        return _json_response({"error": "kind and taskHash are required."}, 400)
    client = _snovio_client()
    try:
        if kind == "company_domain":
            result = client.get_company_domain_by_name_result(task_hash)
        elif kind == "email_finder":
            result = client.get_emails_by_name_domain_result(task_hash)
        elif kind == "linkedin_profile":
            result = client.get_linkedin_profiles_by_urls_result(task_hash)
        else:
            return _json_response({"error": "Unsupported enrichment kind."}, 400)
        return _json_response({"kind": kind, "taskHash": task_hash, "result": result})
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/analytics", methods=["GET"])
async def get_snovio_analytics(req: func.HttpRequest) -> func.HttpResponse:
    """Proxy campaign analytics without exposing Snov.io credentials."""
    missing = _snovio_required_response()
    if missing:
        return missing
    params = _query_params(req)
    campaign_id = params.get("campaignId", "")
    filters = {}
    if campaign_id:
        filters["campaign_id"] = campaign_id
    if params.get("dateFrom"):
        filters["date_from"] = params.get("dateFrom")
    if params.get("dateTo"):
        filters["date_to"] = params.get("dateTo")
    try:
        client = _snovio_client()
        response = {"analytics": client.get_campaign_analytics(filters)}
        if campaign_id:
            response["progress"] = client.get_campaign_progress(campaign_id)
            if _parse_bool(params.get("includeActivity"), default=False):
                response["activity"] = {
                    name: client.get_campaign_activity(name, campaign_id)
                    for name in ["sent", "opened", "clicked", "replies", "finished"]
                }
        return _json_response(response)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/suppressions", methods=["POST"])
async def add_snovio_suppressions(req: func.HttpRequest) -> func.HttpResponse:
    """Add emails or domains to a Snov.io Do-not-email list."""
    missing = _snovio_required_response()
    if missing:
        return missing
    payload = _request_json(req)
    list_id = str(payload.get("listId") or payload.get("list_id") or "").strip()
    items = [str(item).strip() for item in payload.get("items", []) if str(item).strip()]
    if not list_id or not items:
        return _json_response({"error": "listId and at least one item are required."}, 400)
    try:
        response = _snovio_client().add_do_not_email(list_id, items)
        audit = {"listId": list_id, "items": items, "response": response, "createdAt": datetime.now(timezone.utc).isoformat()}
        _upload_blob(OUTPUT_CONTAINER, f"snovio-audit/suppressions/{uuid.uuid4()}.json", json.dumps(audit, indent=2).encode("utf-8"))
        return _json_response(audit)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/recipient-status", methods=["POST"])
async def change_snovio_recipient_status(req: func.HttpRequest) -> func.HttpResponse:
    """Pause, activate, or unsubscribe a Snov.io campaign recipient."""
    missing = _snovio_required_response()
    if missing:
        return missing
    payload = _request_json(req)
    try:
        response = _snovio_client().change_recipient_status(
            email=payload.get("email", ""),
            campaign_id=str(payload.get("campaignId") or payload.get("campaign_id") or ""),
            status=payload.get("status", ""),
        )
        return _json_response({"response": response})
    except (ValueError, SnovioAPIError) as error:
        status_code = 400 if isinstance(error, ValueError) else 502
        return _json_response({"error": str(error)}, status_code)


@app.route(route="snovio/webhook", methods=["POST"])
async def receive_snovio_webhook(req: func.HttpRequest) -> func.HttpResponse:
    """Receive Snov.io webhook events and persist them idempotently."""
    if not SNOVIO_WEBHOOK_SECRET:
        return _json_response({"error": "Snov.io webhook secret is not configured."}, 503)
    params = _query_params(req)
    provided = params.get("token") or getattr(req, "headers", {}).get("x-snovio-webhook-secret", "")
    if not hmac.compare_digest(str(provided), SNOVIO_WEBHOOK_SECRET):
        return _json_response({"error": "Invalid webhook token."}, 401)

    payload = _request_json(req)
    canonical = json.dumps(payload, sort_keys=True)
    event_id = payload.get("event_id") or payload.get("id") or hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    blob_name = f"snovio-webhooks/{event_id}.json"
    _upload_blob(OUTPUT_CONTAINER, blob_name, json.dumps({"eventId": event_id, "payload": payload}, indent=2).encode("utf-8"))
    return _json_response({"accepted": True, "eventId": event_id, "eventBlob": blob_name})


@app.route(route="snovio/webhooks", methods=["GET"])
async def list_snovio_webhooks(req: func.HttpRequest) -> func.HttpResponse:
    missing = _snovio_required_response()
    if missing:
        return missing
    try:
        return _json_response(_snovio_client().list_webhooks())
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/webhooks", methods=["POST"])
async def create_snovio_webhook(req: func.HttpRequest) -> func.HttpResponse:
    missing = _snovio_required_response()
    if missing:
        return missing
    payload = _request_json(req)
    try:
        response = _snovio_client().create_webhook(payload.get("eventObject", ""), payload.get("eventAction", ""), payload.get("endpointUrl", ""))
        return _json_response(response)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/webhooks/{webhookId}", methods=["PUT"])
async def update_snovio_webhook(req: func.HttpRequest) -> func.HttpResponse:
    missing = _snovio_required_response()
    if missing:
        return missing
    payload = _request_json(req)
    try:
        response = _snovio_client().update_webhook(req.route_params.get("webhookId", ""), payload.get("status", ""))
        return _json_response(response)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/webhooks/{webhookId}", methods=["DELETE"])
async def delete_snovio_webhook(req: func.HttpRequest) -> func.HttpResponse:
    missing = _snovio_required_response()
    if missing:
        return missing
    try:
        response = _snovio_client().delete_webhook(req.route_params.get("webhookId", ""))
        return _json_response(response)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


# ===========================================================================
# 8. STATUS — HTTP Trigger
# ===========================================================================
@app.route(route="status/{jobId}", methods=["GET"])
@app.durable_client_input(client_name="client")
async def get_status(req: func.HttpRequest, client) -> func.HttpResponse:
    """Return the processing status of a job."""
    job_id = req.route_params.get("jobId", "")
    if not job_id:
        return func.HttpResponse(
            json.dumps({"error": "Missing jobId"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        status = await client.get_status(job_id)
        if status is None:
            return func.HttpResponse(
                json.dumps({"error": "Job not found"}),
                status_code=404,
                mimetype="application/json",
            )

        runtime_status = str(status.runtime_status).split(".")[-1] if status.runtime_status else "Unknown"

        response_body = {
            "jobId": job_id,
            "status": runtime_status,
            "createdTime": status.created_time.isoformat() if status.created_time else None,
            "lastUpdatedTime": status.last_updated_time.isoformat() if status.last_updated_time else None,
        }

        # Include real-time progress from custom status
        if status.custom_status:
            cs = status.custom_status if isinstance(status.custom_status, dict) else {}
            response_body["processedLeads"] = cs.get("processedLeads", 0)
            response_body["totalLeads"] = cs.get("totalLeads", 0)
            response_body["phase"] = cs.get("phase", "processing")

        # If completed, include output summary
        if runtime_status == "Completed" and status.output:
            response_body["totalLeads"] = status.output.get("totalLeads", 0)
            response_body["outputBlob"] = status.output.get("outputBlob", "")

        # If failed, include error
        if runtime_status == "Failed":
            response_body["error"] = str(status.output) if status.output else "Unknown error"

        return func.HttpResponse(
            json.dumps(response_body),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logger.exception("Status check failed for %s", job_id)
        return func.HttpResponse(
            json.dumps({"error": f"Status check failed: {str(e)}"}),
            status_code=500,
            mimetype="application/json",
        )


# ===========================================================================
# 9. DOWNLOAD — HTTP Trigger
# ===========================================================================
@app.route(route="download/{jobId}", methods=["GET"])
@app.durable_client_input(client_name="client")
async def download_csv(req: func.HttpRequest, client) -> func.HttpResponse:
    """Download the enriched CSV for a completed job."""
    job_id = req.route_params.get("jobId", "")
    if not job_id:
        return func.HttpResponse(
            json.dumps({"error": "Missing jobId"}),
            status_code=400,
            mimetype="application/json",
        )

    try:
        # Verify job is complete
        status = await client.get_status(job_id)
        if status is None:
            return func.HttpResponse(
                json.dumps({"error": "Job not found"}),
                status_code=404,
                mimetype="application/json",
            )

        runtime_status = str(status.runtime_status).split(".")[-1] if status.runtime_status else "Unknown"
        if runtime_status != "Completed":
            return func.HttpResponse(
                json.dumps({"error": f"Job is not yet complete. Current status: {runtime_status}"}),
                status_code=409,
                mimetype="application/json",
            )

        # Stream the file directly
        blob_name = f"{job_id}.csv"
        csv_bytes = _download_blob(OUTPUT_CONTAINER, blob_name)

        return func.HttpResponse(
            csv_bytes,
            status_code=200,
            mimetype="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="emails_{job_id[:8]}.csv"',
            },
        )

    except Exception as e:
        logger.exception("Download failed for %s", job_id)
        return func.HttpResponse(
            json.dumps({"error": f"Download failed: {str(e)}"}),
            status_code=500,
            mimetype="application/json",
        )
