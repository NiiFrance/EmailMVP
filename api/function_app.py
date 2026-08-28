"""Azure Functions app — Email MVP with Durable Functions orchestration.

Endpoints:
  POST /api/upload        — Upload CSV, start email generation
  GET  /api/status/{jobId} — Check processing progress
  GET  /api/download/{jobId} — Download enriched CSV
  GET  /api/templates     — List available prompt templates
"""

import asyncio
import html
import json
import logging
import os
import re
import secrets
import uuid
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

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
    invalidate_campaign_cache,
    FIELDS_FIRST_NAME_ONLY,
)
from csv_processor import (
    parse_csv,
    parse_file,
    dataframe_to_csv_bytes,
    extract_all_leads,
    assemble_enriched_csv,
)
from column_mapper import resolve_columns, detect_columns, _friendly_field
from snovio_client import SnovioAPIError, SnovioClient, SnovioConfigError
import data_store
import snovio_mcp
import snovio_policy
import copilot
import time
from snovio_workflows import (
    assess_custom_field_readiness,
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
from snovio_campaigns import (
    build_campaign_payload,
    build_campaign_sequence,
    build_touch_content,
    detect_touch_count,
    map_email_step_contents,
    touch_field_labels,
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
SNOVIO_SESSION_TTL_SECONDS = int(os.environ.get("SNOVIO_SESSION_TTL_SECONDS", "3600"))
SNOVIO_SESSION_ENCRYPTION_KEY = os.environ.get("SNOVIO_SESSION_ENCRYPTION_KEY", "")
SNOVIO_SESSION_CONTAINER = os.environ.get("SNOVIO_SESSION_CONTAINER", "snovio-sessions")
SNOVIO_DEFAULT_DELAY_DAYS = int(os.environ.get("SNOVIO_DEFAULT_DELAY_DAYS", "3"))
SNOVIO_CAMPAIGN_TIMEZONE = os.environ.get("SNOVIO_CAMPAIGN_TIMEZONE", "")
SNOVIO_CAMPAIGN_ARCHIVE_MONTHS = int(os.environ.get("SNOVIO_CAMPAIGN_ARCHIVE_MONTHS", "3"))
SNOVIO_MCP_STATE_TTL_SECONDS = int(os.environ.get("SNOVIO_MCP_STATE_TTL_SECONDS", "600"))
APP_DISPLAY_NAME = os.environ.get("APP_DISPLAY_NAME", "Cloudware Email Campaign Generator").strip()
SNOVIO_WEBHOOK_QUEUE = os.environ.get("SNOVIO_WEBHOOK_QUEUE", "snovio-webhooks")
SNOVIO_SYNC_QUEUE = os.environ.get("SNOVIO_SYNC_QUEUE", "snovio-sync")
COPILOT_REQUESTS_PER_MINUTE = int(os.environ.get("COPILOT_REQUESTS_PER_MINUTE", "10"))
COPILOT_TURN_TTL_SECONDS = int(os.environ.get("COPILOT_TURN_TTL_SECONDS", "180"))
MAX_CSV_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB
MAX_WEBHOOK_SIZE_BYTES = 256 * 1024
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
# Multi-tenant domain allowlist: comma-separated email domains permitted to use
# the app (e.g. "relianceinfosystems.com,cloudware.africa"). Empty = allow all
# (single-tenant behaviour / local dev).
ALLOWED_EMAIL_DOMAINS = {
    d.strip().lower().lstrip("@") for d in os.environ.get("ALLOWED_EMAIL_DOMAINS", "").split(",") if d.strip()
}

logger = logging.getLogger("emailmvp")

DEFAULT_SNOVIO_WEBHOOK_EVENTS = (
    ("campaign_email", "sent"),
    ("campaign_email", "bounced"),
    ("campaign_reply", "received"),
    ("campaign_reply", "autoreply_received"),
    ("campaign_li_reply", "received"),
    ("campaign_li", "connection_request_accepted"),
    ("prospect", "campaign_finished"),
    ("email_verification", "verified"),
)


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


def _blob_exists(container: str, blob_name: str) -> bool:
    try:
        return _blob_service().get_blob_client(container, blob_name).exists()
    except Exception:
        return False


def _json_response(payload: dict | list, status_code: int = 200, headers: dict | None = None) -> func.HttpResponse:
    return func.HttpResponse(json.dumps(payload), status_code=status_code, mimetype="application/json", headers=headers)


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
    # req.params is a read-only Mapping (not a dict) on Azure Functions, so an
    # isinstance(dict) check silently drops every query parameter in production.
    try:
        return dict(params)
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Helper — User identity (SWA Entra ID principal)
# ---------------------------------------------------------------------------
def _client_principal(req: func.HttpRequest) -> dict | None:
    """Parse the x-ms-client-principal header injected by Static Web Apps.

    Trustworthy because the function host only accepts traffic from the linked
    SWA (direct calls are rejected with 401 upstream).
    """
    headers = getattr(req, "headers", {}) or {}
    header = headers.get("x-ms-client-principal", "")
    if not header:
        return None
    try:
        data = json.loads(base64.b64decode(header).decode("utf-8"))
    except Exception:
        return None
    if "authenticated" not in (data.get("userRoles") or []):
        return None
    oid = str(data.get("userId") or "").strip()
    email = str(data.get("userDetails") or "").strip()
    if not oid:
        return None
    name = email
    for claim in data.get("claims") or []:
        if claim.get("typ") in ("name", "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name"):
            name = str(claim.get("val") or name)
            break
    return {"oid": oid, "email": email, "name": name}


def _domain_allowed(email: str) -> bool:
    """True when the email's domain is on the allowlist (empty allowlist = allow all)."""
    if not ALLOWED_EMAIL_DOMAINS:
        return True
    domain = email.lower().rsplit("@", 1)[-1] if "@" in email else ""
    return domain in ALLOWED_EMAIL_DOMAINS


def _require_allowed_domain(req: func.HttpRequest):
    """Multi-tenant gate: 403 when an authenticated caller's domain is not allowlisted.

    Returns an error response to short-circuit with, or None when the request may
    proceed. Requests without a client principal pass through — SWA already blocks
    unauthenticated browser traffic, and webhook callbacks carry no principal.
    """
    principal = _client_principal(req)
    if principal and not _domain_allowed(principal["email"]):
        logger.warning("Domain allowlist rejected %s", principal["email"])
        return _json_response(
            {"error": "Access denied. Your organisation is not authorised to use this application."}, 403
        )
    return None


def _current_user(req: func.HttpRequest) -> dict | None:
    """Return {oid, email, name, role} for the caller, or None when anonymous.

    Role resolution: ADMIN_EMAILS is a permanent floor (bootstrap admins);
    otherwise the Users table value wins, defaulting to "user".
    """
    principal = _client_principal(req)
    if not principal:
        return None
    if not _domain_allowed(principal["email"]):
        return None
    role = "admin" if principal["email"].lower() in ADMIN_EMAILS else "user"
    if role != "admin":
        try:
            row = data_store.get_user(principal["oid"])
            if row and str(row.get("role", "")) == "admin":
                role = "admin"
        except Exception as error:
            logger.warning("User role lookup failed: %s", error)
    principal["role"] = role
    return principal


def _require_user(req: func.HttpRequest):
    """Return (user, None) or (None, 401/403 response)."""
    gate = _require_allowed_domain(req)
    if gate:
        return None, gate
    user = _current_user(req)
    if not user:
        return None, _json_response({"error": "Authentication required."}, 401)
    return user, None


def _require_admin(req: func.HttpRequest):
    """Return (user, None) or (None, 401/403 response)."""
    user, err = _require_user(req)
    if err:
        return None, err
    if user["role"] != "admin":
        return None, _json_response({"error": "Admin role required."}, 403)
    return user, None


def _require_job_owner(req: func.HttpRequest, job_id: str):
    """Return (user-with-job, None) or (None, error response).

    A job belongs to the caller when a Jobs row exists under their oid — point
    lookup, no cross-user scan. Admins may act on ANY job (delegation: running
    campaigns on behalf of other users); the job's real owner oid is preserved
    in user["job"]["ownerOid"]. Unknown/foreign jobs read as 404 (not 403) to
    avoid leaking other users' job ids.
    """
    user, err = _require_user(req)
    if err:
        return None, err
    try:
        job = data_store.get_job(user["oid"], job_id)
        if job:
            job["ownerOid"] = user["oid"]
        elif user.get("role") == "admin":
            job = data_store.find_job(job_id)
    except Exception as error:
        logger.warning("Job ownership lookup failed for %s: %s", job_id, error)
        return None, _json_response({"error": "Job lookup failed."}, 500)
    if not job:
        return None, _json_response({"error": "Job not found."}, 404)
    user["job"] = job
    return user, None


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


def _snovio_configured(req: func.HttpRequest | None = None) -> bool:
    client_id, client_secret, _ = _resolve_snovio_credentials(req)
    return bool(client_id and client_secret)


def _snovio_required_response(req: func.HttpRequest | None = None) -> func.HttpResponse | None:
    if _snovio_configured(req):
        return None
    return _json_response({"configured": False, "error": "Snov.io credentials are not configured."}, 503)


def _snovio_credential_key(client_id: str, client_secret: str) -> str:
    return hashlib.sha256(f"{client_id}\0{client_secret}".encode("utf-8")).hexdigest()


def _build_snovio_client(client_id: str, client_secret: str) -> SnovioClient:
    credential_key = _snovio_credential_key(client_id, client_secret)

    def load_token() -> tuple[str, float] | None:
        try:
            row = data_store.get_snovio_access_token(credential_key)
            if not row:
                return None
            token = _decrypt_session_secret(
                str(row.get("accessToken") or ""), bool(row.get("tokenEncrypted"))
            )
            return token, float(row.get("expiresAt") or 0)
        except Exception as error:
            logger.warning("Shared Snov.io token load failed: %s", type(error).__name__)
            return None

    def save_token(token: str, expires_at: float) -> None:
        try:
            token_value, token_encrypted = _encrypt_session_secret(token)
            data_store.save_snovio_access_token(
                credential_key, token_value, expires_at, token_encrypted
            )
        except Exception as error:
            logger.warning("Shared Snov.io token save failed: %s", type(error).__name__)

    def reserve_rate_slot() -> float:
        try:
            return data_store.reserve_snovio_rate_slot(credential_key, SNOVIO_REQUESTS_PER_MINUTE)
        except Exception as error:
            logger.warning("Shared Snov.io rate reservation failed: %s", type(error).__name__)
            return 0.0

    return SnovioClient(
        client_id=client_id,
        client_secret=client_secret,
        base_url=SNOVIO_API_BASE_URL,
        requests_per_minute=SNOVIO_REQUESTS_PER_MINUTE,
        token_loader=load_token,
        token_saver=save_token,
        rate_reserver=reserve_rate_slot,
    )


def _snovio_client(req: func.HttpRequest | None = None) -> SnovioClient:
    client_id, client_secret, _ = _resolve_snovio_credentials(req)
    return _build_snovio_client(client_id, client_secret)


def _snovio_client_for_oid(oid: str) -> SnovioClient:
    """Build a REST client for a queued operation without browser headers."""
    row = data_store.get_snovio_creds(oid)
    if row:
        client_id = str(row.get("clientId") or "")
        client_secret = _decrypt_session_secret(
            str(row.get("clientSecret") or ""), bool(row.get("secretEncrypted"))
        )
        if client_id and client_secret:
            return _build_snovio_client(client_id, client_secret)
    return _build_snovio_client(SNOVIO_CLIENT_ID, SNOVIO_CLIENT_SECRET)


# ---------------------------------------------------------------------------
# Helper — Snov.io session credentials (secure bring-your-own-key)
# ---------------------------------------------------------------------------
SNOVIO_SESSION_HEADER = "x-snovio-session"


def _snovio_session_blob_name(session_id: str) -> str:
    return f"{session_id}.json"


def _get_session_cipher():
    """Return a Fernet cipher when an encryption key is configured, else None."""
    if not SNOVIO_SESSION_ENCRYPTION_KEY:
        return None
    try:
        from cryptography.fernet import Fernet

        return Fernet(SNOVIO_SESSION_ENCRYPTION_KEY.encode("utf-8"))
    except Exception:
        logger.warning("Invalid SNOVIO_SESSION_ENCRYPTION_KEY; relying on storage encryption at rest only.")
        return None


def _encrypt_session_secret(value: str) -> tuple[str, bool]:
    cipher = _get_session_cipher()
    if not cipher:
        return value, False
    return cipher.encrypt(value.encode("utf-8")).decode("utf-8"), True


def _decrypt_session_secret(value: str, encrypted: bool) -> str:
    if not encrypted:
        return value
    cipher = _get_session_cipher()
    if not cipher:
        raise SnovioConfigError("Session secret is encrypted but no decryption key is configured.")
    return cipher.decrypt(value.encode("utf-8")).decode("utf-8")


def _mask_client_id(client_id: str) -> str:
    if len(client_id) <= 8:
        return "****"
    return f"{client_id[:4]}\u2026{client_id[-4:]}"


def _store_snovio_session(client_id: str, client_secret: str) -> dict:
    session_id = uuid.uuid4().hex
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=SNOVIO_SESSION_TTL_SECONDS)
    encrypted_secret, secret_encrypted = _encrypt_session_secret(client_secret)
    record = {
        "clientId": client_id,
        "clientSecret": encrypted_secret,
        "secretEncrypted": secret_encrypted,
        "createdAt": now.isoformat(),
        "expiresAt": expires_at.isoformat(),
    }
    _upload_blob(SNOVIO_SESSION_CONTAINER, _snovio_session_blob_name(session_id), json.dumps(record).encode("utf-8"))
    return {
        "sessionId": session_id,
        "expiresAt": record["expiresAt"],
        "clientIdMasked": _mask_client_id(client_id),
    }


def _load_snovio_session(session_id: str) -> dict | None:
    if not session_id:
        return None
    try:
        raw = _download_blob(SNOVIO_SESSION_CONTAINER, _snovio_session_blob_name(session_id))
    except Exception:
        return None
    try:
        record = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    expires_at = record.get("expiresAt")
    if expires_at:
        try:
            if datetime.now(timezone.utc) >= datetime.fromisoformat(expires_at):
                _delete_snovio_session(session_id)
                return None
        except ValueError:
            return None
    return record


def _delete_snovio_session(session_id: str) -> None:
    if not session_id:
        return
    try:
        client = _blob_service().get_blob_client(SNOVIO_SESSION_CONTAINER, _snovio_session_blob_name(session_id))
        client.delete_blob()
    except Exception:
        pass


def _session_id_from_request(req: func.HttpRequest | None) -> str:
    if req is None:
        return ""
    headers = getattr(req, "headers", {}) or {}
    return str(headers.get(SNOVIO_SESSION_HEADER, "") or "").strip()


def _resolve_snovio_credentials(req: func.HttpRequest | None) -> tuple[str, str, str]:
    """Resolve Snov.io credentials: session header, then account-saved, then env."""
    session_id = _session_id_from_request(req)
    if session_id:
        record = _load_snovio_session(session_id)
        if record:
            client_id = str(record.get("clientId", ""))
            try:
                client_secret = _decrypt_session_secret(
                    str(record.get("clientSecret", "")), bool(record.get("secretEncrypted"))
                )
            except Exception:
                logger.exception("Failed to decrypt Snov.io session secret.")
                client_secret = ""
            if client_id and client_secret:
                return client_id, client_secret, "session"
    # Account-saved credentials: entered once, remembered per signed-in user.
    principal = _client_principal(req) if req is not None else None
    if principal:
        try:
            row = data_store.get_snovio_creds(principal["oid"])
        except Exception as error:
            logger.warning("Snov.io saved-creds lookup failed: %s", error)
            row = None
        if row:
            client_id = str(row.get("clientId", ""))
            try:
                client_secret = _decrypt_session_secret(
                    str(row.get("clientSecret", "")), bool(row.get("secretEncrypted"))
                )
            except Exception:
                logger.exception("Failed to decrypt saved Snov.io secret.")
                client_secret = ""
            if client_id and client_secret:
                return client_id, client_secret, "account"
    return SNOVIO_CLIENT_ID, SNOVIO_CLIENT_SECRET, "environment"


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
    gate = _require_allowed_domain(req)
    if gate:
        return gate
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
            extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else "unknown"
            logger.warning(
                "Upload parse rejected: extension=%s bytes=%d error_type=%s error=%s",
                extension,
                len(file_bytes),
                type(e).__name__,
                str(e)[:500],
            )
            return func.HttpResponse(
                json.dumps({"error": f"Invalid file: {str(e)}"}),
                status_code=400,
                mimetype="application/json",
            )

        # Smart column detection (non-fatal). The user reviews and corrects the
        # mapping on the next screen before generation actually starts.
        headers = [str(h) for h in df_check.columns.tolist()]
        required_fields = template.get("required_fields")
        detection = None
        if required_fields:
            try:
                openai_client = AzureOpenAI(
                    api_key=AZURE_OPENAI_API_KEY,
                    azure_endpoint=AZURE_OPENAI_ENDPOINT,
                    api_version="2024-12-01-preview",
                )
                detection = detect_columns(
                    headers,
                    client=openai_client,
                    deployment=AZURE_OPENAI_DEPLOYMENT,
                    required_fields=required_fields,
                )
            except Exception as e:
                logger.warning("Column detection failed, returning empty mapping: %s", e)
                detection = {
                    "fields": [
                        {"field": f, "label": _friendly_field(f), "index": None, "derivedFromFullName": False}
                        for f in required_fields
                    ],
                    "unresolved": list(required_fields),
                    "fullNameIndex": None,
                }

        # Normalize every accepted file to UTF-8 CSV once. This prevents later
        # activities from having to reinterpret the user's source encoding.
        csv_bytes = dataframe_to_csv_bytes(df_check)

        job_id = str(uuid.uuid4())
        blob_name = f"{job_id}.csv"

        _upload_blob(INPUT_CONTAINER, blob_name, csv_bytes)
        logger.info("Stored %s (%d leads) as %s [template=%s]", filename, total_leads, blob_name, template["id"])

        # Record the job in the caller's workspace (history + ownership checks).
        # Admins may run a campaign on behalf of another user (delegation): the job
        # is recorded in the TARGET user's workspace with an audit trail.
        user = _current_user(req)
        if user:
            owner_oid = user["oid"]
            extra_fields: dict = {}
            on_behalf_of = str((req.form or {}).get("on_behalf_of") or "").strip().lower()
            if on_behalf_of and on_behalf_of != user["email"].lower():
                if user["role"] != "admin":
                    return func.HttpResponse(
                        json.dumps({"error": "Only admins can run campaigns on behalf of another user."}),
                        status_code=403, mimetype="application/json",
                    )
                target = next((u for u in data_store.list_users() if str(u.get("email", "")).lower() == on_behalf_of), None)
                if not target:
                    return func.HttpResponse(
                        json.dumps({"error": f"No user found with email {on_behalf_of}."}),
                        status_code=404, mimetype="application/json",
                    )
                owner_oid = str(target.get("oid") or target.get("RowKey"))
                extra_fields = {"delegatedBy": user["email"], "delegatedAt": datetime.now(timezone.utc).isoformat()}
                logger.info("Admin %s uploading job %s on behalf of %s", user["email"], job_id, on_behalf_of)
            try:
                data_store.record_job(owner_oid, job_id, {
                    "templateId": template["id"],
                    "templateName": template["name"],
                    "fileName": filename,
                    "totalLeads": total_leads,
                    "status": "uploaded",
                    **extra_fields,
                })
            except Exception as error:
                logger.warning("Job record failed for %s: %s", job_id, error)

        # Build a lightweight column preview: header + first non-empty sample value,
        # so the user can identify columns even when a header is blank/Unnamed.
        columns_preview = []
        for i in range(len(headers)):
            sample = ""
            try:
                for v in df_check.iloc[:, i].tolist():
                    sv = str(v).strip()
                    if sv and sv.lower() != "nan":
                        sample = sv
                        break
            except Exception:
                sample = ""
            columns_preview.append({"index": i, "header": headers[i], "sample": sample[:60]})

        return func.HttpResponse(
            json.dumps({
                "jobId": job_id,
                "totalLeads": total_leads,
                "templateId": template["id"],
                "templateName": template["name"],
                "columns": columns_preview,
                "detection": detection,
                "needsReview": bool(detection and detection.get("unresolved")),
                "statusUrl": f"/api/status/{job_id}",
                "downloadUrl": f"/api/download/{job_id}",
            }),
            status_code=200,
            mimetype="application/json",
        )

    except Exception as e:
        logger.exception("Upload failed")
        return func.HttpResponse(
            json.dumps({"error": f"Upload failed: {str(e)}"}),
            status_code=500,
            mimetype="application/json",
        )


def _build_column_map(raw_map: dict, required_fields: dict) -> tuple[dict | None, list]:
    """Turn the frontend's chosen mapping into a column_map for extraction.

    Accepts per-field column indices, or the string ``"full:<idx>"`` to derive a
    name field from a Full Name column. Returns ``(column_map, missing_labels)``;
    when ``missing_labels`` is non-empty the caller should reject the request.
    """
    column_map: dict = {}
    full_name_idx = None

    def _as_index(value):
        if isinstance(value, str) and value.startswith("full:"):
            return None  # handled separately
        try:
            idx = int(value)
        except (TypeError, ValueError):
            return None
        return idx if idx >= 0 else None

    for field in required_fields:
        value = raw_map.get(field)
        if isinstance(value, str) and value.startswith("full:"):
            try:
                full_name_idx = int(value.split(":", 1)[1])
            except (ValueError, IndexError):
                pass
            continue
        idx = _as_index(value)
        if idx is not None:
            column_map[field] = idx

    # Explicit full_name override (e.g., both name fields share one column).
    explicit_full = _as_index(raw_map.get("full_name"))
    if full_name_idx is None and explicit_full is not None:
        full_name_idx = explicit_full

    # Same column chosen for both first and last name => it's a Full Name column.
    if (
        column_map.get("first_name") is not None
        and column_map.get("first_name") == column_map.get("last_name")
    ):
        full_name_idx = column_map.pop("first_name")
        column_map.pop("last_name", None)

    if full_name_idx is not None:
        column_map["full_name"] = full_name_idx

    missing = []
    for field in required_fields:
        if field in column_map:
            continue
        if field in ("first_name", "last_name") and "full_name" in column_map:
            continue
        missing.append(_friendly_field(field))

    return (column_map or None), missing


@app.route(route="generate", methods=["POST"])
@app.durable_client_input(client_name="client")
async def generate_emails(req: func.HttpRequest, client) -> func.HttpResponse:
    """Start generation for an already-uploaded job using a confirmed column mapping."""
    try:
        try:
            body = req.get_json()
        except ValueError:
            return func.HttpResponse(
                json.dumps({"error": "Invalid JSON body."}), status_code=400, mimetype="application/json"
            )

        job_id = str(body.get("jobId") or "").strip()
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", job_id):
            return func.HttpResponse(
                json.dumps({"error": "A valid jobId from /api/upload is required."}),
                status_code=400, mimetype="application/json",
            )

        prompt_id = body.get("promptId") or body.get("prompt_id") or "cold_email"
        try:
            template = get_template(prompt_id)
        except KeyError:
            return func.HttpResponse(
                json.dumps({"error": f"Unknown template: {prompt_id}."}),
                status_code=400, mimetype="application/json",
            )

        # Only the job's owner may start generation for it.
        user, err = _require_job_owner(req, job_id)
        if err:
            return err

        # Confirm the uploaded file still exists before starting work.
        if not _blob_exists(INPUT_CONTAINER, f"{job_id}.csv"):
            return func.HttpResponse(
                json.dumps({"error": "Uploaded file not found — please upload again."}),
                status_code=404, mimetype="application/json",
            )

        column_map = None
        required_fields = template.get("required_fields")
        if required_fields:
            column_map, missing = _build_column_map(body.get("columnMap") or {}, required_fields)
            if missing:
                return func.HttpResponse(
                    json.dumps({"error": "Please choose a column for: " + ", ".join(missing) + "."}),
                    status_code=400, mimetype="application/json",
                )

        orchestrator_input = {
            "job_id": job_id,
            "column_map": column_map,
            "template_config": {"id": prompt_id},
        }
        await client.start_new("orchestrate_emails", client_input=orchestrator_input, instance_id=job_id)
        logger.info("Started generation for %s [template=%s, map=%s]", job_id, template["id"], column_map)
        try:
            data_store.update_job(user["job"].get("ownerOid", user["oid"]), job_id, {
                "status": "generating",
                "templateId": template["id"],
                "templateName": template["name"],
                "startedAt": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as error:
            logger.warning("Job update failed for %s: %s", job_id, error)

        return func.HttpResponse(
            json.dumps({
                "jobId": job_id,
                "totalLeads": body.get("totalLeads"),
                "statusUrl": f"/api/status/{job_id}",
                "downloadUrl": f"/api/download/{job_id}",
            }),
            status_code=202,
            mimetype="application/json",
        )
    except Exception as e:
        logger.exception("Generate failed")
        return func.HttpResponse(
            json.dumps({"error": f"Could not start generation: {str(e)}"}),
            status_code=500, mimetype="application/json",
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
# Helper — Suggest campaigns whose required columns a file can satisfy
# ===========================================================================
def _compatible_template_names(headers: list, exclude_id: str | None = None) -> list:
    """Return names of templates whose required columns resolve from these headers.

    Uses fuzzy + full-name matching only (no LLM) so it is fast and side-effect free.
    """
    names = []
    for tpl in PROMPT_REGISTRY.values():
        if tpl.get("id") == exclude_id:
            continue
        required = tpl.get("required_fields")
        if not required:
            continue
        try:
            resolve_columns(headers, client=None, deployment="", required_fields=required)
            names.append(tpl["name"])
        except ValueError:
            continue
    return names


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
        parse_response = template["parse_response"]

        # Learning loop: inject performance guidance distilled from live Snov.io
        # engagement (replies/sentiment) for this template, when available.
        system_prompt = template["system_prompt"]
        try:
            guidance_row = data_store.get_template_guidance(template["id"])
            guidance_text = str(guidance_row.get("guidance") or "") if isinstance(guidance_row, dict) else ""
            if guidance_text.strip():
                system_prompt = (
                    f"{system_prompt}\n\nPERFORMANCE GUIDANCE (derived from real engagement "
                    f"data for this campaign type — follow unless it conflicts with the rules above):\n"
                    f"{guidance_text.strip()[:1500]}"
                )
        except Exception as guidance_error:
            logger.debug("Guidance lookup skipped for %s: %s", template["id"], guidance_error)

        # gpt-5.x "mini" deployments are reasoning models: hidden reasoning tokens
        # count against max_completion_tokens, so a low cap can truncate output and
        # yield too few emails ("Expected N emails, got M"). Use a generous budget and
        # retry a few times, since occasional non-compliance is expected from the model.
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        max_attempts = 3
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            attempt_messages = list(messages)
            if attempt > 1 and last_error is not None:
                # Nudge the model to fix the exact problem from the previous attempt.
                attempt_messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous response was not valid: {str(last_error)[:300]}. "
                        "Return ONLY a JSON array containing exactly the required number of "
                        "email objects, each with a \"subject\" and \"body\" key. "
                        "No prose, no markdown fences."
                    ),
                })

            completion = client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=attempt_messages,
                max_completion_tokens=32768,
            )
            choice = completion.choices[0]
            response_text = choice.message.content or ""
            finish_reason = getattr(choice, "finish_reason", None)

            if finish_reason == "length" and not response_text.strip():
                last_error = ValueError("Model output was truncated before any content was returned.")
                logger.warning("Lead %d attempt %d truncated (finish_reason=length)", row_index, attempt)
                continue

            try:
                parsed = parse_response(response_text)
                if attempt > 1:
                    logger.info("Lead %d recovered on attempt %d", row_index, attempt)
                logger.info("Successfully generated content for lead %d [template=%s]", row_index, template["id"])
                return {"row_index": row_index, "parsed": parsed}
            except (ValueError, json.JSONDecodeError) as parse_error:
                last_error = parse_error
                logger.warning("Lead %d attempt %d parse failed: %s", row_index, attempt, str(parse_error))

        # All attempts exhausted.
        if isinstance(last_error, json.JSONDecodeError):
            message = f"Invalid JSON from model: {last_error}"
        elif last_error is not None:
            message = str(last_error)
        else:
            message = "Generation failed after multiple attempts."
        logger.error("Lead %d failed after %d attempts: %s", row_index, max_attempts, message)
        return {"row_index": row_index, "error": message}

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
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    templates = list_templates()
    return func.HttpResponse(
        json.dumps({"templates": templates}),
        status_code=200,
        mimetype="application/json",
    )


