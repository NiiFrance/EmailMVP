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
    build_custom_template,
    MAX_CUSTOM_PROMPT_LENGTH,
)
from csv_processor import (
    parse_csv,
    parse_file,
    dataframe_to_csv_bytes,
    extract_all_leads,
    assemble_enriched_csv,
)
from column_mapper import resolve_columns

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
AZURE_OPENAI_DEPLOYMENT = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-53-chat")
BATCH_SIZE = int(os.environ.get("BATCH_SIZE", "100"))
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
        custom_prompt = req.form.get("custom_prompt", "")

        if prompt_id == "custom":
            if not custom_prompt.strip():
                return func.HttpResponse(
                    json.dumps({"error": "Custom prompt text is required when using the 'custom' template."}),
                    status_code=400,
                    mimetype="application/json",
                )
            try:
                template = build_custom_template(custom_prompt.strip())
            except ValueError as e:
                return func.HttpResponse(
                    json.dumps({"error": str(e)}),
                    status_code=400,
                    mimetype="application/json",
                )
        else:
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
        # For built-in templates, store only the ID. For custom, store the full prompt.
        if prompt_id == "custom":
            template_config = {"id": "custom", "custom_prompt": custom_prompt.strip()}
        else:
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
    if template_id == "custom":
        return build_custom_template(template_config["custom_prompt"])
    return get_template(template_id)


# ===========================================================================
# 4. ACTIVITY — Process a single lead (call GPT 5.3)
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

        # For backward compatibility with cold_email, also include 'emails' key
        result = {"row_index": row_index, "parsed": parsed}
        if template["id"] == "cold_email":
            result["emails"] = parsed

        return result

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

    # For custom templates, discover headers from the first successful result
    if output_headers_fn is None:
        # Find first successful parsed result to discover columns
        from prompt_templates import _custom_output_headers_from_parsed
        for r in results:
            if "parsed" in r:
                output_headers = _custom_output_headers_from_parsed(r["parsed"])
                break
        else:
            output_headers = ["Output"]  # Fallback
    else:
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
# 7. STATUS — HTTP Trigger
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
# 7. DOWNLOAD — HTTP Trigger
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
