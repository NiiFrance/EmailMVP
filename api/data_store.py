"""Table Storage data layer — users, jobs, Snov.io credentials, campaigns.

Backs the multi-user features: per-user workspaces (job history + resume),
persisted Snov.io credentials, roles, and admin-editable campaign templates.
Uses the same managed-identity pattern as the blob helpers in function_app.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone

from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode
from azure.identity import DefaultAzureCredential

logger = logging.getLogger("emailmvp")

STORAGE_ACCOUNT_NAME = os.environ.get("AzureWebJobsStorage__accountName", "")
STORAGE_CLIENT_ID = os.environ.get("AzureWebJobsStorage__clientId", "")
STORAGE_CONN_STR = os.environ.get("STORAGE_CONNECTION_STRING", os.environ.get("AzureWebJobsStorage", ""))

USERS_TABLE = "Users"
JOBS_TABLE = "Jobs"
SNOVIO_CREDS_TABLE = "SnovioCreds"
CAMPAIGNS_TABLE = "Campaigns"

_service: TableServiceClient | None = None
_tables_ready: set[str] = set()


def _table_service() -> TableServiceClient:
    global _service
    if _service is None:
        if STORAGE_ACCOUNT_NAME:
            credential = (
                DefaultAzureCredential(managed_identity_client_id=STORAGE_CLIENT_ID)
                if STORAGE_CLIENT_ID
                else DefaultAzureCredential()
            )
            _service = TableServiceClient(
                endpoint=f"https://{STORAGE_ACCOUNT_NAME}.table.core.windows.net",
                credential=credential,
            )
        else:
            _service = TableServiceClient.from_connection_string(STORAGE_CONN_STR)
    return _service


def _table(name: str):
    if name not in _tables_ready:
        try:
            _table_service().create_table_if_not_exists(name)
        except Exception as error:  # table may already exist or racing creation
            logger.debug("create_table_if_not_exists(%s): %s", name, error)
        _tables_ready.add(name)
    return _table_service().get_table_client(name)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _entity_to_dict(entity) -> dict:
    return {key: value for key, value in dict(entity).items()}


# ---------------------------------------------------------------------------
# Users — PartitionKey "user", RowKey = oid
# ---------------------------------------------------------------------------

def get_user(oid: str) -> dict | None:
    try:
        return _entity_to_dict(_table(USERS_TABLE).get_entity("user", oid))
    except ResourceNotFoundError:
        return None


def upsert_user(oid: str, email: str, name: str, role: str) -> dict:
    """Create or refresh a user row; preserves an existing role unless upgraded."""
    existing = get_user(oid)
    entity = {
        "PartitionKey": "user",
        "RowKey": oid,
        "email": email,
        "name": name,
        "role": role,
        "lastLoginAt": _now_iso(),
    }
    if existing:
        entity["createdAt"] = existing.get("createdAt", _now_iso())
        if "lastContext" in existing:
            entity["lastContext"] = existing["lastContext"]
    else:
        entity["createdAt"] = _now_iso()
    _table(USERS_TABLE).upsert_entity(entity, mode=UpdateMode.MERGE)
    return entity


def set_user_role(oid: str, role: str) -> bool:
    if get_user(oid) is None:
        return False
    _table(USERS_TABLE).upsert_entity(
        {"PartitionKey": "user", "RowKey": oid, "role": role}, mode=UpdateMode.MERGE
    )
    return True


def set_user_context(oid: str, context: dict) -> None:
    _table(USERS_TABLE).upsert_entity(
        {"PartitionKey": "user", "RowKey": oid, "lastContext": json.dumps(context)},
        mode=UpdateMode.MERGE,
    )


def list_users() -> list[dict]:
    entities = _table(USERS_TABLE).query_entities("PartitionKey eq 'user'")
    return [_entity_to_dict(e) for e in entities]


# ---------------------------------------------------------------------------
# Jobs — PartitionKey = oid, RowKey = jobId
# ---------------------------------------------------------------------------

def record_job(oid: str, job_id: str, fields: dict) -> None:
    entity = {"PartitionKey": oid, "RowKey": job_id, "createdAt": _now_iso(), **fields}
    _table(JOBS_TABLE).upsert_entity(entity, mode=UpdateMode.MERGE)


def update_job(oid: str, job_id: str, fields: dict) -> None:
    entity = {"PartitionKey": oid, "RowKey": job_id, **fields}
    _table(JOBS_TABLE).upsert_entity(entity, mode=UpdateMode.MERGE)


def get_job(oid: str, job_id: str) -> dict | None:
    try:
        return _entity_to_dict(_table(JOBS_TABLE).get_entity(oid, job_id))
    except ResourceNotFoundError:
        return None


def list_jobs(oid: str, limit: int = 25) -> list[dict]:
    entities = _table(JOBS_TABLE).query_entities(f"PartitionKey eq '{oid}'")
    jobs = [_entity_to_dict(e) for e in entities]
    jobs.sort(key=lambda j: str(j.get("createdAt", "")), reverse=True)
    return jobs[:limit]


# ---------------------------------------------------------------------------
# Snov.io credentials — PartitionKey "snovio", RowKey = oid
# ---------------------------------------------------------------------------

def save_snovio_creds(oid: str, client_id: str, secret_value: str, secret_encrypted: bool) -> None:
    _table(SNOVIO_CREDS_TABLE).upsert_entity(
        {
            "PartitionKey": "snovio",
            "RowKey": oid,
            "clientId": client_id,
            "clientSecret": secret_value,
            "secretEncrypted": secret_encrypted,
            "updatedAt": _now_iso(),
        },
        mode=UpdateMode.REPLACE,
    )


def get_snovio_creds(oid: str) -> dict | None:
    try:
        return _entity_to_dict(_table(SNOVIO_CREDS_TABLE).get_entity("snovio", oid))
    except ResourceNotFoundError:
        return None


def delete_snovio_creds(oid: str) -> None:
    try:
        _table(SNOVIO_CREDS_TABLE).delete_entity("snovio", oid)
    except ResourceNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Snov.io MCP OAuth — client registration, per-user tokens, and CSRF states.
# Stored in the SnovioCreds table under dedicated partitions.
# ---------------------------------------------------------------------------

def get_mcp_client_registration(host: str) -> dict | None:
    try:
        return _entity_to_dict(_table(SNOVIO_CREDS_TABLE).get_entity("snoviomcpclient", host))
    except ResourceNotFoundError:
        return None


def save_mcp_client_registration(host: str, client_id: str, redirect_uri: str) -> None:
    _table(SNOVIO_CREDS_TABLE).upsert_entity(
        {
            "PartitionKey": "snoviomcpclient",
            "RowKey": host,
            "clientId": client_id,
            "redirectUri": redirect_uri,
            "updatedAt": _now_iso(),
        },
        mode=UpdateMode.REPLACE,
    )


def save_mcp_state(state: str, oid: str, code_verifier: str, redirect_uri: str, client_id: str) -> None:
    _table(SNOVIO_CREDS_TABLE).upsert_entity(
        {
            "PartitionKey": "snoviomcpstate",
            "RowKey": state,
            "oid": oid,
            "codeVerifier": code_verifier,
            "redirectUri": redirect_uri,
            "clientId": client_id,
            "createdAt": _now_iso(),
        },
        mode=UpdateMode.REPLACE,
    )


def pop_mcp_state(state: str) -> dict | None:
    """Fetch and delete an OAuth state row (single use)."""
    table = _table(SNOVIO_CREDS_TABLE)
    try:
        entity = _entity_to_dict(table.get_entity("snoviomcpstate", state))
    except ResourceNotFoundError:
        return None
    try:
        table.delete_entity("snoviomcpstate", state)
    except ResourceNotFoundError:
        pass
    return entity


def save_mcp_tokens(oid: str, access_token: str, refresh_token: str, expires_at: float, encrypted: bool, client_id: str = "") -> None:
    _table(SNOVIO_CREDS_TABLE).upsert_entity(
        {
            "PartitionKey": "snoviomcp",
            "RowKey": oid,
            "accessToken": access_token,
            "refreshToken": refresh_token,
            "expiresAt": float(expires_at),
            "tokensEncrypted": encrypted,
            "clientId": client_id,
            "updatedAt": _now_iso(),
        },
        mode=UpdateMode.REPLACE,
    )


def get_mcp_tokens(oid: str) -> dict | None:
    try:
        return _entity_to_dict(_table(SNOVIO_CREDS_TABLE).get_entity("snoviomcp", oid))
    except ResourceNotFoundError:
        return None


def delete_mcp_tokens(oid: str) -> None:
    try:
        _table(SNOVIO_CREDS_TABLE).delete_entity("snoviomcp", oid)
    except ResourceNotFoundError:
        pass


# ---------------------------------------------------------------------------
# Campaigns — PartitionKey "campaign", RowKey = campaign id
# ---------------------------------------------------------------------------

def list_campaign_entities(include_archived: bool = False) -> list[dict]:
    entities = _table(CAMPAIGNS_TABLE).query_entities("PartitionKey eq 'campaign'")
    campaigns = [_entity_to_dict(e) for e in entities]
    if not include_archived:
        campaigns = [c for c in campaigns if not c.get("archived")]
    campaigns.sort(key=lambda c: (str(c.get("group", "")), str(c.get("name", ""))))
    return campaigns


def get_campaign_entity(campaign_id: str) -> dict | None:
    try:
        return _entity_to_dict(_table(CAMPAIGNS_TABLE).get_entity("campaign", campaign_id))
    except ResourceNotFoundError:
        return None


def upsert_campaign_entity(campaign_id: str, fields: dict) -> None:
    entity = {"PartitionKey": "campaign", "RowKey": campaign_id, **fields}
    _table(CAMPAIGNS_TABLE).upsert_entity(entity, mode=UpdateMode.MERGE)


def campaigns_table_empty() -> bool:
    entities = _table(CAMPAIGNS_TABLE).query_entities("PartitionKey eq 'campaign'", results_per_page=1)
    for _ in entities:
        return False
    return True