# ===========================================================================
# 6b. IDENTITY — current user, saved context, and admin user management
# ===========================================================================
@app.route(route="me", methods=["GET"])
async def get_me(req: func.HttpRequest) -> func.HttpResponse:
    """Return the signed-in user's identity, role, and saved context."""
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    user = _current_user(req)
    if not user:
        return _json_response({"error": "Not authenticated."}, 401)
    last_context = None
    try:
        row = data_store.upsert_user(user["oid"], user["email"], user["name"], user["role"])
        raw_context = row.get("lastContext")
        if raw_context:
            last_context = json.loads(raw_context)
    except Exception as error:
        logger.warning("User upsert failed for %s: %s", user["email"], error)
    return _json_response({
        "oid": user["oid"],
        "email": user["email"],
        "name": user["name"],
        "role": user["role"],
        "lastContext": last_context,
    })


@app.route(route="me/context", methods=["PUT"])
async def put_me_context(req: func.HttpRequest) -> func.HttpResponse:
    """Persist the user's resume context (current step / job / template)."""
    user, err = _require_user(req)
    if err:
        return err
    payload = _request_json(req)
    context = {
        "step": str(payload.get("step") or ""),
        "jobId": str(payload.get("jobId") or ""),
        "templateId": str(payload.get("templateId") or ""),
        "savedAt": datetime.now(timezone.utc).isoformat(),
    }
    try:
        data_store.set_user_context(user["oid"], context)
    except Exception as error:
        logger.warning("Context save failed for %s: %s", user["email"], error)
        return _json_response({"error": "Could not save context."}, 500)
    return _json_response({"saved": True})


@app.route(route="jobs/{jobId}/drafts", methods=["PUT"])
async def put_job_drafts(req: func.HttpRequest) -> func.HttpResponse:
    """Persist review-step edits to the job's generated CSV (owner only).

    Body: {"edits": [{"email": "...", "touches": [{"subject": "...", "body": "..."}, ...]}]}
    Rewrites the Subject_Touch{n}/Body_Touch{n} columns for matching leads so the
    Snov.io sync (which reads the output CSV) pushes what the user reviewed.
    """
    job_id = req.route_params.get("jobId", "")
    _, err = _require_job_owner(req, job_id)
    if err:
        return err
    payload = _request_json(req)
    edits = payload.get("edits")
    if not isinstance(edits, list) or not edits:
        return _json_response({"error": "edits array is required."}, 400)
    try:
        dataframe = parse_csv(_download_job_csv(job_id))
    except Exception:
        return _json_response({"error": "Job output not found."}, 404)

    rows, _columns = build_job_rows(dataframe)
    email_to_index = {r["email"].lower(): r["rowIndex"] for r in rows if r.get("email")}
    header_lookup = {str(c).lower(): c for c in dataframe.columns}
    updated = 0
    for edit in edits:
        email = str(edit.get("email") or "").strip().lower()
        row_index = email_to_index.get(email)
        if row_index is None:
            continue
        changed = False
        for touch_number, touch in enumerate(edit.get("touches") or [], start=1):
            if not isinstance(touch, dict):
                continue
            for prefix, key in (("subject_touch", "subject"), ("body_touch", "body")):
                if key not in touch:
                    continue
                column = header_lookup.get(f"{prefix}{touch_number}")
                if column is None:
                    continue
                dataframe.iloc[row_index, dataframe.columns.get_loc(column)] = str(touch.get(key) or "")
                changed = True
        if changed:
            updated += 1

    _upload_blob(OUTPUT_CONTAINER, f"{job_id}.csv", dataframe_to_csv_bytes(dataframe))
    return _json_response({"saved": True, "updatedLeads": updated})


