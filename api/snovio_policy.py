"""Server-side policy classification for dynamically discovered Snov.io MCP tools."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolPolicy:
    category: str
    requires_confirmation: bool
    admin_only: bool = False
    executable: bool = True


_REVIEWED_TOOLS = frozenset("""
app_add_companies_to_list app_add_list_to_folder app_add_prospect
app_add_prospects_to_list app_bulk_verification_save_to_list
app_bulk_verification_status app_bulk_verify_emails app_check_linkedin_search
app_check_list_export app_check_list_usage app_create_deals app_create_folder
app_create_list app_database_search_ai app_database_search_companies
app_database_search_companies_add_to_list app_database_search_filters
app_database_search_prospects app_database_search_prospects_add_to_list
app_delete_folder app_delete_list app_domain_search app_domain_search_add_to_list
app_domain_search_company_data app_export_list app_find_email
app_find_email_add_to_list app_get_company_lists app_get_email_providers_stats
app_get_folders app_get_list_export_fields app_get_lists app_get_prospect
app_get_team_users app_get_user_info app_get_verified_emails
app_linkedin_search_by_filters app_linkedin_search_by_url app_list_prospects
app_move_list app_remove_prospects_from_list app_rename_folder app_rename_list
app_reorder_folder app_restore_list app_search_company_domain app_search_lists
app_suggest_folder_name app_update_prospect app_verified_emails_add_to_list
app_verify_email campaign_add_recipients campaign_create campaign_duplicate
campaign_export campaign_folder_manage campaign_get campaign_linkedin_senders
campaign_list campaign_prechecks campaign_preview_for_prospect
campaign_recipients_manage campaign_recipients_report campaign_rename
campaign_reports campaign_save_as_template campaign_schedule_manage
campaign_schedules_list campaign_sequence_update campaign_set_state campaign_stats
campaign_step_content_set campaign_template_categories campaign_templates_find
crm_add_deal_note crm_add_deal_participant crm_create_deal crm_create_funnel
crm_create_funnel_status crm_create_lost_reason crm_delete_deal_note
crm_delete_deals crm_delete_funnel crm_delete_funnel_status crm_delete_lost_reason
crm_edit_deal_note crm_get_colors crm_get_currencies crm_get_deal
crm_get_deal_timeline crm_get_funnel_statuses crm_get_funnels
crm_get_lost_reasons crm_list_deals crm_move_deals crm_reorder_funnels
crm_search_deals crm_update_deal crm_update_funnel crm_update_funnel_status
crm_update_lost_reason li_check_connection_level li_check_invite li_endorse_skills
li_enqueue_inline_message li_enqueue_parse_chats li_enqueue_parse_network
li_enqueue_parse_pending li_follow li_get_chat_messages li_get_task_result
li_in_mail li_like_recent_post li_network_export_start li_network_export_status
li_network_list li_network_parse_status li_parse_profile_create_prospect
li_parse_profile_set_task_state li_pending_list li_pending_parse_status
li_pending_settings_update li_send_inline_message_realtime li_send_invite
li_send_message li_unread_replies li_visit_profile pipelines_account_assign
pipelines_account_create pipelines_account_delete pipelines_account_location_update
pipelines_account_premium_update pipelines_account_retract
pipelines_account_settings_update pipelines_account_show pipelines_account_ssi_update
pipelines_account_stats_update pipelines_account_status_check
pipelines_account_teamwork_update pipelines_account_timezone_update
pipelines_account_unread_update pipelines_account_update pipelines_accounts_list_all
pipelines_accounts_list_connected pipelines_accounts_list_team
pipelines_addons_summary pipelines_get_countries pipelines_get_timezones
pipelines_proxy_custom_update pipelines_proxy_validate pipelines_request_accept
pipelines_request_create pipelines_request_reject pipelines_request_withdraw
pipelines_requests_list pipelines_trial_status pipelines_warmup_update
senders_bulk_manage senders_connect_smtp senders_domain_health senders_list
senders_manage senders_smtp_settings_lookup senders_update_smtp task_create_event
task_delete_events task_edit_event task_get_event task_get_event_types
task_get_events unibox_assign_prospect unibox_bounced_manage unibox_filters
unibox_find_thread_by_prospect unibox_reply unibox_source_add
unibox_source_update unibox_thread_delete unibox_thread_mark unibox_thread_read
unibox_threads_list
""".split())

_OUTBOUND_TOOLS = frozenset({
    "campaign_set_state", "li_endorse_skills", "li_enqueue_inline_message",
    "li_follow", "li_in_mail", "li_like_recent_post",
    "li_send_inline_message_realtime", "li_send_invite", "li_send_message",
    "li_visit_profile", "unibox_reply",
})
_ADMIN_READ_TOOLS = frozenset({
    "campaign_linkedin_senders", "pipelines_account_show",
    "pipelines_account_status_check", "pipelines_accounts_list_all",
    "pipelines_accounts_list_connected", "pipelines_accounts_list_team",
    "pipelines_addons_summary", "pipelines_get_countries", "pipelines_get_timezones",
    "pipelines_requests_list", "pipelines_trial_status", "senders_domain_health",
    "senders_list", "senders_smtp_settings_lookup",
})
_ACCOUNT_TOOLS = frozenset(
    tool for tool in _REVIEWED_TOOLS
    if tool.startswith(("pipelines_", "senders_")) and tool not in _ADMIN_READ_TOOLS
) | {"li_pending_settings_update"}
_CREDIT_TOOLS = frozenset({
    "app_database_search_ai", "app_database_search_companies",
    "app_database_search_prospects", "app_linkedin_search_by_filters",
    "app_linkedin_search_by_url", "li_network_export_start",
})
_READ_TOOLS = frozenset({
    "app_suggest_folder_name", "campaign_get", "campaign_list",
    "campaign_prechecks", "campaign_preview_for_prospect",
    "campaign_recipients_report", "campaign_reports", "campaign_schedules_list",
    "campaign_stats", "campaign_template_categories", "campaign_templates_find",
    "li_network_list", "li_pending_list", "li_unread_replies",
    "unibox_find_thread_by_prospect", "unibox_thread_read", "unibox_threads_list",
})
_WRITE_TOOLS = frozenset({
    "campaign_add_recipients", "campaign_create", "campaign_duplicate",
    "campaign_export", "campaign_folder_manage", "campaign_recipients_manage",
    "campaign_rename", "campaign_save_as_template", "campaign_schedule_manage",
    "campaign_sequence_update", "campaign_step_content_set",
    "unibox_bounced_manage", "unibox_source_add", "unibox_source_update",
    "unibox_thread_delete", "unibox_thread_mark",
})


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
_READ_PREFIXES = (
    "app_get_", "app_list_", "app_search_", "app_check_", "app_view_",
    "crm_get_", "crm_list_", "crm_search_", "li_check_", "li_get_", "task_get_",
)
_READ_SUFFIXES = ("_status", "_summary", "_history", "_timeline", "_filters")


def classify_tool(tool_name: str) -> ToolPolicy:
    """Classify a live MCP tool. Unknown tools remain discoverable but blocked."""
    name = str(tool_name or "").strip().lower()
    if name not in _REVIEWED_TOOLS:
        return ToolPolicy("unknown", False, executable=False)
    if name in _OUTBOUND_TOOLS:
        return ToolPolicy("outbound", True, admin_only=True)
    if name in _ADMIN_READ_TOOLS:
        return ToolPolicy("read", False, admin_only=True)
    if name in _ACCOUNT_TOOLS:
        return ToolPolicy("account", True, admin_only=True)
    if name in _CREDIT_TOOLS:
        return ToolPolicy("credit", True)
    if any(marker in name for marker in _OUTBOUND_MARKERS):
        return ToolPolicy("outbound", True, admin_only=True)
    if any(marker in name for marker in _ACCOUNT_MARKERS):
        return ToolPolicy("account", True, admin_only=True)
    if any(marker in name for marker in _CREDIT_MARKERS):
        return ToolPolicy("credit", True)
    if any(marker in name for marker in _DESTRUCTIVE_MARKERS):
        return ToolPolicy("destructive", True)
    if name in _WRITE_TOOLS:
        return ToolPolicy("write", True)
    if any(marker in name for marker in _WRITE_MARKERS):
        return ToolPolicy("write", True)
    if name in _READ_TOOLS or name.startswith(_READ_PREFIXES) or name.endswith(_READ_SUFFIXES):
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