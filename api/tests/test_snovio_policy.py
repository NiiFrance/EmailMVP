"""Tests for server-enforced Snov.io MCP tool classification."""

import pytest

import snovio_policy
from snovio_policy import classify_tool, summarize_action


@pytest.mark.parametrize("name", [
    "app_get_lists", "app_list_prospects", "crm_search_deals", "app_bulk_verification_status",
])
def test_read_tools_execute_without_confirmation(name):
    policy = classify_tool(name)
    assert policy.executable is True
    assert policy.requires_confirmation is False
    assert policy.admin_only is False


@pytest.mark.parametrize("name", [
    "app_verify_email", "app_bulk_verify_emails", "app_find_email",
    "app_database_search_prospects_add_to_list", "app_database_search_companies",
])
def test_credit_tools_require_confirmation(name):
    policy = classify_tool(name)
    assert policy.category == "credit"
    assert policy.requires_confirmation is True


@pytest.mark.parametrize("name", [
    "app_delete_list", "app_remove_prospects_from_list", "crm_delete_deals",
])
def test_destructive_tools_require_confirmation(name):
    assert classify_tool(name).requires_confirmation is True


@pytest.mark.parametrize("name", [
    "campaign_set_state", "li_send_invite", "li_send_message", "unibox_reply",
    "li_pending_settings_update", "pipelines_account_update", "senders_connect_smtp",
])
def test_outbound_and_account_tools_are_admin_only(name):
    policy = classify_tool(name)
    assert policy.requires_confirmation is True
    assert policy.admin_only is True


def test_unknown_future_tool_is_discoverable_but_not_executable():
    policy = classify_tool("app_quantum_prospect_action")
    assert policy.category == "unknown"
    assert policy.executable is False


def test_every_reviewed_live_catalog_tool_is_classified():
    assert len(snovio_policy._REVIEWED_TOOLS) == 181
    unknown = sorted(
        tool for tool in snovio_policy._REVIEWED_TOOLS
        if not classify_tool(tool).executable
    )
    assert unknown == []


def test_future_tool_in_known_namespace_remains_default_denied():
    policy = classify_tool("campaign_launch_everything_new")
    assert policy.category == "unknown"
    assert policy.executable is False


def test_summary_counts_batches_without_dumping_values():
    summary = summarize_action("app_bulk_verify_emails", {
        "emails": ["one@example.com", "two@example.com"], "campaignId": "55",
    })
    assert "emails=2 item(s)" in summary
    assert "one@example.com" not in summary
    assert "campaignId=55" in summary