@app.route(route="users", methods=["GET"])
async def get_users(req: func.HttpRequest) -> func.HttpResponse:
    """Admin: list all users and their roles."""
    _, err = _require_admin(req)
    if err:
        return err
    try:
        users = data_store.list_users()
    except Exception as error:
        logger.warning("User list failed: %s", error)
        return _json_response({"error": "Could not list users."}, 500)
    return _json_response({"users": [
        {
            "oid": u.get("RowKey"),
            "email": u.get("email", ""),
            "name": u.get("name", ""),
            "role": u.get("role", "user"),
            "bootstrapAdmin": str(u.get("email", "")).lower() in ADMIN_EMAILS,
            "lastLoginAt": u.get("lastLoginAt", ""),
        }
        for u in users
    ]})


@app.route(route="users/{oid}/role", methods=["PUT"])
async def put_user_role(req: func.HttpRequest) -> func.HttpResponse:
    """Admin: promote or demote a user."""
    admin, err = _require_admin(req)
    if err:
        return err
    oid = req.route_params.get("oid", "")
    role = str(_request_json(req).get("role") or "").strip().lower()
    if role not in ("admin", "user"):
        return _json_response({"error": "role must be 'admin' or 'user'."}, 400)
    target = data_store.get_user(oid)
    if not target:
        return _json_response({"error": "User not found."}, 404)
    if str(target.get("email", "")).lower() in ADMIN_EMAILS and role != "admin":
        return _json_response({"error": "This user is a bootstrap admin (ADMIN_EMAILS) and cannot be demoted here."}, 400)
    if admin["oid"] == oid and role != "admin":
        return _json_response({"error": "You cannot demote yourself."}, 400)
    data_store.set_user_role(oid, role)
    logger.info("Role change: %s set %s to %s", admin["email"], target.get("email"), role)
    return _json_response({"oid": oid, "role": role})


@app.route(route="jobs", methods=["GET"])
async def list_my_jobs(req: func.HttpRequest) -> func.HttpResponse:
    """Return the caller's job history (their workspace)."""
    user, err = _require_user(req)
    if err:
        return err
    archived = _parse_bool(_query_params(req).get("archived"), default=False)
    try:
        jobs = data_store.list_jobs(user["oid"], limit=25, archived=archived)
        archived_count = data_store.count_jobs(user["oid"], archived=True)
    except Exception as error:
        logger.warning("Job list failed for %s: %s", user["email"], error)
        return _json_response({"error": "Could not load your campaigns."}, 500)
    return _json_response({"archivedCount": archived_count, "jobs": [
        {
            "jobId": j.get("RowKey"),
            "templateId": j.get("templateId", ""),
            "templateName": j.get("templateName", ""),
            "fileName": j.get("fileName", ""),
            "totalLeads": int(j.get("totalLeads", 0) or 0),
            "status": j.get("status", ""),
            "createdAt": j.get("createdAt", ""),
            "completedAt": j.get("completedAt", ""),
            "archived": bool(j.get("archived")),
        }
        for j in jobs
    ]})


def _owned_job_for_history(req: func.HttpRequest, job_id: str):
    """Resolve only the caller's own history row, even when the caller is an admin."""
    user, error = _require_user(req)
    if error:
        return None, None, error
    try:
        job = data_store.get_job(user["oid"], job_id)
    except Exception as lookup_error:
        logger.warning("Job history lookup failed for %s: %s", job_id, lookup_error)
        return None, None, _json_response({"error": "Job lookup failed."}, 500)
    if not job:
        return None, None, _json_response({"error": "Campaign not found."}, 404)
    return user, job, None


@app.route(route="jobs/{jobId}", methods=["DELETE"])
async def archive_job_history(req: func.HttpRequest) -> func.HttpResponse:
    """Hide a drafted or failed job from the caller's workspace history."""
    job_id = str((req.route_params or {}).get("jobId") or "")
    user, job, error = _owned_job_for_history(req, job_id)
    if error:
        return error
    status = str(job.get("status") or "")
    if status not in {"Completed", "Failed"}:
        return _json_response({
            "error": "Only Drafted or Failed campaigns can be removed from your workspace.",
            "status": status,
        }, 409)
    try:
        data_store.set_job_archived(user["oid"], job_id, True)
    except Exception as archive_error:
        logger.warning("Job archive failed for %s: %s", job_id, archive_error)
        return _json_response({"error": "Could not remove this campaign from your workspace."}, 500)
    try:
        user_row = data_store.get_user(user["oid"])
        raw_context = str((user_row or {}).get("lastContext") or "")
        context = json.loads(raw_context) if raw_context else {}
        if isinstance(context, dict) and str(context.get("jobId") or "") == job_id:
            data_store.set_user_context(user["oid"], {})
    except Exception as context_error:
        logger.warning("Archived job %s but could not clear resume context: %s", job_id, context_error)
    return _json_response({"jobId": job_id, "archived": True})


@app.route(route="jobs/{jobId}", methods=["PUT"])
async def restore_job_history(req: func.HttpRequest) -> func.HttpResponse:
    """Restore an archived job to the caller's workspace history."""
    if _request_json(req).get("archived") is not False:
        return _json_response({"error": "archived must be false to restore a campaign."}, 400)
    job_id = str((req.route_params or {}).get("jobId") or "")
    user, _job, error = _owned_job_for_history(req, job_id)
    if error:
        return error
    try:
        data_store.set_job_archived(user["oid"], job_id, False)
    except Exception as restore_error:
        logger.warning("Job restore failed for %s: %s", job_id, restore_error)
        return _json_response({"error": "Could not restore this campaign."}, 500)
    return _json_response({"jobId": job_id, "archived": False})


# ===========================================================================
# 6c. CAMPAIGNS — admin-editable template registry
# ===========================================================================
def _campaign_public(row: dict, full: bool = False) -> dict:
    payload = {
        "id": row.get("RowKey"),
        "name": row.get("name", ""),
        "group": row.get("group", "Custom"),
        "description": row.get("description", ""),
        "numEmails": int(row.get("numEmails", 1) or 1),
        "builtin": bool(row.get("builtin")),
        "archived": bool(row.get("archived")),
    }
    if full:
        payload["systemPrompt"] = row.get("systemPrompt", "")
        payload["updatedBy"] = row.get("updatedBy", "")
        payload["updatedAt"] = row.get("updatedAt", "")
    return payload


def _validate_campaign_payload(payload: dict, partial: bool = False) -> tuple[dict, str]:
    """Validate/normalize campaign fields. Returns (fields, error_message)."""
    fields: dict = {}
    if "name" in payload or not partial:
        name = str(payload.get("name") or "").strip()
        if not name:
            return {}, "A campaign name is required."
        fields["name"] = name[:120]
    if "group" in payload or not partial:
        fields["group"] = (str(payload.get("group") or "Custom").strip() or "Custom")[:60]
    if "description" in payload:
        fields["description"] = str(payload.get("description") or "").strip()[:500]
    if "numEmails" in payload or not partial:
        try:
            num = int(payload.get("numEmails", 1))
        except (TypeError, ValueError):
            return {}, "numEmails must be a number."
        if not 1 <= num <= 12:
            return {}, "numEmails must be between 1 and 12."
        fields["numEmails"] = num
    if "systemPrompt" in payload or not partial:
        prompt = str(payload.get("systemPrompt") or "").strip()
        if not prompt:
            return {}, "A system prompt is required."
        if len(prompt) > 60000:
            return {}, "The system prompt is too long (60,000 character limit)."
        fields["systemPrompt"] = prompt
    if "archived" in payload:
        fields["archived"] = bool(payload.get("archived"))
    return fields, ""


@app.route(route="campaigns", methods=["GET"])
async def list_campaigns_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """List campaigns. Admins may pass ?full=true for prompts + archived ones."""
    user, err = _require_user(req)
    if err:
        return err
    full = _parse_bool(_query_params(req).get("full"), default=False) and user["role"] == "admin"
    try:
        rows = data_store.list_campaign_entities(include_archived=full)
    except Exception as error:
        logger.warning("Campaign list failed: %s", error)
        return _json_response({"error": "Could not load campaigns."}, 500)
    return _json_response({"campaigns": [_campaign_public(r, full=full) for r in rows]})


@app.route(route="campaigns", methods=["POST"])
async def create_campaign_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Admin: create a new campaign."""
    admin, err = _require_admin(req)
    if err:
        return err
    fields, message = _validate_campaign_payload(_request_json(req), partial=False)
    if message:
        return _json_response({"error": message}, 400)

    base_id = re.sub(r"[^a-z0-9]+", "_", fields["name"].lower()).strip("_") or "campaign"
    campaign_id = base_id
    suffix = 2
    while data_store.get_campaign_entity(campaign_id) is not None or campaign_id in PROMPT_REGISTRY:
        campaign_id = f"{base_id}_{suffix}"
        suffix += 1

    fields.update({
        "requiredFields": json.dumps(FIELDS_FIRST_NAME_ONLY),
        "builtin": False,
        "archived": False,
        "updatedBy": admin["email"],
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    })
    fields.setdefault("description", "")
    data_store.upsert_campaign_entity(campaign_id, fields)
    invalidate_campaign_cache()
    logger.info("Campaign created: %s by %s", campaign_id, admin["email"])
    row = data_store.get_campaign_entity(campaign_id) or {"RowKey": campaign_id, **fields}
    return _json_response(_campaign_public(row, full=True), 201)


@app.route(route="campaigns/{campaignId}", methods=["PUT"])
async def update_campaign_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Admin: update or archive/restore a campaign."""
    admin, err = _require_admin(req)
    if err:
        return err
    campaign_id = req.route_params.get("campaignId", "")
    existing = data_store.get_campaign_entity(campaign_id)
    if not existing:
        return _json_response({"error": "Campaign not found."}, 404)
    fields, message = _validate_campaign_payload(_request_json(req), partial=True)
    if message:
        return _json_response({"error": message}, 400)
    if not fields:
        return _json_response({"error": "Nothing to update."}, 400)
    fields["updatedBy"] = admin["email"]
    fields["updatedAt"] = datetime.now(timezone.utc).isoformat()
    data_store.upsert_campaign_entity(campaign_id, fields)
    invalidate_campaign_cache()
    logger.info("Campaign updated: %s by %s (%s)", campaign_id, admin["email"], ", ".join(fields.keys()))
    row = data_store.get_campaign_entity(campaign_id)
    return _json_response(_campaign_public(row, full=True))


@app.route(route="campaigns/{campaignId}", methods=["DELETE"])
async def archive_campaign_endpoint(req: func.HttpRequest) -> func.HttpResponse:
    """Admin: archive a campaign (soft delete — it disappears from pickers)."""
    admin, err = _require_admin(req)
    if err:
        return err
    campaign_id = req.route_params.get("campaignId", "")
    existing = data_store.get_campaign_entity(campaign_id)
    if not existing:
        return _json_response({"error": "Campaign not found."}, 404)
    data_store.upsert_campaign_entity(campaign_id, {
        "archived": True,
        "updatedBy": admin["email"],
        "updatedAt": datetime.now(timezone.utc).isoformat(),
    })
    invalidate_campaign_cache()
    logger.info("Campaign archived: %s by %s", campaign_id, admin["email"])
    return _json_response({"id": campaign_id, "archived": True})


# ===========================================================================
# 7. SNOV.IO — HTTP Triggers (configuration and balance preflight)
# ===========================================================================
@app.route(route="snovio/status", methods=["GET"])
async def get_snovio_status(req: func.HttpRequest) -> func.HttpResponse:
    """Return Snov.io integration status without exposing secrets."""
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    resolved_id, _, source = _resolve_snovio_credentials(req)
    session_record = _load_snovio_session(_session_id_from_request(req))
    connected = bool(session_record) or source == "account"
    return _json_response({
        "configured": _snovio_configured(req),
        "credentialSource": source,
        "sessionActive": connected,
        "sessionExpiresAt": session_record.get("expiresAt") if session_record else None,
        "sessionClientIdMasked": _mask_client_id(str(session_record.get("clientId", ""))) if session_record else (_mask_client_id(resolved_id) if source == "account" else None),
        "environmentConfigured": bool(SNOVIO_CLIENT_ID and SNOVIO_CLIENT_SECRET),
        "apiBaseUrl": SNOVIO_API_BASE_URL,
        "rateLimitPerMinute": SNOVIO_REQUESTS_PER_MINUTE,
        "allowUnknownVerification": SNOVIO_ALLOW_UNKNOWN_VERIFICATION,
        "webhookSecretConfigured": bool(SNOVIO_WEBHOOK_SECRET),
        "templateMappingsConfigured": bool(_parse_template_mappings()),
    })


@app.route(route="snovio/session", methods=["POST"])
async def create_snovio_session(req: func.HttpRequest) -> func.HttpResponse:
    """Validate user-supplied Snov.io credentials and open a secure server-side session.

    The client_id/client_secret are validated against Snov.io, then stored server-side
    (encrypted at rest) under an opaque session id. The secret is never returned to the
    browser and never logged. The caller receives only the opaque session id, which it
    sends back via the X-Snovio-Session header on subsequent requests.
    """
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    payload = _request_json(req)
    client_id = str(payload.get("clientId") or payload.get("client_id") or "").strip()
    client_secret = str(payload.get("clientSecret") or payload.get("client_secret") or "").strip()
    if not client_id or not client_secret:
        return _json_response({"error": "clientId and clientSecret are required."}, 400)

    probe = SnovioClient(
        client_id=client_id,
        client_secret=client_secret,
        base_url=SNOVIO_API_BASE_URL,
        requests_per_minute=SNOVIO_REQUESTS_PER_MINUTE,
    )
    try:
        probe.get_access_token()
        balance = probe.get_balance()
    except SnovioConfigError as error:
        return _json_response({"error": str(error)}, 400)
    except SnovioAPIError as error:
        return _json_response({"error": "Snov.io rejected the supplied credentials.", "statusCode": error.status_code}, 401)
    except Exception:
        logger.exception("Snov.io session validation failed.")
        return _json_response({"error": "Unable to validate Snov.io credentials."}, 502)

    session = _store_snovio_session(client_id, client_secret)

    # Remember for the signed-in user (opt-out via remember=false) so future
    # logins auto-connect without re-entering keys.
    remembered = False
    if _parse_bool(payload.get("remember"), default=True):
        principal = _client_principal(req)
        if principal:
            try:
                secret_value, secret_encrypted = _encrypt_session_secret(client_secret)
                data_store.save_snovio_creds(principal["oid"], client_id, secret_value, secret_encrypted)
                remembered = True
            except Exception as error:
                logger.warning("Saving Snov.io creds failed for %s: %s", principal.get("email"), error)

    return _json_response({
        "configured": True,
        "sessionId": session["sessionId"],
        "expiresAt": session["expiresAt"],
        "clientIdMasked": session["clientIdMasked"],
        "remembered": remembered,
        "balance": balance,
    }, 201)


@app.route(route="snovio/session", methods=["DELETE"])
async def delete_snovio_session(req: func.HttpRequest) -> func.HttpResponse:
    """Close the Snov.io session and forget any account-saved credentials."""
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    session_id = _session_id_from_request(req)
    _delete_snovio_session(session_id)
    principal = _client_principal(req)
    if principal:
        try:
            data_store.delete_snovio_creds(principal["oid"])
        except Exception as error:
            logger.warning("Deleting saved Snov.io creds failed: %s", error)
    return _json_response({"closed": True})


# ===========================================================================
# Snov.io MCP — OAuth connect (no API keys) + tool access for the copilot
# ===========================================================================
def _public_origin(req: func.HttpRequest) -> str:
    """Origin the user's browser sees (the SWA host, not the function host)."""
    configured = os.environ.get("PUBLIC_APP_ORIGIN", "").strip().rstrip("/")
    if configured:
        return configured
    headers = getattr(req, "headers", {}) or {}
    host = headers.get("x-forwarded-host") or headers.get("host") or ""
    return f"https://{host}" if host else ""


def _mcp_redirect_uri(req: func.HttpRequest) -> str:
    return f"{_public_origin(req)}/api/snovio/mcp/callback"


def _mcp_client_id(req: func.HttpRequest) -> str:
    """Return the OAuth client id for this host, registering once if needed."""
    redirect_uri = _mcp_redirect_uri(req)
    host = redirect_uri.split("/")[2] if "://" in redirect_uri else redirect_uri
    row = data_store.get_mcp_client_registration(host)
    if row and row.get("clientId") and row.get("redirectUri") == redirect_uri:
        return str(row["clientId"])
    client_id = snovio_mcp.register_client(APP_DISPLAY_NAME, redirect_uri)
    data_store.save_mcp_client_registration(host, client_id, redirect_uri)
    return client_id


