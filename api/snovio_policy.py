"""Server-side policy classification for dynamically discovered Snov.io MCP tools."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPolicy:
    category: str
    requires_confirmation: bool
    admin_only: bool = False
    executable: bool = True


_OUTBOUND_MARKERS = (
    "send_connection", "send_invite", "send_message", "send_inmail",
    "linkedin_message", "connection_invite", "like_post", "endorse_skill",
    "visit_profile", "launch_campaign",
)
_ACCOUNT_MARKERS = (
    "linkedin_account", "proxy", "team_slot", "daily_limit", "safety_limit",
    "server_location", "warm_up", "warmup",
)
_CREDIT_MARKERS = (
    "verify_email", "bulk_verify", "find_email", "enrich", "domain_search",
    "database_search_prospects_add_to_list", "web_search",
)
_DESTRUCTIVE_MARKERS = (
    "delete_", "remove_", "archive_", "mark_lost", "unsubscribe",
)
_WRITE_MARKERS = (
    "create_", "update_", "edit_", "rename_", "move_", "add_", "set_",
    "restore_", "reorder_", "mark_", "link_", "complete_", "connect_",
    "assign_", "save_", "sync_", "parse_", "export_",
)
_READ_PREFIXES = ("app_get_", "app_list_", "app_search_", "app_check_", "app_view_")
_READ_SUFFIXES = ("_status", "_summary", "_history", "_timeline", "_filters")


def classify_tool(tool_name: str) -> ToolPolicy:
    """Classify a live MCP tool. Unknown tools remain discoverable but blocked."""
    name = str(tool_name or "").strip().lower()
    if not name.startswith("app_"):
        return ToolPolicy("unknown", False, executable=False)
    if any(marker in name for marker in _OUTBOUND_MARKERS):
        return ToolPolicy("outbound", True, admin_only=True)
    if any(marker in name for marker in _ACCOUNT_MARKERS):
        return ToolPolicy("account", True, admin_only=True)
    if any(marker in name for marker in _CREDIT_MARKERS):
        return ToolPolicy("credit", True)
    if any(marker in name for marker in _DESTRUCTIVE_MARKERS):
        return ToolPolicy("destructive", True)
    if any(marker in name for marker in _WRITE_MARKERS):
        return ToolPolicy("write", True)
    if name.startswith(_READ_PREFIXES) or name.endswith(_READ_SUFFIXES):
        return ToolPolicy("read", False)
    return ToolPolicy("unknown", False, executable=False)


def summarize_action(tool_name: str, arguments: dict) -> str:
    """Build a bounded, non-secret summary for the confirmation UI."""
    parts = [tool_name]
    for key in (
        "name", "title", "email", "list_id", "listId", "campaign_id", "campaignId",
        "pipeline_id", "deal_id", "linkedin_url", "profile_url",
    ):
        value = arguments.get(key)
        if value not in (None, "", []):
            parts.append(f"{key}={str(value)[:80]}")
    for key in ("emails", "prospects", "recipients", "items", "urls"):
        value = arguments.get(key)
        if isinstance(value, list):
            parts.append(f"{key}={len(value)} item(s)")
    return " | ".join(parts)[:500]