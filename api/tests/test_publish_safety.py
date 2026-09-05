import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

import tests.test_function_app as fixture

fa = fixture.fa


def client_for_sync():
    client = MagicMock()
    client.get_user_campaigns.return_value = []
    client.get_custom_fields.return_value = [{"label": "Subject_Touch1"}, {"label": "Body_Touch1"}]
    client.get_prospects_by_email.return_value = {"data": []}
    client.add_prospect_to_list.return_value = {"success": True}
    return client


@pytest.mark.parametrize("dry_run", [True, False])
def test_failed_drafts_and_signature_addresses_are_blocked(dry_run):
    client = client_for_sync()
    csv = b"Email,Subject_Touch1,Body_Touch1\nqa@example.com,Generation unavailable,Error\n,Hello,Contact seller@example.com\n"
    report, error = fa._run_prospect_sync(client, "job", {"listId": "123", "dryRun": dry_run}, csv_bytes=csv)
    assert error is None
    assert report["summary"]["blocked"] == 2
    assert report["summary"]["eligible"] == 0
    client.add_prospect_to_list.assert_not_called()
    client.create_prospect_list.assert_not_called()


def test_duplicate_rows_are_not_imported_twice():
    client = client_for_sync()
    csv = b"Email,Subject_Touch1,Body_Touch1\nqa@example.com,Hello,Body\nQA@example.com,Hello,Body\n"
    report, error = fa._run_prospect_sync(client, "job", {"listId": "123", "dryRun": False}, csv_bytes=csv)
    assert error is None
    assert report["summary"]["added"] == 1
    assert report["summary"]["blocked"] == 1
    client.add_prospect_to_list.assert_called_once()


def test_missing_recipient_recovery_disables_duplicates_and_verifies_membership():
    client = client_for_sync()
    client.get_prospects_by_email.side_effect = [{"data": []}, {"data": [{"lists": [{"id": 123}]}]}]
    report, error = fa._run_prospect_sync(client, "job", {"listId": "123", "dryRun": False, "_noDuplicateRows": [0]},
        csv_bytes=b"Email,Subject_Touch1,Body_Touch1\nqa@example.com,Hi,Body\n")
    assert error is None
    assert report["summary"]["added"] == 1
    assert client.add_prospect_to_list.call_args.args[1]["createDuplicates"] is False
    assert client.get_prospects_by_email.call_count == 2


def test_recovery_does_not_update_another_lists_prospect():
    client = client_for_sync()
    client.get_prospects_by_email.return_value = {"data": [{"lists": [{"id": 999}]}]}
    report, error = fa._run_prospect_sync(client, "job", {"listId": "123", "dryRun": False, "_noDuplicateRows": [0]},
        csv_bytes=b"Email,Subject_Touch1,Body_Touch1\nqa@example.com,Hi,Body\n")
    assert report["summary"]["failed"] == 1
    client.add_prospect_to_list.assert_not_called()


def test_lookup_failure_is_not_classified_as_an_ambiguous_write():
    client = client_for_sync()
    client.get_prospects_by_email.side_effect = fa.SnovioAPIError("Lookup unavailable")
    report, error = fa._run_prospect_sync(client, "job", {"listId": "123", "dryRun": False},
        csv_bytes=b"Email,Subject_Touch1,Body_Touch1\nqa@example.com,Hello,Body\n")
    assert error is None
    assert report["rows"][0]["status"] == "failed"
    assert not report["rows"][0].get("uncertain")
    client.add_prospect_to_list.assert_not_called()


def test_active_destination_blocked_without_selected_campaign():
    client = client_for_sync()
    client.get_user_campaigns.return_value = [{"id": 9, "status": "Active", "list_id": 123}]
    report, error = fa._run_prospect_sync(client, "job", {
        "listId": "123", "dryRun": False, "confirmActiveCampaign": True
    }, csv_bytes=b"Email\nqa@example.com\n")
    assert error.status_code == 409
    client.add_prospect_to_list.assert_not_called()


def test_missing_custom_fields_block_before_list_creation():
    client = client_for_sync()
    client.get_custom_fields.return_value = []
    report, error = fa._run_prospect_sync(client, "job", {"dryRun": False},
        csv_bytes=b"Email,Subject_Touch1,Body_Touch1\nqa@example.com,Hi,Body\n")
    assert report["summary"]["blocked"] == 1
    assert "Missing Snov.io" in report["rows"][0]["blockedReason"]
    client.create_prospect_list.assert_not_called()


def test_stale_operation_cannot_update_job():
    table = MagicMock()
    table.get_entity.return_value = {"snovioSyncOperationId": "newer"}
    with patch.object(fa.data_store, "_table", return_value=table):
        assert not fa.data_store.update_snovio_operation("owner", "job", "older", {"snovioSyncStatus": "completed"})
    table.update_entity.assert_not_called()


def test_builder_requires_admin_before_model_call():
    with patch.object(fa, "_require_admin", return_value=(None, fa._json_response({"error": "Forbidden"}, 403))), \
            patch.object(fa, "AzureOpenAI") as model:
        response = asyncio.run(fa.preview_campaign_brief(MagicMock()))
    assert response.status_code == 403
    model.assert_not_called()


def test_status_rejects_another_operation():
    request = MagicMock(route_params={"jobId": "job", "operationId": "someone-else"})
    with patch.object(fa, "_require_job_owner", return_value=({"oid": "owner", "job": {
        "snovioSyncOperationId": "mine"
    }}, None)), patch.object(fa, "_download_blob") as download:
        response = asyncio.run(fa.get_snovio_sync_status(request))
    assert response.status_code == 404
    download.assert_not_called()


def test_unpublished_template_is_hidden_from_sales():
    fields, error = fa._validate_campaign_payload({"name": "Test", "numEmails": 2,
        "systemPrompt": "Test prompt", "publicationStatus": "draft"})
    assert not error
    assert fields["archived"] is True


def test_generation_schema_and_snapshot_survive_configuration_changes():
    template = fa.get_template("leads")
    snapshot = fa.template_snapshot(template)
    with patch.object(fa, "get_template", side_effect=RuntimeError("Mutable registry unavailable")):
        resolved = fa._resolve_template(snapshot)
    assert resolved["num_emails"] == template["num_emails"]
    assert resolved["system_prompt"] == template["system_prompt"]