def _mcp_state_expired(row: dict) -> bool:
    created_at = str(row.get("createdAt") or "")
    if not created_at:
        return True
    try:
        created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return datetime.now(timezone.utc) - created > timedelta(seconds=SNOVIO_MCP_STATE_TTL_SECONDS)


def _store_mcp_tokens(oid: str, payload: dict, client_id: str) -> None:
    access_token = str(payload.get("access_token") or "")
    refresh_token = str(payload.get("refresh_token") or "")
    expires_at = time.time() + int(payload.get("expires_in", 3600) or 3600)
    enc_access, encrypted = _encrypt_session_secret(access_token)
    enc_refresh, _ = _encrypt_session_secret(refresh_token) if refresh_token else ("", encrypted)
    data_store.save_mcp_tokens(oid, enc_access, enc_refresh, expires_at, encrypted, client_id=client_id)


def _get_valid_mcp_token(oid: str) -> str | None:
    """Return a decrypted, unexpired MCP access token (refreshing if possible)."""
    row = data_store.get_mcp_tokens(oid)
    if not row:
        return None
    encrypted = bool(row.get("tokensEncrypted"))
    try:
        access_token = _decrypt_session_secret(str(row.get("accessToken") or ""), encrypted)
        refresh_token = _decrypt_session_secret(str(row.get("refreshToken") or ""), encrypted) if row.get("refreshToken") else ""
    except Exception:
        logger.exception("MCP token decryption failed for %s", oid)
        return None
    expires_at = float(row.get("expiresAt") or 0)
    if time.time() < expires_at - 60:
        return access_token
    client_id = str(row.get("clientId") or "")
    if not refresh_token or not client_id:
        return None
    try:
        refreshed = snovio_mcp.refresh_tokens(client_id, refresh_token)
        _store_mcp_tokens(oid, refreshed, client_id)
        return str(refreshed.get("access_token"))
    except Exception as error:
        logger.warning("MCP token refresh failed for %s: %s", oid, error)
        return None


@app.route(route="snovio/mcp/connect", methods=["GET"])
async def snovio_mcp_connect(req: func.HttpRequest) -> func.HttpResponse:
    """Begin the Snov.io MCP OAuth flow; returns the authorize URL."""
    user, err = _require_user(req)
    if err:
        return err
    try:
        client_id = _mcp_client_id(req)
        redirect_uri = _mcp_redirect_uri(req)
        verifier, challenge = snovio_mcp.make_pkce_pair()
        state = uuid.uuid4().hex
        data_store.save_mcp_state(state, user["oid"], verifier, redirect_uri, client_id)
        url = snovio_mcp.build_authorize_url(client_id, redirect_uri, state, challenge)
        return _json_response({"authorizeUrl": url})
    except Exception as error:
        logger.exception("MCP connect failed")
        return _json_response({"error": f"Could not start Snov.io connection: {error}"}, 502)


@app.route(route="snovio/mcp/callback", methods=["GET"])
async def snovio_mcp_callback(req: func.HttpRequest) -> func.HttpResponse:
    """OAuth redirect target: exchange the code, store tokens, close the tab.

    This route is reachable anonymously: SWA's auth cookie is SameSite=Strict, so
    the cross-site redirect from Snov.io arrives without a session. The user is
    bound through the single-use, unguessable ``state`` value created at connect
    time (which records the initiating user's oid).
    """
    params = _query_params(req)
    state = params.get("state", "")
    code = params.get("code", "")
    oauth_error = params.get("error", "")

    def _page(message: str, ok: bool) -> func.HttpResponse:
        color = "#1a7f37" if ok else "#b10e20"
        safe_message = html.escape(message, quote=True)
        target_origin = json.dumps(_public_origin(req)).replace("</", "<\\/")
        page_html = (
            "<!DOCTYPE html><html><head><title>Snov.io connection</title></head>"
            "<body style=\"font-family:system-ui;display:flex;align-items:center;justify-content:center;height:90vh;\">"
            f"<div style=\"text-align:center;\"><h2 style=\"color:{color};\">{safe_message}</h2>"
            "<p>You can close this tab and return to the app.</p>"
            f"<script>try{{if(window.opener){{window.opener.postMessage({{snovioMcp:'done'}},{target_origin});}}}}catch(e){{}}</script>"
            "</div></body></html>"
        )
        return func.HttpResponse(page_html, status_code=200, mimetype="text/html")

    if oauth_error:
        return _page(f"Connection cancelled ({oauth_error}).", ok=False)
    if not state or not code:
        return _page("Missing code or state in the callback.", ok=False)
    row = data_store.pop_mcp_state(state)
    if not row:
        return _page("This connection link expired — please retry from the app.", ok=False)
    oid = str(row.get("oid") or "")
    if not oid:
        return _page("This connection request is malformed — please retry from the app.", ok=False)
    if _mcp_state_expired(row):
        return _page("This connection link expired — please retry from the app.", ok=False)
    try:
        tokens = snovio_mcp.exchange_code(
            str(row.get("clientId")), str(row.get("redirectUri")), code, str(row.get("codeVerifier"))
        )
        _store_mcp_tokens(oid, tokens, str(row.get("clientId")))
        return _page("Snov.io connected \u2713", ok=True)
    except Exception as error:
        logger.exception("MCP code exchange failed")
        return _page(f"Connection failed: {error}", ok=False)


@app.route(route="snovio/mcp/status", methods=["GET"])
async def snovio_mcp_status(req: func.HttpRequest) -> func.HttpResponse:
    """Report whether the signed-in user has a working MCP connection."""
    user, err = _require_user(req)
    if err:
        return err
    token = _get_valid_mcp_token(user["oid"])
    return _json_response({"connected": bool(token)})


@app.route(route="snovio/mcp/disconnect", methods=["POST"])
async def snovio_mcp_disconnect(req: func.HttpRequest) -> func.HttpResponse:
    """Forget the signed-in user's MCP tokens."""
    user, err = _require_user(req)
    if err:
        return err
    data_store.delete_mcp_tokens(user["oid"])
    return _json_response({"disconnected": True})


@app.route(route="snovio/mcp/tools", methods=["GET"])
async def snovio_mcp_tools(req: func.HttpRequest) -> func.HttpResponse:
    """List the MCP tools available to the connected user (also used by the copilot)."""
    user, err = _require_user(req)
    if err:
        return err
    token = _get_valid_mcp_token(user["oid"])
    if not token:
        return _json_response({"error": "Snov.io is not connected. Use Connect Snov.io first."}, 409)
    try:
        session = snovio_mcp.SnovioMCPSession(token, APP_DISPLAY_NAME)
        tools = session.list_tools()
        return _json_response({
            "count": len(tools),
            "tools": [
                {"name": t.get("name"), "description": (t.get("description") or "")[:300],
                 "inputSchema": t.get("inputSchema")}
                for t in tools
            ],
        })
    except snovio_mcp.SnovioMCPError as error:
        return _json_response({"error": str(error)}, 502)


# ===========================================================================
# Lead sourcing — find prospects in Snov.io's database (via the user's MCP login)
# ===========================================================================
@app.route(route="snovio/search-leads", methods=["POST"])
async def snovio_search_leads(req: func.HttpRequest) -> func.HttpResponse:
    """Turn a plain-language description into Snov.io database-search results.

    Body: {"prompt": "...", "page": 1} or {"taskId": 123, "page": 2}.
    Returns lead rows shaped like our upload CSV so the frontend can feed them
    straight into the existing generation pipeline.
    """
    user, err = _require_user(req)
    if err:
        return err
    token = _get_valid_mcp_token(user["oid"])
    if not token:
        return _json_response({"error": "Snov.io is not connected. Click 'Connect Snov.io' in step 4 first."}, 409)
    payload = _request_json(req)
    prompt = str(payload.get("prompt") or "").strip()
    task_id = payload.get("taskId")
    page = int(payload.get("page") or 1)
    if not prompt and not task_id:
        return _json_response({"error": "Describe the leads you want (prompt) or pass a taskId to page."}, 400)

    try:
        session = snovio_mcp.SnovioMCPSession(token, APP_DISPLAY_NAME)
        if task_id:
            search_args: dict = {"task_id": int(task_id), "page": page}
        else:
            ai_result = session.call_tool("app_database_search_ai", {"prompt": prompt[:300]})
            filters = _mcp_json(ai_result)
            if not isinstance(filters, dict):
                return _json_response({"error": "Snov.io could not derive search filters from that description.",
                                       "detail": snovio_mcp.tool_result_text(ai_result)[:400]}, 422)
            search_args = _ai_filters_to_search_args(filters)
            if not search_args:
                return _json_response({"error": "Snov.io returned no usable filters for that description."}, 422)
            search_args["is_ai_search"] = True
            search_args["page"] = page
        search_result = session.call_tool("app_database_search_prospects", search_args)
        data = _mcp_json(search_result)
        if not isinstance(data, dict):
            return _json_response({"error": "Unexpected Snov.io search response.",
                                   "detail": snovio_mcp.tool_result_text(search_result)[:400]}, 502)
        rows = data.get("prospects") or data.get("rows") or data.get("data") or []
        leads = [_search_row_to_lead(row) for row in rows if isinstance(row, dict)]
        return _json_response({
            "taskId": data.get("task_id") or data.get("taskId") or task_id,
            "page": page,
            "total": data.get("count") or data.get("total") or data.get("total_count"),
            "leads": leads,
        })
    except snovio_mcp.SnovioMCPError as error:
        return _json_response({"error": str(error)}, 502)


def _ai_filters_to_search_args(payload: dict) -> dict:
    """Map app_database_search_ai output onto app_database_search_prospects params."""
    filters = payload.get("filters") if isinstance(payload.get("filters"), dict) else payload
    company = filters.get("company") if isinstance(filters.get("company"), dict) else {}
    prospect = filters.get("prospect") if isinstance(filters.get("prospect"), dict) else {}
    mapping = {
        "industries": company.get("industries"),
        "company_locations": company.get("locations"),
        "company_names": company.get("names") or company.get("companyNames"),
        "company_sizes": company.get("sizes") or company.get("companySizes"),
        "founded": company.get("founded"),
        "revenue": company.get("revenue"),
        "job_positions": prospect.get("jobPositions") or prospect.get("positions"),
        "prospect_locations": prospect.get("locations"),
        "departments": _stringify_filter(prospect.get("departments")),
        "management_levels": _stringify_filter(prospect.get("managementLevels") or prospect.get("management_levels")),
        "skills": _stringify_filter(prospect.get("skills")),
        "specialities": prospect.get("specialities"),
        "first_name": prospect.get("firstName") or prospect.get("first_name"),
        "last_name": prospect.get("lastName") or prospect.get("last_name"),
    }

    def _has_content(value) -> bool:
        if value in (None, [], {}, ""):
            return False
        if isinstance(value, dict):
            return any(_has_content(v) for v in value.values())
        return True

    return {key: value for key, value in mapping.items() if _has_content(value)}


def _stringify_filter(value):
    """Coerce {include/exclude: [{name/value/text...}]} item objects to plain strings.

    The AI filter helper returns objects for some dictionaries (departments,
    management levels, skills) while the search tool expects string arrays.
    """
    if not isinstance(value, dict):
        return value
    coerced = {}
    for side in ("include", "exclude"):
        items = value.get(side)
        if not isinstance(items, list):
            continue
        flattened = []
        for item in items:
            if isinstance(item, dict):
                flattened.append(str(item.get("value") or item.get("text") or item.get("name") or ""))
            else:
                flattened.append(str(item))
        coerced[side] = [item for item in flattened if item]
    return coerced or value


def _mcp_json(result: dict) -> object:
    """Extract structured data from an MCP tool result.

    Prefers structuredContent when it's actually useful (a dict, or a list of
    dicts) — some Snov.io tools return junk like ["type"] there — otherwise
    parses each text content part (tools may prefix a human summary like
    "50 prospects" before the JSON payload).
    """
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    if isinstance(structured, list) and structured and all(isinstance(i, dict) for i in structured):
        return structured
    candidates = []
    for item in result.get("content") or []:
        if item.get("type") == "text" and item.get("text"):
            candidates.append(str(item["text"]))
    for text in candidates:
        text = text.strip()
        # exact JSON first, then the first {...} block inside the text
        for attempt in (text, text[text.find("{"):] if "{" in text else "", text[text.find("["):] if "[" in text else ""):
            if not attempt:
                continue
            try:
                return json.loads(attempt)
            except (json.JSONDecodeError, TypeError):
                continue
    return None


def _search_row_to_lead(row: dict) -> dict:
    """Normalize a Snov.io database-search row to our lead shape (no email yet:
    Snov.io only reveals addresses once prospects are saved to a list)."""
    def pick(*keys):
        for key in keys:
            value = row.get(key)
            if value:
                return str(value)
        return ""
    return {
        "first_name": pick("firstName", "first_name"),
        "last_name": pick("lastName", "last_name"),
        "full_name": pick("name", "fullName", "full_name"),
        "title": pick("position", "title", "jobPosition"),
        "company": pick("companyName", "company_name"),
        "company_url": pick("companyUrl", "companySite", "company_site"),
        "country": pick("country"),
        "location": pick("locality", "location"),
        "industry": pick("industry"),
        "hasEmail": bool(row.get("emailId")),
        "encodedProspectId": pick("encodedProspectId"),
        "companyId": row.get("companyId"),
        "emailId": row.get("emailId"),
    }


@app.route(route="snovio/import-leads", methods=["POST"])
async def snovio_import_leads(req: func.HttpRequest) -> func.HttpResponse:
    """Save selected database-search rows to a Snov.io list and return them with
    revealed emails (spends Snov.io credits), shaped for the upload pipeline.

    Body: {"listName": "...", "prospects": [{encodedProspectId, companyId, emailId}]}
    """
    user, err = _require_user(req)
    if err:
        return err
    token = _get_valid_mcp_token(user["oid"])
    if not token:
        return _json_response({"error": "Snov.io is not connected."}, 409)
    payload = _request_json(req)
    prospects = payload.get("prospects") or []
    selected = [
        {k: v for k, v in {
            "encodedProspectId": str(p.get("encodedProspectId") or ""),
            "companyId": p.get("companyId"),
            "emailId": p.get("emailId"),
        }.items() if v not in (None, "")}
        for p in prospects
        if isinstance(p, dict) and p.get("encodedProspectId") and p.get("companyId") is not None
    ][:50]
    if not selected:
        return _json_response({"error": "Select at least one prospect from the search results."}, 400)
    list_name = (str(payload.get("listName") or "").strip() or f"Sourced leads {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}")[:50]

    try:
        session = snovio_mcp.SnovioMCPSession(token, APP_DISPLAY_NAME)
        created_raw = session.call_tool("app_create_list", {"name": list_name, "type": "people"})
        created = _mcp_json(created_raw)
        list_id = None
        if isinstance(created, dict):
            data_part = created.get("data") if isinstance(created.get("data"), dict) else {}
            list_part = created.get("list") if isinstance(created.get("list"), dict) else {}
            list_id = created.get("list_id") or created.get("id") or data_part.get("id") or list_part.get("id")
        if not list_id:
            return _json_response({"error": "Could not create the Snov.io list.",
                                   "detail": snovio_mcp.tool_result_text(created_raw)[:300]}, 502)
        session.call_tool("app_database_search_prospects_add_to_list", {"list_id": int(list_id), "prospects": selected})

        leads: list[dict] = []
        for _ in range(6):  # saving is async on Snov.io's side; poll briefly
            listing = _mcp_json(session.call_tool("app_list_prospects", {"list_id": int(list_id), "per_page": 100}))
            rows = []
            if isinstance(listing, dict):
                rows = listing.get("contacts") or listing.get("prospects") or listing.get("rows") or listing.get("data") or []
            leads = [_list_row_to_lead(row) for row in rows if isinstance(row, dict)]
            if len(leads) >= len(selected):
                break
            time.sleep(3)
        return _json_response({"listId": list_id, "listName": list_name, "imported": len(leads), "leads": leads})
    except snovio_mcp.SnovioMCPError as error:
        return _json_response({"error": str(error)}, 502)


def _list_row_to_lead(row: dict) -> dict:
    """Normalize an app_list_prospects row (emails revealed) to the upload shape."""
    def pick(*keys):
        for key in keys:
            value = row.get(key)
            if value:
                return str(value)
        return ""
    email = pick("email", "primaryEmail")
    if not email:
        emails = row.get("emails")
        if isinstance(emails, list) and emails:
            first = emails[0]
            email = str(first.get("email") if isinstance(first, dict) else first or "")
    company = row.get("currentJob") if isinstance(row.get("currentJob"), dict) else {}
    return {
        "email": email,
        "first_name": pick("firstName", "first_name"),
        "last_name": pick("lastName", "last_name"),
        "full_name": pick("name", "fullName"),
        "title": pick("position", "title") or str(company.get("position") or ""),
        "company": pick("companyName", "company_name") or str(company.get("companyName") or ""),
        "company_url": pick("companyUrl", "companySite") or str(company.get("site") or ""),
        "country": pick("country"),
        "location": pick("locality", "location"),
        "industry": pick("industry") or str(company.get("industry") or ""),
    }


# ===========================================================================
# In-app copilot — natural-language operations over the app + the user's Snov.io
# ===========================================================================
def _copilot_app_tools(user: dict, req: func.HttpRequest, durable_client=None, mcp_session=None) -> dict:
    """App tools the copilot can call for the signed-in user.

    Read tools are always safe; ACTION tools (generation, sync, campaign) require
    a confirm flag the model may only set after an explicit user go-ahead in chat.
    """
    mcp_catalog: list[dict] | None = None

    def get_mcp_catalog() -> list[dict]:
        nonlocal mcp_catalog
        if mcp_session is None:
            return []
        if mcp_catalog is None:
            mcp_catalog = mcp_session.list_tools()
        return mcp_catalog

    def search_snovio_tools(args):
        if mcp_session is None:
            return {"error": "Snov.io Copilot is not connected. Open Settings to connect it."}
        query = str(args.get("query") or "").strip().lower()
        terms = [term for term in re.split(r"\W+", query) if term]
        matches = []
        for tool in get_mcp_catalog():
            name = str(tool.get("name") or "")
            description = str(tool.get("description") or "")
            haystack = f"{name} {description}".lower()
            normalized_terms = {term.rstrip("s") for term in terms if term.rstrip("s")}
            matched_terms = {term for term in normalized_terms if term in haystack}
            if normalized_terms and not matched_terms:
                continue
            policy = snovio_policy.classify_tool(name)
            matches.append({
                "name": name,
                "description": description[:300],
                "category": policy.category,
                "requiresConfirmation": policy.requires_confirmation,
                "adminOnly": policy.admin_only,
                "executable": policy.executable,
                "_score": (
                    len(matched_terms) * 10
                    + (30 if "_".join(terms) in name.lower() else 0)
                    + (5 if name.lower().startswith("app_get_") or name.lower().startswith("app_list_") else 0)
                ),
            })
        matches.sort(key=lambda item: (-item["_score"], item["name"]))
        offset = max(0, int(args.get("offset") or 0))
        results = [{key: value for key, value in item.items() if key != "_score"}
                   for item in matches[offset:offset + 20]]
        return {"tools": results, "count": len(results), "total": len(matches),
                "offset": offset, "hasMore": offset + len(results) < len(matches), "query": query}

    def get_snovio_tool_schema(args):
        tool_name = str(args.get("toolName") or "")
        tool = next((item for item in get_mcp_catalog() if item.get("name") == tool_name), None)
        if not tool:
            return {"error": "Tool not found in the current Snov.io MCP catalog."}
        policy = snovio_policy.classify_tool(tool_name)
        return {
            "name": tool_name,
            "description": str(tool.get("description") or "")[:1000],
            "inputSchema": tool.get("inputSchema") or {"type": "object", "properties": {}},
            "policy": {
                "category": policy.category,
                "requiresConfirmation": policy.requires_confirmation,
                "adminOnly": policy.admin_only,
                "executable": policy.executable,
            },
        }

    def execute_snovio_tool(args):
        if mcp_session is None:
            return {"error": "Snov.io Copilot is not connected. Open Settings to connect it."}
        tool_name = str(args.get("toolName") or "")
        tool_arguments = args.get("arguments") if isinstance(args.get("arguments"), dict) else {}
        if not any(item.get("name") == tool_name for item in get_mcp_catalog()):
            return {"error": "Tool not found in the current Snov.io MCP catalog."}
        policy = snovio_policy.classify_tool(tool_name)
        if not policy.executable:
            return {"error": "This Snov.io tool has not been security-reviewed yet."}
        if policy.admin_only and user.get("role") != "admin":
            return {"error": "This Snov.io action is restricted to app administrators."}
        if tool_name in {"app_add_prospects_to_list", "app_database_search_prospects_add_to_list"}:
            list_id = tool_arguments.get("list_id") or tool_arguments.get("listId")
            if not list_id:
                return {
                    "error": (
                        "A concrete Snov.io list ID is required. Create the list with "
                        "app_create_list first, wait for its confirmed result, then add prospects."
                    )
                }
        if policy.requires_confirmation:
            confirmation_id = secrets.token_urlsafe(32)
            expires_at = time.time() + 600
            summary = snovio_policy.summarize_action(tool_name, tool_arguments)
            data_store.save_mcp_confirmation(
                confirmation_id, user["oid"], tool_name, tool_arguments,
                summary, policy.category, expires_at,
            )
            return {
                "confirmationRequired": True,
                "confirmationId": confirmation_id,
                "toolName": tool_name,
                "category": policy.category,
                "summary": summary,
                "expiresAt": expires_at,
            }
        result = mcp_session.call_tool(tool_name, tool_arguments)
        if result.get("isError"):
            detail = snovio_mcp.tool_result_text(result).removeprefix("TOOL ERROR: ").strip()
            return {"error": detail[:1000] or "Snov.io rejected the tool call."}
        return {"toolName": tool_name, "result": snovio_mcp.tool_result_text(result)[:9000]}

    def list_templates_tool(_args):
        return {"templates": [
            {"id": t["id"], "name": t["name"], "emails": t.get("num_emails")}
            for t in list_templates()
        ]}

    def list_jobs_tool(_args):
        jobs = data_store.list_jobs(user["oid"], limit=20)
        return {"jobs": [
            {"jobId": j.get("jobId"), "template": j.get("templateName"), "file": j.get("fileName"),
             "leads": j.get("totalLeads"), "status": j.get("status"), "createdAt": j.get("createdAt"),
             "delegatedBy": j.get("delegatedBy")}
            for j in jobs
        ]}

    def _own_job(job_id: str) -> dict | None:
        """Job lookup honouring admin delegation."""
        if not re.fullmatch(r"[0-9a-fA-F-]{36}", job_id):
            return None
        job = data_store.get_job(user["oid"], job_id)
        if job:
            job["ownerOid"] = user["oid"]
            return job
        if user.get("role") == "admin":
            return data_store.find_job(job_id)
        return None

    def job_drafts_tool(args):
        job_id = str(args.get("jobId") or "")
        if not _own_job(job_id):
            return {"error": "That job does not belong to you (jobId must come from list_my_jobs)."}
        try:
            dataframe = parse_csv(_download_job_csv(job_id))
        except Exception:
            return {"error": "No generated output found for this job."}
        headers = [str(c) for c in dataframe.columns]
        preview = dataframe.head(3).astype(str).to_dict(orient="records")
        return {"columns": headers, "rowCount": len(dataframe), "sampleRows": preview}

    async def start_generation_tool(args):
        job_id = str(args.get("jobId") or "")
        template_id = str(args.get("templateId") or "")
        job = _own_job(job_id)
        if not job:
            return {"error": "Job not found in your workspace — attach a lead file first."}
        try:
            template = get_template(template_id)
        except KeyError:
            return {"error": f"Unknown template '{template_id}'.",
                    "availableTemplates": [t["id"] for t in list_templates()]}
        if durable_client is None:
            return {"error": "Generation is unavailable in this context."}
        if not _blob_exists(INPUT_CONTAINER, f"{job_id}.csv"):
            return {"error": "The uploaded file for this job is missing — attach it again."}
        column_map = None
        required_fields = template.get("required_fields")
        if required_fields:
            dataframe = parse_csv(_download_blob(INPUT_CONTAINER, f"{job_id}.csv"))
            headers = [str(h) for h in dataframe.columns]
            openai_client = AzureOpenAI(
                api_key=AZURE_OPENAI_API_KEY, azure_endpoint=AZURE_OPENAI_ENDPOINT,
                api_version="2024-12-01-preview",
            )
            detection = detect_columns(headers, client=openai_client,
                                       deployment=AZURE_OPENAI_DEPLOYMENT, required_fields=required_fields)
            raw_map = {}
            for field in detection.get("fields", []):
                if field.get("derivedFromFullName") and detection.get("fullNameIndex") is not None:
                    raw_map[field["field"]] = f"full:{detection['fullNameIndex']}"
                elif field.get("index") is not None:
                    raw_map[field["field"]] = field["index"]
            column_map, missing = _build_column_map(raw_map, required_fields)
            if missing:
                return {"error": "The file is missing required columns for this template: " + ", ".join(missing)}
        await durable_client.start_new("orchestrate_emails", client_input={
            "job_id": job_id, "column_map": column_map, "template_config": {"id": template["id"]},
        }, instance_id=job_id)
        try:
            data_store.update_job(job.get("ownerOid", user["oid"]), job_id, {
                "status": "generating", "templateId": template["id"], "templateName": template["name"],
                "startedAt": datetime.now(timezone.utc).isoformat(),
            })
        except Exception as error:
            logger.warning("Copilot job update failed: %s", error)
        return {"started": True, "jobId": job_id, "template": template["name"],
                "leads": job.get("totalLeads"), "note": "Poll get_job_status until Completed."}

    async def job_status_tool(args):
        job_id = str(args.get("jobId") or "")
        job = _own_job(job_id)
        if not job:
            return {"error": "Job not found in your workspace."}
        result = {"jobId": job_id, "status": job.get("status"), "template": job.get("templateName")}
        if durable_client is not None:
            # Wait server-side (up to ~60s) so the agent doesn't burn steps polling.
            deadline = asyncio.get_event_loop().time() + 60
            while True:
                try:
                    status = await durable_client.get_status(job_id)
                    runtime = getattr(getattr(status, "runtime_status", None), "name", None) or str(getattr(status, "runtime_status", ""))
                    if runtime:
                        result["status"] = runtime
                except Exception:
                    break
                if result["status"] in {"Completed", "Failed", "Terminated"} or asyncio.get_event_loop().time() >= deadline:
                    break
                await asyncio.sleep(3)
        return result

    def sync_tool(args):
        job_id = str(args.get("jobId") or "")
        if not _own_job(job_id):
            return {"error": "Job not found in your workspace."}
        if not _snovio_configured(req):
            return {"error": "Snov.io API credentials are not connected — connect in step 4 first."}
        list_name = str(args.get("listName") or "").strip()[:50]
        confirmation_id = secrets.token_urlsafe(32)
        confirmation_args = {"jobId": job_id, "listName": list_name}
        expires_at = time.time() + 600
        summary = f"Sync job {job_id[:8]} to Snov.io list {list_name or '(new list)'}"
        data_store.save_mcp_confirmation(
            confirmation_id, user["oid"], "app_internal_sync_leads", confirmation_args,
            summary, "write", expires_at,
        )
        return {"confirmationRequired": True, "confirmationId": confirmation_id,
                "toolName": "app_internal_sync_leads", "category": "write",
                "summary": summary, "expiresAt": expires_at}

    async def campaign_tool(args):
        job_id = str(args.get("jobId") or "")
        if not _own_job(job_id):
            return {"error": "Job not found in your workspace."}
        if not _snovio_configured(req):
            return {"error": "Snov.io API credentials are not connected — connect in step 4 first."}
        title = str(args.get("title") or "").strip()[:120]
        if not title:
            return {"error": "A campaign title is required."}
        confirmation_id = secrets.token_urlsafe(32)
        confirmation_args = {
            "jobId": job_id, "title": title,
            "delayDays": max(0, min(30, int(args.get("delayDays") or 3))),
        }
        expires_at = time.time() + 600
        summary = f"Create draft Snov.io campaign '{title}' from job {job_id[:8]}"
        data_store.save_mcp_confirmation(
            confirmation_id, user["oid"], "app_internal_create_drip_campaign", confirmation_args,
            summary, "write", expires_at,
        )
        return {"confirmationRequired": True, "confirmationId": confirmation_id,
                "toolName": "app_internal_create_drip_campaign", "category": "write",
                "summary": summary, "expiresAt": expires_at}

    return {
        "search_snovio_tools": {
            "description": "Search the live Snov.io MCP catalog by capability. Use this before selecting a Snov.io action.",
            "parameters": {"type": "object", "properties": {
                "query": {"type": "string", "description": "Capability keywords, such as deals, LinkedIn invite, verify email, or list folders"},
                "offset": {"type": "integer", "minimum": 0, "description": "Pagination offset; results are returned 20 at a time"},
            }, "required": ["query"]},
            "handler": search_snovio_tools,
        },
        "get_snovio_tool_schema": {
            "description": "Get the exact arguments and security policy for one tool returned by search_snovio_tools.",
            "parameters": {"type": "object", "properties": {
                "toolName": {"type": "string"},
            }, "required": ["toolName"]},
            "handler": get_snovio_tool_schema,
        },
        "execute_snovio_tool": {
            "description": "Execute an exact Snov.io MCP tool. Read actions run immediately; changes return a confirmation request for the user.",
            "parameters": {"type": "object", "properties": {
                "toolName": {"type": "string"},
                "arguments": {"type": "object", "additionalProperties": True},
            }, "required": ["toolName", "arguments"]},
            "handler": execute_snovio_tool,
        },
        "list_templates": {
            "description": "List the campaign templates available in this app (id, name, number of emails per lead).",
            "parameters": {"type": "object", "properties": {}},
            "handler": list_templates_tool,
        },
        "list_my_jobs": {
            "description": "List the signed-in user's recent generation jobs (campaigns) in this app.",
            "parameters": {"type": "object", "properties": {}},
            "handler": list_jobs_tool,
        },
        "get_job_output": {
            "description": "Inspect a job's generated output: columns, row count, and a small sample (including Subject_Touch/Body_Touch drafts). Use this to show the user sample drafts before asking for sync approval.",
            "parameters": {"type": "object", "properties": {"jobId": {"type": "string", "description": "job UUID from list_my_jobs"}}, "required": ["jobId"]},
            "handler": job_drafts_tool,
        },
        "start_generation": {
            "description": "Start drafting emails for an uploaded job with a chosen template. Columns are auto-mapped; fails with a clear message if required columns are missing.",
            "parameters": {"type": "object", "properties": {
                "jobId": {"type": "string", "description": "job UUID of the attached/uploaded lead file"},
                "templateId": {"type": "string", "description": "template id from list_templates"},
            }, "required": ["jobId", "templateId"]},
            "handler": start_generation_tool,
        },
        "get_job_status": {
            "description": "Check whether generation for a job is Running, Completed or Failed. Waits up to a minute server-side, so one or two calls are usually enough.",
            "parameters": {"type": "object", "properties": {"jobId": {"type": "string"}}, "required": ["jobId"]},
            "handler": job_status_tool,
        },
        "sync_leads_to_snovio": {
            "description": "PROPOSE ACTION: prepare an exact confirmation to sync a completed job's leads into a Snov.io list. The server will require the user to click Confirm before execution.",
            "parameters": {"type": "object", "properties": {
                "jobId": {"type": "string"},
                "listName": {"type": "string", "description": "Snov.io list name, max 50 chars"},
            }, "required": ["jobId", "listName"]},
            "handler": sync_tool,
        },
        "create_drip_campaign": {
            "description": "PROPOSE ACTION: prepare an exact confirmation to create a DRAFT Snov.io drip campaign. The server requires a user click before execution; nothing is sent automatically.",
            "parameters": {"type": "object", "properties": {
                "jobId": {"type": "string"},
                "title": {"type": "string", "description": "campaign title (also used as list name)"},
                "delayDays": {"type": "integer", "description": "days between touches, default 3"},
            }, "required": ["jobId", "title"]},
            "handler": campaign_tool,
        },
    }


class _CopilotToolRequest:
    """Minimal HttpRequest stand-in so copilot tools can reuse route handlers."""

    def __init__(self, base_req: func.HttpRequest, body: dict, route_params: dict):
        self.headers = getattr(base_req, "headers", {}) or {}
        self.route_params = route_params
        self.params = {}
        self._body = body

    def get_json(self):
        return self._body

    def get_body(self):
        return json.dumps(self._body).encode("utf-8")


def _response_json(response) -> dict:
    """Parse an HttpResponse body produced by our routes (test- and prod-safe)."""
    body = None
    get_body = getattr(response, "get_body", None)
    if callable(get_body):
        try:
            body = get_body()
        except Exception:
            body = None
    if body is None:
        body = getattr(response, "body", None)
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(body or "{}")
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


@app.route(route="copilot/chat", methods=["POST"])
@app.durable_client_input(client_name="client")
async def copilot_chat(req: func.HttpRequest, client) -> func.HttpResponse:
    """Run one turn of the in-app copilot for the signed-in user."""
    user, err = _require_user(req)
    if err:
        return err
    payload = _request_json(req)
    raw_messages = payload.get("messages") or []
    history = []
    for item in raw_messages[-16:]:
        role = str(item.get("role") or "")
        content = str(item.get("content") or "")[:6000]
        if role in ("user", "assistant") and content:
            history.append({"role": role, "content": content})
    if not history or history[-1]["role"] != "user":
        return _json_response({"error": "messages must end with a user message."}, 400)

    rate_key = "copilot-" + hashlib.sha256(user["oid"].encode("utf-8")).hexdigest()
    retry_after = data_store.reserve_snovio_rate_slot(rate_key, COPILOT_REQUESTS_PER_MINUTE)
    if retry_after > 0:
        seconds = max(1, int(retry_after + 0.999))
        return _json_response(
            {"error": "Copilot request limit reached. Please wait before trying again."},
            429,
            headers={"Retry-After": str(seconds)},
        )
    turn_id = secrets.token_urlsafe(24)
    if not data_store.acquire_copilot_turn(user["oid"], turn_id, COPILOT_TURN_TTL_SECONDS):
        return _json_response({"error": "A Copilot request is already running for your account."}, 409)

    token = _get_valid_mcp_token(user["oid"])
    mcp_session = snovio_mcp.SnovioMCPSession(token, APP_DISPLAY_NAME) if token else None
    try:
        openai_client = AzureOpenAI(
            api_key=AZURE_OPENAI_API_KEY,
            azure_endpoint=AZURE_OPENAI_ENDPOINT,
            api_version="2024-12-01-preview",
        )
        outcome = await copilot.run_agent_async(
            openai_client,
            AZURE_OPENAI_DEPLOYMENT,
            history,
            mcp_session,
            _copilot_app_tools(user, req, client, mcp_session),
            system_prompt=copilot.SYSTEM_PROMPT.replace("Email Campaign Generator", APP_DISPLAY_NAME),
        )
        return _json_response({
            "reply": outcome["reply"],
            "toolTrace": outcome["toolTrace"],
            "confirmations": outcome.get("confirmations") or [],
            "snovioConnected": bool(token),
        })
    except Exception as error:
        logger.exception("Copilot turn failed")
        return _json_response({"error": f"Copilot failed: {error}"}, 500)
    finally:
        data_store.release_copilot_turn(user["oid"], turn_id)


@app.route(route="copilot/confirm/{confirmationId}", methods=["POST"])
async def copilot_confirm_action(req: func.HttpRequest) -> func.HttpResponse:
    """Execute one exact, previously proposed Snov.io MCP action once."""
    user, err = _require_user(req)
    if err:
        return err
    if not _parse_bool(_request_json(req).get("confirm"), default=False):
        return _json_response({"error": "Explicit confirmation is required."}, 400)
    confirmation_id = str((req.route_params or {}).get("confirmationId") or "")
    row = data_store.consume_mcp_confirmation(confirmation_id, user["oid"])
    if not row:
        return _json_response({"error": "Confirmation not found, already used, or belongs to another user."}, 404)
    if time.time() > float(row.get("expiresAt") or 0):
        return _json_response({"error": "Confirmation expired. Ask Copilot to propose the action again."}, 410)
    tool_name = str(row.get("toolName") or "")
    policy = snovio_policy.classify_tool(tool_name)
    internal_action = tool_name in {"app_internal_sync_leads", "app_internal_create_drip_campaign"}
    if internal_action:
        policy = snovio_policy.ToolPolicy("write", True)
    if not policy.executable:
        return _json_response({"error": "This Snov.io tool is not approved for execution."}, 403)
    if policy.admin_only and user.get("role") != "admin":
        return _json_response({"error": "This Snov.io action is restricted to app administrators."}, 403)
    try:
        arguments = json.loads(str(row.get("arguments") or "{}"))
        if tool_name in {"app_add_prospects_to_list", "app_database_search_prospects_add_to_list"}:
            list_id = arguments.get("list_id") or arguments.get("listId")
            if not list_id:
                return _json_response({
                    "error": "The confirmed action is missing a Snov.io list ID. Ask Copilot to create the list first.",
                    "executed": False,
                }, 400)
        if tool_name == "app_internal_sync_leads":
            job_id = str(arguments.get("jobId") or "")
            owner, owner_error = _require_job_owner(req, job_id)
            if owner_error:
                return owner_error
            report, sync_error = _run_prospect_sync(_snovio_client(req), job_id, {
                "dryRun": False,
                "listName": str(arguments.get("listName") or "")[:50],
                "autoCreateList": True,
            })
            if sync_error is not None:
                return _json_response({"error": "Snov.io rejected the confirmed sync."}, 502)
            return _json_response({"executed": True, "toolName": tool_name,
                                   "summary": row.get("summary"), "result": report.get("summary")})
        if tool_name == "app_internal_create_drip_campaign":
            job_id = str(arguments.get("jobId") or "")
            sender_accounts = _snovio_client(req).get_sender_accounts()
            sender_ids = [str(sender_accounts[0].get("id"))] if sender_accounts else []
            if not sender_ids:
                return _json_response({"error": "No Snov.io sender account is connected."}, 409)
            title = str(arguments.get("title") or "")[:120]
            fake_req = _CopilotToolRequest(req, {
                "dryRun": False, "campaignTitle": title, "listName": title,
                "senderAccountIds": sender_ids, "delayDays": int(arguments.get("delayDays") or 3),
            }, {"jobId": job_id})
            response = await create_snovio_journey(fake_req)
            payload = _response_json(response)
            if int(getattr(response, "status_code", 500) or 500) >= 400:
                return _json_response({"error": payload.get("error") or "Campaign creation failed."}, 502)
            return _json_response({"executed": True, "toolName": tool_name,
                                   "summary": row.get("summary"), "result": {
                                       "campaignId": payload.get("campaignId"), "status": payload.get("status")}})

        token = _get_valid_mcp_token(user["oid"])
        if not token:
            return _json_response({"error": "Snov.io Copilot is not connected. Open Settings to reconnect."}, 409)
        result = snovio_mcp.SnovioMCPSession(token, APP_DISPLAY_NAME).call_tool(tool_name, arguments)
        if result.get("isError"):
            detail = snovio_mcp.tool_result_text(result).removeprefix("TOOL ERROR: ").strip()
            logger.warning("Confirmed MCP action rejected: tool=%s category=%s", tool_name, policy.category)
            return _json_response({
                "error": detail[:1000] or "Snov.io rejected the confirmed action.",
                "toolName": tool_name,
                "executed": False,
            }, 502)
        logger.info("Confirmed MCP action executed: tool=%s category=%s user=%s", tool_name, policy.category, user["email"])
        return _json_response({
            "executed": True,
            "toolName": tool_name,
            "summary": row.get("summary"),
            "result": snovio_mcp.tool_result_text(result)[:9000],
        })
    except (json.JSONDecodeError, snovio_mcp.SnovioMCPError) as error:
        logger.warning("Confirmed MCP action failed: tool=%s error=%s", tool_name, type(error).__name__)
        return _json_response({"error": "Snov.io could not complete the confirmed action."}, 502)


# ===========================================================================
# Admin dashboard + engagement learning loop
# ===========================================================================
@app.route(route="dashboard/overview", methods=["GET"])
async def admin_dashboard(req: func.HttpRequest) -> func.HttpResponse:
    """Aggregate Snov.io feedback for admins: credits, sends, engagement, sentiment.

    Also persists a per-campaign engagement snapshot that feeds the learning loop.
    """
    _, err = _require_admin(req)
    if err:
        return err
    missing = _snovio_required_response(req)
    if missing:
        return missing
    params = _query_params(req)
    date_to = params.get("dateTo") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_from = params.get("dateFrom") or (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    try:
        client = _snovio_client(req)
        balance = client.get_balance()
        campaigns = client.get_user_campaigns()
        campaign_rows = []
        totals = {"sent": 0, "delivered": 0, "opens": 0, "clicks": 0, "replies": 0,
                  "unsubscribed": 0, "interested": 0, "maybe": 0, "notInterested": 0}
        for campaign in campaigns[:25]:
            campaign_id = str(campaign.get("id") or "")
            row = {
                "id": campaign_id,
                "name": campaign.get("campaign"),
                "status": campaign.get("status"),
                "listId": campaign.get("list_id"),
            }
            try:
                stats = client.get_campaign_analytics({
                    "campaign_id": campaign_id, "date_from": date_from, "date_to": date_to,
                })
                row["analytics"] = {
                    "sent": stats.get("emails_sent", 0),
                    "delivered": stats.get("delivered", 0),
                    "deliveredRate": stats.get("delivered_rate"),
                    "bounced": stats.get("bounced", 0),
                    "opens": stats.get("email_opens", 0),
                    "opensRate": stats.get("email_opens_rate"),
                    "clicks": stats.get("link_clicks", 0),
                    "replies": stats.get("email_replies", 0),
                    "repliesRate": stats.get("email_replies_rate"),
                    "unsubscribed": stats.get("unsubscribed", 0),
                    "interested": stats.get("interested", 0),
                    "maybe": stats.get("maybe", 0),
                    "notInterested": stats.get("not_interested", 0),
                }
                totals["sent"] += int(stats.get("emails_sent") or 0)
                totals["delivered"] += int(stats.get("delivered") or 0)
                totals["opens"] += int(stats.get("email_opens") or 0)
                totals["clicks"] += int(stats.get("link_clicks") or 0)
                totals["replies"] += int(stats.get("email_replies") or 0)
                totals["unsubscribed"] += int(stats.get("unsubscribed") or 0)
                totals["interested"] += int(stats.get("interested") or 0)
                totals["maybe"] += int(stats.get("maybe") or 0)
                totals["notInterested"] += int(stats.get("not_interested") or 0)
                try:
                    data_store.save_engagement_snapshot(campaign_id, {
                        "name": str(campaign.get("campaign") or ""),
                        "status": str(campaign.get("status") or ""),
                        "dateFrom": date_from, "dateTo": date_to,
                        "analytics": row["analytics"],
                    })
                except Exception as snapshot_error:
                    logger.warning("Engagement snapshot failed for %s: %s", campaign_id, snapshot_error)
            except SnovioAPIError as stats_error:
                row["analyticsError"] = str(stats_error)[:200]
            campaign_rows.append(row)
        guidance = []
        try:
            guidance = [
                {"templateId": g.get("RowKey") or g.get("templateId"), "guidance": g.get("guidance"), "updatedAt": g.get("updatedAt")}
                for g in data_store.list_template_guidance()
            ]
        except Exception:
            pass
        return _json_response({
            "dateFrom": date_from, "dateTo": date_to,
            "balance": (balance.get("data") or balance) if isinstance(balance, dict) else balance,
            "totals": totals,
            "campaigns": campaign_rows,
            "templateGuidance": guidance,
        })
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="dashboard/analyze-performance", methods=["POST"])
async def admin_analyze_performance(req: func.HttpRequest) -> func.HttpResponse:
    """Learning loop: turn live engagement stats into per-template guidance.

    Campaign names map to template names by our own convention, so engagement can
    be attributed per template. An LLM pass distills the stats into guidance that
    process_lead_activity injects into future generations for that template.
    """
    admin, err = _require_admin(req)
    if err:
        return err
    missing = _snovio_required_response(req)
    if missing:
        return missing
    try:
        snapshots = data_store.list_engagement_snapshots(limit=100)
    except Exception:
        snapshots = []
    if not snapshots:
        return _json_response({"error": "No engagement snapshots yet — open the dashboard first (it collects them)."}, 409)

    templates = {t["name"]: t["id"] for t in list_templates()}
    per_template: dict[str, list[dict]] = {}
    for snap in snapshots:
        name = str(snap.get("name") or "")
        template_id = templates.get(name)
        if not template_id:
            continue
        try:
            analytics = json.loads(snap.get("analytics") or "{}")
        except (TypeError, json.JSONDecodeError):
            analytics = {}
        per_template.setdefault(template_id, []).append(analytics)

    if not per_template:
        return _json_response({"error": "No snapshots map to app templates yet (campaign names must match template names)."}, 409)

    openai_client = AzureOpenAI(
        api_key=AZURE_OPENAI_API_KEY,
        azure_endpoint=AZURE_OPENAI_ENDPOINT,
        api_version="2024-12-01-preview",
    )
    results = []
    for template_id, stats_list in per_template.items():
        aggregate = {
            "campaigns": len(stats_list),
            "sent": sum(int(s.get("sent") or 0) for s in stats_list),
            "opens": sum(int(s.get("opens") or 0) for s in stats_list),
            "clicks": sum(int(s.get("clicks") or 0) for s in stats_list),
            "replies": sum(int(s.get("replies") or 0) for s in stats_list),
            "unsubscribed": sum(int(s.get("unsubscribed") or 0) for s in stats_list),
            "interested": sum(int(s.get("interested") or 0) for s in stats_list),
            "notInterested": sum(int(s.get("notInterested") or 0) for s in stats_list),
        }
        if aggregate["sent"] < 1:
            results.append({"templateId": template_id, "skipped": "no sends yet"})
            continue
        prompt = (
            "You are optimising B2B email sequences. Based on these aggregate engagement "
            f"stats for the '{template_id}' campaign template:\n{json.dumps(aggregate)}\n"
            "Write 3-5 short, concrete writing guidelines the email generator should follow "
            "next time to improve replies and interested-sentiment (subject style, length, CTA, tone). "
            "Note: replies and interested/notInterested sentiment are the trustworthy signals; opens are noisy. "
            "If data volume is too low to conclude anything (fewer than ~50 sends), say so and give at most one "
            "cautious guideline. Return plain text bullets only."
        )
        try:
            completion = openai_client.chat.completions.create(
                model=AZURE_OPENAI_DEPLOYMENT,
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=2048,
            )
            guidance = (completion.choices[0].message.content or "").strip()
            if guidance:
                data_store.save_template_guidance(template_id, guidance, json.dumps(aggregate))
                results.append({"templateId": template_id, "guidance": guidance, "stats": aggregate})
            else:
                results.append({"templateId": template_id, "skipped": "empty analysis"})
        except Exception as error:
            logger.exception("Guidance analysis failed for %s", template_id)
            results.append({"templateId": template_id, "error": str(error)[:200]})
    logger.info("Performance analysis run by %s: %d templates", admin["email"], len(results))
    return _json_response({"analyzed": results})


@app.route(route="snovio/balance", methods=["GET"])
async def get_snovio_balance(req: func.HttpRequest) -> func.HttpResponse:
    """Return Snov.io account balance as a preflight check."""
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    missing = _snovio_required_response(req)
    if missing:
        return missing

    try:
        balance = _snovio_client(req).get_balance()
        return _json_response({"configured": True, "balance": balance})
    except SnovioConfigError as error:
        return _json_response({"configured": False, "error": str(error)}, 503)
    except SnovioAPIError as error:
        status_code = 429 if error.status_code == 429 else 502
        return _json_response({"configured": True, "error": str(error), "statusCode": error.status_code}, status_code)


@app.route(route="snovio/options", methods=["GET"])
async def get_snovio_options(req: func.HttpRequest) -> func.HttpResponse:
    """Return Snov.io lists, campaigns, sender accounts, schedules, and custom fields."""
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    missing = _snovio_required_response(req)
    if missing:
        return _json_response({
            "configured": False,
            "lists": [],
            "campaigns": [],
            "senderAccounts": [],
            "schedules": [],
            "customFields": [],
            "templateMappings": _parse_template_mappings(),
        })

    try:
        client = _snovio_client(req)
        return _json_response({
            "configured": True,
            "lists": client.get_user_lists(),
            "campaigns": client.get_user_campaigns(),
            "senderAccounts": client.get_sender_accounts(),
            "schedules": client.get_campaign_schedules(),
            "customFields": client.get_custom_fields(),
            "templateMappings": _parse_template_mappings(),
            "templates": list_templates(),
        })
    except SnovioAPIError as error:
        return _json_response({"configured": True, "error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/preflight", methods=["GET"])
async def get_snovio_preflight(req: func.HttpRequest) -> func.HttpResponse:
    """Estimate credit/rate impact before a Snov.io operation."""
    gate = _require_allowed_domain(req)
    if gate:
        return gate
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
    response = {"configured": _snovio_configured(req), "estimate": estimate, "rateLimitPerMinute": SNOVIO_REQUESTS_PER_MINUTE}

    if _snovio_configured(req):
        try:
            balance = _snovio_client(req).get_balance()
            balance_value = float((balance.get("data") or {}).get("balance", 0))
            response["balance"] = balance
            response["lowCredit"] = balance_value < estimate["estimatedCredits"] + SNOVIO_LOW_CREDIT_THRESHOLD
        except Exception as error:
            response["balanceError"] = str(error)

    return _json_response(response)


@app.route(route="jobs/{jobId}/snovio/verify", methods=["POST"])
async def verify_job_emails(req: func.HttpRequest) -> func.HttpResponse:
    """Start Snov.io email verification for a generated job."""
    missing = _snovio_required_response(req)
    if missing:
        return missing

    job_id = req.route_params.get("jobId", "")
    _, owner_err = _require_job_owner(req, job_id)
    if owner_err:
        return owner_err
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

        client = _snovio_client(req)
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
    missing = _snovio_required_response(req)
    if missing:
        return missing
    payload = _request_json(req)
    task_hash = payload.get("taskHash") or payload.get("task_hash")
    allow_unknown = _parse_bool(payload.get("allowUnknown"), SNOVIO_ALLOW_UNKNOWN_VERIFICATION)
    if not task_hash:
        return _json_response({"error": "taskHash is required."}, 400)
    try:
        result = _snovio_client(req).get_email_verification_result(task_hash)
        classified = [classify_verification(item, allow_unknown=allow_unknown) for item in result.get("data", [])]
        return _json_response({"taskHash": task_hash, "status": result.get("status"), "results": classified, "raw": result})
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


def _run_prospect_sync(
    client: SnovioClient,
    job_id: str,
    payload: dict,
    on_list_created: Callable[[str, Any], None] | None = None,
) -> tuple[dict, func.HttpResponse | None]:
    """Resolve the target list, evaluate eligibility, and sync prospects.

    Shared by the sync and journey routes. Returns ``(report, error_response)``; when
    ``error_response`` is not None the caller must return it directly. On success the
    report's ``listId`` holds the resolved Snov.io list id (created when requested).
    """
    list_id = str(payload.get("listId") or payload.get("list_id") or "").strip()
    campaign_id = str(payload.get("campaignId") or payload.get("campaign_id") or "").strip()
    dry_run = _parse_bool(payload.get("dryRun"), default=True)
    auto_create_list = _parse_bool(payload.get("createListIfMissing", payload.get("autoCreateList")), default=True)
    # Verification is opt-in. Requiring it by default silently blocked every lead
    # (status "verification_required") whenever the user hadn't run the separate,
    # credit-costing Verify step first — which read as "sync does nothing / keeps failing".
    require_verification = _parse_bool(payload.get("requireVerification"), default=False)
    confirm_active_campaign = _parse_bool(payload.get("confirmActiveCampaign"), default=False)
    # When a lead is already in the target list, refresh it (Snov.io updateContact)
    # so re-running a campaign pushes the newly drafted Subject/Body_Touch fields.
    # Pass updateExisting=false to skip duplicates instead.
    update_existing = _parse_bool(payload.get("updateExisting"), default=True)
    allow_unknown = _parse_bool(payload.get("allowUnknown"), SNOVIO_ALLOW_UNKNOWN_VERIFICATION)
    suppressed_emails = {str(item).strip().lower() for item in payload.get("suppressedEmails", [])}
    suppressed_domains = {str(item).strip().lower() for item in payload.get("suppressedDomains", [])}

    campaigns = client.get_user_campaigns() if campaign_id else []
    campaign = find_campaign(campaigns, campaign_id) if campaign_id else None
    campaign_list_id = _snovio_campaign_list_id(campaign)
    created_list = payload.get("_createdList")
    list_source = "created" if list_id and created_list else ("selected" if list_id else "")
    if not list_id and campaign_list_id:
        list_id = campaign_list_id
        list_source = "campaign"

    list_name = _snovio_list_name(payload, job_id)
    planned_list_creation = not list_id and auto_create_list
    if not list_id and not auto_create_list:
        return {}, _json_response({
            "error": "listId is required unless autoCreateList=true or the selected campaign includes list_id.",
            "campaign": campaign,
        }, 400)

    active_campaign = is_sending_campaign(campaign)
    if active_campaign and not dry_run and not confirm_active_campaign:
        return {}, _json_response({
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
            return {}, _json_response({"error": "Snov.io list was created but no list ID was returned.", "createdList": created_list}, 502)
        list_source = "created"
        if on_list_created is not None:
            on_list_created(list_id, created_list)

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
                exists_elsewhere = bool(duplicate.get("data")) and not existing_in_target
                if existing_in_target and not update_existing:
                    row_report.update({"eligible": False, "blockedReason": "duplicate_in_target_list", "status": "skipped"})
                else:
                    row_report["existingProspect"] = existing_in_target
                    prospect_payload = build_prospect_payload(dataframe.iloc[row_index], columns, list_id, custom_fields)
                    if exists_elsewhere:
                        # Snov.io's updateContact updates the existing prospect's fields but
                        # does NOT attach it to the new list — the target list stays empty.
                        # createDuplicates makes a per-list copy so each list carries its own
                        # campaign drafts (updateContact and createDuplicates are exclusive).
                        prospect_payload["updateContact"] = False
                        prospect_payload["createDuplicates"] = True
                        row_report["duplicatedIntoList"] = True
                    try:
                        response = client.add_prospect_to_list(list_id, prospect_payload)
                    except SnovioAPIError as add_error:
                        # Snov.io rejects the whole prospect if companySite isn't a domain
                        # it accepts (e.g. webmail/unverifiable domains). companySite is
                        # optional, so drop it and retry rather than losing the lead.
                        if "companysite" in str(add_error).lower() and prospect_payload.get("companySite"):
                            retry_payload = {k: v for k, v in prospect_payload.items() if k != "companySite"}
                            logger.warning("Retrying %s without companySite (was %r)", email, prospect_payload.get("companySite"))
                            response = client.add_prospect_to_list(list_id, retry_payload)
                        else:
                            raise
                    row_report["response"] = response
                    row_report["snovioProspectId"] = response.get("id")
                    if response.get("updated") or (
                        existing_in_target and (response.get("added") or response.get("success") or response.get("id"))
                    ):
                        row_report["status"] = "updated"
                    elif response.get("added") or response.get("success") or response.get("id"):
                        # Snov.io's add-prospect-to-list returns {"success": true} (and
                        # sometimes an id) on success without "added"/"updated" keys, so a
                        # genuine success must not be misread as a failure.
                        row_report["status"] = "added"
                    else:
                        message = (
                            response.get("message")
                            or response.get("error")
                            or "Snov.io did not confirm the prospect was added."
                        )
                        row_report.update({"status": "failed", "error": str(message)})
                        logger.warning("Snov.io add-prospect not confirmed for %s: %s", email, response)
            except Exception as error:
                row_report.update({"status": "failed", "error": str(error)})
                logger.warning("Snov.io add-prospect failed for %s: %s", email, error)


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
        "updateExisting": update_existing,
        "requireVerification": require_verification,
        "columns": columns,
        "summary": summarize_report(report_rows),
        "rows": report_rows,
    }
    return report, None


@app.route(route="jobs/{jobId}/snovio/sync", methods=["POST"])
@app.queue_output(arg_name="syncOperation", queue_name=SNOVIO_SYNC_QUEUE, connection="AzureWebJobsStorage")
async def sync_job_to_snovio(req: func.HttpRequest, syncOperation=None) -> func.HttpResponse:
    """Dry-run or execute post-generation prospect sync into a Snov.io list."""
    missing = _snovio_required_response(req)
    if missing:
        return missing

    job_id = req.route_params.get("jobId", "")
    owner, owner_err = _require_job_owner(req, job_id)
    if owner_err:
        return owner_err
    payload = _request_json(req)
    if not _parse_bool(payload.get("dryRun"), default=True):
        if syncOperation is None:
            return _json_response({"error": "The Snov.io sync queue is unavailable."}, 503)
        job_owner_oid = str(owner["job"].get("ownerOid") or owner["oid"])
        operation_id = uuid.uuid4().hex
        request_blob = f"snovio-sync-operations/{job_owner_oid}/{operation_id}.json"
        claim = data_store.claim_snovio_sync_operation(
            job_owner_oid, job_id, operation_id, request_blob
        )
        if not claim.get("acquired"):
            existing_id = str(claim.get("operationId") or "")
            if existing_id:
                return _json_response({
                    "operationId": existing_id,
                    "status": str(claim.get("status") or "queued"),
                    "statusUrl": f"/api/jobs/{job_id}/snovio/sync/{existing_id}",
                    "message": "This sync is already in progress.",
                }, 202)
            return _json_response({"error": "The sync could not be queued. Please try again."}, 409)
        _upload_blob(
            OUTPUT_CONTAINER,
            request_blob,
            json.dumps({**payload, "dryRun": False}).encode("utf-8"),
        )
        syncOperation.set(json.dumps({
            "operationId": operation_id,
            "oid": job_owner_oid,
            "jobId": job_id,
            "requestBlob": request_blob,
        }, separators=(",", ":")))
        return _json_response({
            "operationId": operation_id,
            "status": "queued",
            "statusUrl": f"/api/jobs/{job_id}/snovio/sync/{operation_id}",
            "message": "Sync started. You can leave this screen while it finishes.",
        }, 202)
    try:
        client = _snovio_client(req)
        report, error = _run_prospect_sync(client, job_id, payload)
        if error:
            return error
        report["reportBlob"] = _upload_snovio_report(job_id, "sync", report)
        return _json_response(report)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)
    except Exception as error:
        logger.exception("Snov.io sync failed for %s", job_id)
        return _json_response({"error": f"Snov.io sync failed: {str(error)}"}, 500)


@app.queue_trigger(arg_name="syncOperation", queue_name=SNOVIO_SYNC_QUEUE, connection="AzureWebJobsStorage")
def process_snovio_sync(syncOperation) -> None:
    """Execute a queued Snov.io sync and persist its terminal report on the job."""
    message = json.loads(syncOperation.get_body().decode("utf-8"))
    operation_id = str(message.get("operationId") or "")
    oid = str(message.get("oid") or "")
    job_id = str(message.get("jobId") or "")
    request_blob = str(message.get("requestBlob") or "")
    if not all((operation_id, oid, job_id, request_blob)):
        logger.error("Discarding malformed Snov.io sync queue message")
        return
    job = data_store.get_job(oid, job_id)
    if not job or str(job.get("snovioSyncOperationId") or "") != operation_id:
        logger.info("Ignoring stale Snov.io sync operation %s", operation_id)
        return
    if str(job.get("snovioSyncStatus") or "") == "completed":
        return

    data_store.update_job(oid, job_id, {
        "snovioSyncStatus": "running",
        "snovioSyncUpdatedAt": datetime.now(timezone.utc).isoformat(),
    })
    try:
        payload = json.loads(_download_blob(OUTPUT_CONTAINER, request_blob).decode("utf-8"))
        def persist_created_list(list_id: str, created_list: Any) -> None:
            payload["listId"] = list_id
            payload["_createdList"] = created_list
            _upload_blob(OUTPUT_CONTAINER, request_blob, json.dumps(payload).encode("utf-8"))

        report, error = _run_prospect_sync(
            _snovio_client_for_oid(oid), job_id, payload, persist_created_list
        )
        if error is not None:
            error_payload = _response_json(error)
            raise RuntimeError(str(error_payload.get("error") or "Snov.io rejected the sync."))
        report_blob = _upload_snovio_report(job_id, f"sync-{operation_id}", report)
        data_store.update_job(oid, job_id, {
            "snovioSyncStatus": "completed",
            "snovioSyncReportBlob": report_blob,
            "snovioSyncError": "",
            "snovioSyncUpdatedAt": datetime.now(timezone.utc).isoformat(),
        })
        logger.info("Queued Snov.io sync completed: operation=%s job=%s", operation_id, job_id)
    except Exception as error:
        logger.exception("Queued Snov.io sync failed: operation=%s job=%s", operation_id, job_id)
        data_store.update_job(oid, job_id, {
            "snovioSyncStatus": "failed",
            "snovioSyncError": str(error)[:1000],
            "snovioSyncUpdatedAt": datetime.now(timezone.utc).isoformat(),
        })


@app.route(route="jobs/{jobId}/snovio/sync/{operationId}", methods=["GET"])
async def get_snovio_sync_status(req: func.HttpRequest) -> func.HttpResponse:
    """Return one owner-scoped queued sync status and its completed report."""
    job_id = str((req.route_params or {}).get("jobId") or "")
    operation_id = str((req.route_params or {}).get("operationId") or "")
    owner, owner_error = _require_job_owner(req, job_id)
    if owner_error:
        return owner_error
    job = owner["job"]
    if not operation_id or str(job.get("snovioSyncOperationId") or "") != operation_id:
        return _json_response({"error": "Sync operation not found."}, 404)
    status = str(job.get("snovioSyncStatus") or "queued")
    response = {
        "operationId": operation_id,
        "status": status,
        "updatedAt": job.get("snovioSyncUpdatedAt"),
    }
    if status == "failed":
        response["error"] = str(job.get("snovioSyncError") or "Snov.io sync failed.")
    if status == "completed":
        report_blob = str(job.get("snovioSyncReportBlob") or "")
        if not report_blob:
            return _json_response({"error": "The sync completed without a report."}, 500)
        try:
            response["report"] = json.loads(_download_blob(OUTPUT_CONTAINER, report_blob).decode("utf-8"))
        except Exception:
            return _json_response({"error": "The completed sync report is unavailable."}, 500)
    return _json_response(response)


@app.route(route="jobs/{jobId}/snovio/journey", methods=["POST"])
async def create_snovio_journey(req: func.HttpRequest) -> func.HttpResponse:
    """Sync prospects and build a multi-touch Snov.io drip campaign ("customer journey").

    Each generated touch is synced as a prospect custom field and referenced from the
    matching email step via a merge variable, so every recipient receives their own
    drafted content. The campaign is created in draft state for human review and launch;
    this endpoint never starts a campaign.
    """
    missing = _snovio_required_response(req)
    if missing:
        return missing

    job_id = req.route_params.get("jobId", "")
    _, owner_err = _require_job_owner(req, job_id)
    if owner_err:
        return owner_err
    payload = _request_json(req)
    dry_run = _parse_bool(payload.get("dryRun"), default=True)
    try:
        delay_days = int(payload.get("delayDays", SNOVIO_DEFAULT_DELAY_DAYS) or 0)
    except (TypeError, ValueError):
        delay_days = SNOVIO_DEFAULT_DELAY_DAYS
    sender_account_ids = [str(s).strip() for s in payload.get("senderAccountIds", []) if str(s).strip()]
    campaign_title = str(payload.get("campaignTitle") or "").strip()
    track_opens = _parse_bool(payload.get("trackOpens"), default=True)
    track_clicks = _parse_bool(payload.get("trackClicks"), default=True)
    schedule_id = payload.get("scheduleId")
    timezone_name = str(payload.get("timezone") or SNOVIO_CAMPAIGN_TIMEZONE or "").strip()

    try:
        client = _snovio_client(req)

        # Derive the touch count from the generated output CSV headers.
        output_df = parse_csv(_download_job_csv(job_id))
        num_touches = detect_touch_count([str(column) for column in output_df.columns])
        if num_touches < 1:
            return _json_response({"error": "No generated Subject_Touch/Body_Touch columns found for this job."}, 400)

        # Snov.io only stores values for custom fields that already exist, so confirm the
        # per-touch fields are present before syncing or building the campaign.
        required_labels = touch_field_labels(num_touches)
        custom_fields = client.get_custom_fields()
        readiness = assess_custom_field_readiness(custom_fields, required_labels)

        sequence, email_refs = build_campaign_sequence(num_touches, delay_days=delay_days)
        touch_content = build_touch_content(num_touches)
        title = campaign_title or _snovio_list_name(payload, job_id)

        plan: dict[str, Any] = {
            "jobId": job_id,
            "numTouches": num_touches,
            "delayDays": delay_days,
            "campaignTitle": title,
            "senderAccountIds": sender_account_ids,
            "customFieldReadiness": readiness,
            "plannedSteps": [
                {"touch": content["touch"], "subject": content["subject"], "body": content["body"]}
                for content in touch_content
            ],
            "estimate": estimate_usage(len(output_df), "sync"),
        }

        if not readiness["ready"]:
            plan["error"] = "Required Snov.io custom fields are missing."
            plan["action"] = (
                "Create the listed custom fields in Snov.io (Prospects \u2192 custom fields), "
                "then retry. They carry each lead's drafted subject and body into the campaign."
            )
            return _json_response(plan, 422)

        if not dry_run and not sender_account_ids:
            plan["error"] = "senderAccountIds is required to create a campaign."
            return _json_response(plan, 400)

        # Sync prospects; their per-touch content lands as custom-field values.
        report, error = _run_prospect_sync(client, job_id, payload)
        if error:
            return error
        plan["sync"] = report

        if dry_run:
            plan["dryRun"] = True
            return _json_response(plan)

        list_id = report.get("listId")
        if not list_id:
            plan["error"] = "No Snov.io list id was resolved for the campaign."
            return _json_response(plan, 400)

        # Create the campaign in draft state.
        campaign_payload = build_campaign_payload(
            title=title,
            email_account_ids=sender_account_ids,
            list_id=list_id,
            sequence=sequence,
            track_opens=track_opens,
            track_clicks=track_clicks,
            schedule_id=int(schedule_id) if schedule_id else None,
            timezone=timezone_name or None,
            archive_in_months=SNOVIO_CAMPAIGN_ARCHIVE_MONTHS,
        )
        campaign_response = client.create_campaign(campaign_payload)
        campaign_data = campaign_response.get("data", campaign_response) if isinstance(campaign_response, dict) else {}
        campaign_id = campaign_data.get("id")
        plan["campaignId"] = campaign_id
        plan["campaign"] = campaign_data

        # Attach each touch's merge-variable content to its email step.
        step_map = map_email_step_contents(campaign_response, email_refs)
        content_results = []
        for entry, content in zip(step_map, touch_content):
            step_id = entry.get("stepId")
            content_id = entry.get("contentId")
            result = {"touch": content["touch"], "stepId": step_id, "contentId": content_id}
            if step_id is None or content_id is None:
                result["status"] = "skipped"
                result["error"] = "Snov.io did not return a step or content id for this touch."
            else:
                try:
                    client.create_email_step_content(
                        campaign_id,
                        step_id,
                        int(content_id),
                        subject=content["subject"],
                        body=content["body"],
                        plain_text=content["plain_text"],
                    )
                    result["status"] = "written"
                except Exception as content_error:
                    result["status"] = "failed"
                    result["error"] = str(content_error)
            content_results.append(result)

        plan["stepContent"] = content_results
        plan["status"] = "draft"
        plan["note"] = "Campaign created in draft. Review and launch it in Snov.io when ready."
        plan["reportBlob"] = _upload_snovio_report(job_id, "journey", plan)
        return _json_response(plan, 201)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)
    except (ValueError, SnovioConfigError) as error:
        return _json_response({"error": str(error)}, 400)
    except Exception as error:
        logger.exception("Snov.io journey creation failed for %s", job_id)
        return _json_response({"error": f"Snov.io journey creation failed: {str(error)}"}, 500)


@app.route(route="jobs/{jobId}/snovio/enrich", methods=["POST"])
async def enrich_job_with_snovio(req: func.HttpRequest) -> func.HttpResponse:
    """Dry-run or start optional Snov.io enrichment tasks for a job."""
    missing = _snovio_required_response(req)
    if missing:
        return missing

    job_id = req.route_params.get("jobId", "")
    _, owner_err = _require_job_owner(req, job_id)
    if owner_err:
        return owner_err
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

        client = _snovio_client(req)
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
    missing = _snovio_required_response(req)
    if missing:
        return missing
    payload = _request_json(req)
    kind = payload.get("kind")
    task_hash = payload.get("taskHash") or payload.get("task_hash")
    if not kind or not task_hash:
        return _json_response({"error": "kind and taskHash are required."}, 400)
    client = _snovio_client(req)
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
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    missing = _snovio_required_response(req)
    if missing:
        return missing
    params = _query_params(req)
    campaign_id = params.get("campaignId", "")
    date_to = params.get("dateTo") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    date_from = params.get("dateFrom") or (datetime.now(timezone.utc) - timedelta(days=90)).strftime("%Y-%m-%d")
    filters = {"date_from": date_from, "date_to": date_to}
    if campaign_id:
        filters["campaign_id"] = campaign_id
    try:
        client = _snovio_client(req)
        response = {"analytics": client.get_campaign_analytics(filters)}
        if campaign_id:
            response["progress"] = client.get_campaign_progress(campaign_id)
            if _parse_bool(params.get("includeActivity"), default=False):
                response["allReplies"] = client.get_campaign_all_replies(campaign_id)
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
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    missing = _snovio_required_response(req)
    if missing:
        return missing
    payload = _request_json(req)
    list_id = str(payload.get("listId") or payload.get("list_id") or "").strip()
    items = [str(item).strip() for item in payload.get("items", []) if str(item).strip()]
    if not list_id or not items:
        return _json_response({"error": "listId and at least one item are required."}, 400)
    try:
        response = _snovio_client(req).add_do_not_email(list_id, items)
        audit = {"listId": list_id, "items": items, "response": response, "createdAt": datetime.now(timezone.utc).isoformat()}
        _upload_blob(OUTPUT_CONTAINER, f"snovio-audit/suppressions/{uuid.uuid4()}.json", json.dumps(audit, indent=2).encode("utf-8"))
        return _json_response(audit)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/recipient-status", methods=["POST"])
async def change_snovio_recipient_status(req: func.HttpRequest) -> func.HttpResponse:
    """Pause, activate, or unsubscribe a Snov.io campaign recipient."""
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    missing = _snovio_required_response(req)
    if missing:
        return missing
    payload = _request_json(req)
    try:
        response = _snovio_client(req).change_recipient_status(
            email=payload.get("email", ""),
            campaign_id=str(payload.get("campaignId") or payload.get("campaign_id") or ""),
            status=payload.get("status", ""),
        )
        return _json_response({"response": response})
    except (ValueError, SnovioAPIError) as error:
        status_code = 400 if isinstance(error, ValueError) else 502
        return _json_response({"error": str(error)}, status_code)


@app.route(route="snovio/webhook/{callbackToken}", methods=["POST"])
@app.queue_output(arg_name="webhookEvent", queue_name=SNOVIO_WEBHOOK_QUEUE, connection="AzureWebJobsStorage")
async def receive_snovio_webhook(req: func.HttpRequest, webhookEvent) -> func.HttpResponse:
    """Validate and enqueue a Snov.io event within its three-second deadline."""
    config = data_store.get_snovio_webhook_config()
    provided = str((req.route_params or {}).get("callbackToken") or "")
    expected_hash = str((config or {}).get("tokenHash") or "")
    provided_hash = hashlib.sha256(provided.encode("utf-8")).hexdigest()
    if not expected_hash or not hmac.compare_digest(provided_hash, expected_hash):
        return _json_response({"error": "Invalid webhook token."}, 401)
    content_type = str((getattr(req, "headers", {}) or {}).get("content-type") or "").lower()
    if "application/json" not in content_type:
        return _json_response({"error": "Webhook content type must be application/json."}, 415)
    body = req.get_body() or b""
    if len(body) > MAX_WEBHOOK_SIZE_BYTES:
        return _json_response({"error": "Webhook payload is too large."}, 413)
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json_response({"error": "Webhook payload must be valid UTF-8 JSON."}, 400)
    if not isinstance(payload, dict):
        return _json_response({"error": "Webhook payload must be a JSON object."}, 400)
    canonical = json.dumps(payload, sort_keys=True)
    event_id = payload.get("event_id") or payload.get("id") or hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    webhookEvent.set(json.dumps({"eventId": str(event_id), "payload": payload}, separators=(",", ":")))
    return _json_response({"accepted": True, "eventId": str(event_id)}, 202)


@app.queue_trigger(arg_name="webhookEvent", queue_name=SNOVIO_WEBHOOK_QUEUE, connection="AzureWebJobsStorage")
def process_snovio_webhook(webhookEvent) -> None:
    """Persist queued events idempotently; Functions handles retries/poisoning."""
    raw = webhookEvent.get_body()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    event = json.loads(raw)
    event_id = str(event.get("eventId") or "")
    if not event_id:
        raise ValueError("Queued Snov.io webhook has no eventId.")
    blob_name = f"snovio-webhooks/{event_id}.json"
    if _blob_exists(OUTPUT_CONTAINER, blob_name):
        return
    _upload_blob(OUTPUT_CONTAINER, blob_name, json.dumps(event, indent=2).encode("utf-8"))


def _webhook_id(response: Any) -> str:
    if isinstance(response, list) and response:
        response = response[0]
    if not isinstance(response, dict):
        return ""
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    return str(data.get("id") or response.get("id") or "")


@app.route(route="snovio/webhook-settings", methods=["GET"])
async def get_snovio_webhook_settings(req: func.HttpRequest) -> func.HttpResponse:
    admin, err = _require_admin(req)
    if err:
        return err
    config = data_store.get_snovio_webhook_config()
    webhook_ids = []
    try:
        webhook_ids = json.loads(str((config or {}).get("webhookIds") or "[]"))
    except json.JSONDecodeError:
        pass
    return _json_response({
        "configured": bool((config or {}).get("tokenHash")),
        "registeredEvents": len(webhook_ids),
        "updatedAt": (config or {}).get("updatedAt"),
        "queue": SNOVIO_WEBHOOK_QUEUE,
    })


@app.route(route="snovio/webhook-settings", methods=["POST"])
async def configure_snovio_webhooks(req: func.HttpRequest) -> func.HttpResponse:
    admin, err = _require_admin(req)
    if err:
        return err
    missing = _snovio_required_response(req)
    if missing:
        return missing
    origin = _public_origin(req)
    if not origin.startswith("https://"):
        return _json_response({"error": "PUBLIC_APP_ORIGIN must be configured before webhooks."}, 503)

    callback_token = secrets.token_urlsafe(48)
    endpoint_url = f"{origin}/api/snovio/webhook/{callback_token}"
    client = _snovio_client(req)
    created_ids: list[str] = []
    try:
        for event_object, event_action in DEFAULT_SNOVIO_WEBHOOK_EVENTS:
            webhook_id = _webhook_id(client.create_webhook(event_object, event_action, endpoint_url))
            if not webhook_id:
                raise SnovioAPIError("Snov.io did not return a webhook id.")
            created_ids.append(webhook_id)
    except Exception as error:
        for webhook_id in created_ids:
            try:
                client.delete_webhook(webhook_id)
            except Exception:
                pass
        logger.warning("Webhook setup rolled back after %d registrations: %s", len(created_ids), type(error).__name__)
        return _json_response({"error": "Snov.io webhook setup failed; partial registrations were rolled back."}, 502)

    previous = data_store.get_snovio_webhook_config()
    data_store.save_snovio_webhook_config(
        hashlib.sha256(callback_token.encode("utf-8")).hexdigest(), created_ids
    )
    try:
        old_ids = json.loads(str((previous or {}).get("webhookIds") or "[]"))
    except json.JSONDecodeError:
        old_ids = []
    for webhook_id in old_ids:
        if str(webhook_id) not in created_ids:
            try:
                client.delete_webhook(str(webhook_id))
            except Exception:
                logger.warning("Old Snov.io webhook cleanup failed: id=%s", webhook_id)
    logger.info("Snov.io webhooks configured by %s: %d events", admin["email"], len(created_ids))
    return _json_response({"configured": True, "registeredEvents": len(created_ids)}, 201)


@app.route(route="snovio/webhook-settings/test", methods=["POST"])
@app.queue_output(arg_name="webhookEvent", queue_name=SNOVIO_WEBHOOK_QUEUE, connection="AzureWebJobsStorage")
async def test_snovio_webhook_pipeline(req: func.HttpRequest, webhookEvent) -> func.HttpResponse:
    admin, err = _require_admin(req)
    if err:
        return err
    event_id = f"test-{uuid.uuid4()}"
    webhookEvent.set(json.dumps({
        "eventId": event_id,
        "payload": {
            "event_object": "test",
            "event_action": "pipeline_check",
            "requestedBy": admin["email"],
        },
    }, separators=(",", ":")))
    return _json_response({"accepted": True, "eventId": event_id}, 202)


@app.route(route="snovio/webhooks", methods=["GET"])
async def list_snovio_webhooks(req: func.HttpRequest) -> func.HttpResponse:
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    missing = _snovio_required_response(req)
    if missing:
        return missing
    try:
        return _json_response(_snovio_client(req).list_webhooks())
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/webhooks", methods=["POST"])
async def create_snovio_webhook(req: func.HttpRequest) -> func.HttpResponse:
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    missing = _snovio_required_response(req)
    if missing:
        return missing
    payload = _request_json(req)
    try:
        response = _snovio_client(req).create_webhook(payload.get("eventObject", ""), payload.get("eventAction", ""), payload.get("endpointUrl", ""))
        return _json_response(response)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/webhooks/{webhookId}", methods=["PUT"])
async def update_snovio_webhook(req: func.HttpRequest) -> func.HttpResponse:
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    missing = _snovio_required_response(req)
    if missing:
        return missing
    payload = _request_json(req)
    try:
        response = _snovio_client(req).update_webhook(req.route_params.get("webhookId", ""), payload.get("status", ""))
        return _json_response(response)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


@app.route(route="snovio/webhooks/{webhookId}", methods=["DELETE"])
async def delete_snovio_webhook(req: func.HttpRequest) -> func.HttpResponse:
    gate = _require_allowed_domain(req)
    if gate:
        return gate
    missing = _snovio_required_response(req)
    if missing:
        return missing
    try:
        response = _snovio_client(req).delete_webhook(req.route_params.get("webhookId", ""))
        return _json_response(response)
    except SnovioAPIError as error:
        return _json_response({"error": str(error), "statusCode": error.status_code}, 502)


# ===========================================================================
# 8. STATUS — HTTP Trigger
# ===========================================================================
@app.route(route="status/{jobId}", methods=["GET"])
@app.durable_client_input(client_name="client")
async def get_status(req: func.HttpRequest, client) -> func.HttpResponse:
    """Return the processing status of a job (owner only)."""
    job_id = req.route_params.get("jobId", "")
    if not job_id:
        return func.HttpResponse(
            json.dumps({"error": "Missing jobId"}),
            status_code=400,
            mimetype="application/json",
        )

    user, err = _require_job_owner(req, job_id)
    if err:
        return err

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

        # Lazily sync the terminal state onto the workspace job row.
        if runtime_status in ("Completed", "Failed") and user["job"].get("status") != runtime_status:
            try:
                data_store.update_job(user["job"].get("ownerOid", user["oid"]), job_id, {
                    "status": runtime_status,
                    "completedAt": datetime.now(timezone.utc).isoformat(),
                    "totalLeads": response_body.get("totalLeads", user["job"].get("totalLeads", 0)),
                })
            except Exception as error:
                logger.warning("Job completion write failed for %s: %s", job_id, error)

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
    """Download the enriched CSV for a completed job (owner only)."""
    job_id = req.route_params.get("jobId", "")
    if not job_id:
        return func.HttpResponse(
            json.dumps({"error": "Missing jobId"}),
            status_code=400,
            mimetype="application/json",
        )

    _, err = _require_job_owner(req, job_id)
    if err:
        return err

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
