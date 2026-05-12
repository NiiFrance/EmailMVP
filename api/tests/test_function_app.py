"""Tests for function_app module aligned to the current Azure OpenAI pipeline."""

import asyncio
import json
import sys
from types import ModuleType
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Inject fake Azure modules before importing function_app.
# ---------------------------------------------------------------------------


class DummyHttpResponse:
    def __init__(self, body=None, status_code=200, mimetype=None):
        self.body = body
        self.status_code = status_code
        self.mimetype = mimetype


_azure = ModuleType("azure")

_azure_functions = ModuleType("azure.functions")
_azure_functions.AuthLevel = MagicMock(ANONYMOUS="ANONYMOUS")
_azure_functions.HttpResponse = DummyHttpResponse
_azure_functions.HttpRequest = MagicMock()

_azure_durable = ModuleType("azure.durable_functions")
_mock_dfapp_instance = MagicMock()
for _decorator_name in ("route", "orchestration_trigger", "activity_trigger", "durable_client_input"):
    getattr(_mock_dfapp_instance, _decorator_name).return_value = lambda f: f
_azure_durable.DFApp = MagicMock(return_value=_mock_dfapp_instance)
_azure_durable.DurableOrchestrationContext = MagicMock()

_azure_storage = ModuleType("azure.storage")
_azure_storage_blob = ModuleType("azure.storage.blob")
_azure_storage_blob.BlobServiceClient = MagicMock()
_azure_storage_blob.generate_blob_sas = MagicMock(return_value="sas-token")
_azure_storage_blob.BlobSasPermissions = MagicMock()

_azure_identity = ModuleType("azure.identity")
_azure_identity.DefaultAzureCredential = MagicMock()

sys.modules["azure"] = _azure
sys.modules["azure.functions"] = _azure_functions
sys.modules["azure.durable_functions"] = _azure_durable
sys.modules["azure.storage"] = _azure_storage
sys.modules["azure.storage.blob"] = _azure_storage_blob
sys.modules["azure.identity"] = _azure_identity

import function_app as fa


def _mini_csv(num_rows: int = 2) -> bytes:
    """Build a CSV with enough columns to satisfy legacy field positions."""

    def col_letter(idx):
        result = ""
        while True:
            result = chr(idx % 26 + ord("A")) + result
            idx = idx // 26 - 1
            if idx < 0:
                break
        return result

    headers = [col_letter(i) for i in range(75)]
    lines = [",".join(headers)]
    for i in range(num_rows):
        row = [""] * 75
        row[0] = "M365 Renewal"
        row[1] = "Renew"
        row[10] = f"Lead{i}"
        row[11] = "Test"
        row[22] = f"Org{i}"
        lines.append(",".join(row))
    return "\n".join(lines).encode("utf-8")


class TestResolveTemplate:
    def test_resolve_builtin_template(self):
        template = fa._resolve_template({"id": "cold_email"})
        assert template["id"] == "cold_email"

    def test_resolve_unknown_raises(self):
        import pytest
        with pytest.raises(KeyError):
            fa._resolve_template({"id": "nonexistent"})

    def test_resolve_all_templates(self):
        for tid in ["cold_email", "csp_renewal_with_license", "csp_renewal_without_license",
                    "e7_upsell", "ea_to_csp", "leads", "marketplace", "price_change",
                    "cloud_ascent"]:
            template = fa._resolve_template({"id": tid})
            assert template["id"] == tid


class TestBlobHelpers:
    @patch.object(fa, "_blob_service")
    def test_upload_blob_calls_upload(self, mock_service):
        mock_container = MagicMock()
        mock_service.return_value.get_container_client.return_value = mock_container

        fa._upload_blob("test-container", "file.csv", b"data")

        mock_container.upload_blob.assert_called_once_with(name="file.csv", data=b"data", overwrite=True)

    @patch.object(fa, "_blob_service")
    def test_download_blob_returns_bytes(self, mock_service):
        mock_blob = MagicMock()
        mock_blob.download_blob.return_value.readall.return_value = b"csv content"
        mock_service.return_value.get_blob_client.return_value = mock_blob

        result = fa._download_blob("test-container", "file.csv")
        assert result == b"csv content"


class TestProcessLeadActivity:
    @staticmethod
    def _mock_completion(content: str):
        message = MagicMock(content=content)
        choice = MagicMock(message=message)
        return MagicMock(choices=[choice])

    def test_success_returns_parsed_for_cold_email(self):
        emails = [{"subject": f"Subject {i}", "body": f"Body {i}"} for i in range(1, 9)]

        with patch("function_app.AzureOpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = self._mock_completion(json.dumps(emails))
            mock_client_cls.return_value = mock_client

            result = fa.process_lead_activity(
                {
                    "lead_data": {
                        "row_index": 3,
                        "first_name": "Jane",
                        "last_name": "Doe",
                        "organization": "Contoso",
                        "license_renewal": "M365",
                        "engagement_objectives": "Renewal",
                    },
                    "template_config": {"id": "cold_email"},
                }
            )

        assert result["row_index"] == 3
        assert len(result["parsed"]) == 8
        assert result["parsed"][0]["subject"] == "Subject 1"

    def test_invalid_json_returns_error(self):
        with patch("function_app.AzureOpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = self._mock_completion("not-json")
            mock_client_cls.return_value = mock_client

            result = fa.process_lead_activity(
                {
                    "lead_data": {"row_index": 5, "first_name": "Jane"},
                    "template_config": {"id": "cold_email"},
                }
            )

        assert result["row_index"] == 5
        assert "Invalid JSON" in result["error"]

    def test_4_email_template(self):
        """Test processing with a 4-email template (e.g., csp_renewal_with_license)."""
        emails = [{"subject": f"Subject {i}", "body": f"Body {i}"} for i in range(1, 5)]

        with patch("function_app.AzureOpenAI") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.chat.completions.create.return_value = self._mock_completion(json.dumps(emails))
            mock_client_cls.return_value = mock_client

            result = fa.process_lead_activity(
                {
                    "lead_data": {
                        "row_index": 0,
                        "first_name": "Kofi",
                        "organization": "Acme",
                    },
                    "template_config": {"id": "csp_renewal_with_license"},
                }
            )

        assert result["row_index"] == 0
        assert len(result["parsed"]) == 4


class TestExtractLeadsActivity:
    @patch.object(fa, "_download_blob")
    def test_returns_lead_dicts(self, mock_download):
        mock_download.return_value = _mini_csv(3)

        leads = fa.extract_leads_activity({"job_id": "job-123", "column_map": None})

        assert len(leads) == 3
        assert leads[0]["first_name"] == "Lead0"
        assert leads[2]["organization"] == "Org2"
        mock_download.assert_called_once_with(fa.INPUT_CONTAINER, "job-123.csv")


class TestAssembleCsvActivity:
    @patch.object(fa, "_upload_blob")
    @patch.object(fa, "_download_blob")
    def test_uploads_enriched_csv(self, mock_download, mock_upload):
        mock_download.return_value = _mini_csv(1)
        results = [
            {
                "row_index": 0,
                "parsed": [{"subject": f"S{i}", "body": f"B{i}"} for i in range(1, 9)],
            }
        ]

        output = fa.assemble_csv_activity(
            {"job_id": "abc", "results": results, "template_config": {"id": "cold_email"}}
        )

        assert output == "abc.csv"
        mock_upload.assert_called_once()
        uploaded_bytes = mock_upload.call_args[0][2]
        assert b"Subject_Touch1" in uploaded_bytes
        assert b"S1" in uploaded_bytes


class TestTemplatesEndpoint:
    def test_get_templates_returns_registry(self):
        response = asyncio.run(fa.get_templates(MagicMock()))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert "templates" in payload
        assert any(item["id"] == "cold_email" for item in payload["templates"])


class TestSnovioEndpoints:
    @staticmethod
    def _request(body=None, route_params=None, params=None, headers=None):
        req = MagicMock()
        req.route_params = route_params or {}
        req.params = params or {}
        req.headers = headers or {}
        req.get_json.return_value = body or {}
        req.get_body.return_value = json.dumps(body or {}).encode("utf-8")
        return req

    def test_status_returns_configuration_without_secrets(self):
        response = asyncio.run(fa.get_snovio_status(MagicMock()))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload == {
            "configured": False,
            "apiBaseUrl": "https://api.snov.io",
            "rateLimitPerMinute": 60,
            "allowUnknownVerification": False,
            "webhookSecretConfigured": False,
            "templateMappingsConfigured": False,
        }

    def test_balance_requires_credentials(self):
        response = asyncio.run(fa.get_snovio_balance(MagicMock()))
        payload = json.loads(response.body)

        assert response.status_code == 503
        assert payload["configured"] is False
        assert "not configured" in payload["error"]

    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_balance_returns_snovio_payload(self, mock_configured, mock_client_factory):
        mock_client = MagicMock()
        mock_client.get_balance.return_value = {"success": True, "data": {"balance": "25000.00"}}
        mock_client_factory.return_value = mock_client

        response = asyncio.run(fa.get_snovio_balance(MagicMock()))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["configured"] is True
        assert payload["balance"]["data"]["balance"] == "25000.00"

    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_balance_maps_rate_limit_error(self, mock_configured, mock_client_factory):
        mock_client = MagicMock()
        mock_client.get_balance.side_effect = fa.SnovioAPIError("Snov.io request failed.", status_code=429)
        mock_client_factory.return_value = mock_client

        response = asyncio.run(fa.get_snovio_balance(MagicMock()))
        payload = json.loads(response.body)

        assert response.status_code == 429
        assert payload["statusCode"] == 429

    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_options_returns_lists_campaigns_and_fields(self, mock_configured, mock_client_factory):
        mock_client = MagicMock()
        mock_client.get_user_lists.return_value = [{"id": 1, "name": "Prospects"}]
        mock_client.get_user_campaigns.return_value = [{"id": 2, "campaign": "Paused", "status": "Paused"}]
        mock_client.get_custom_fields.return_value = [{"label": "Subject_Touch1"}]
        mock_client_factory.return_value = mock_client

        response = asyncio.run(fa.get_snovio_options(MagicMock()))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["configured"] is True
        assert payload["lists"][0]["name"] == "Prospects"
        assert payload["customFields"][0]["label"] == "Subject_Touch1"

    @patch.object(fa, "_download_job_csv", return_value=b"Email,First Name,Company\na@example.com,Ada,Contoso\n")
    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_preflight_estimates_job_usage(self, mock_configured, mock_client_factory, mock_download):
        mock_client = MagicMock()
        mock_client.get_balance.return_value = {"success": True, "data": {"balance": "10"}}
        mock_client_factory.return_value = mock_client
        req = self._request(params={"jobId": "job-1", "operation": "verify"})

        response = asyncio.run(fa.get_snovio_preflight(req))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["estimate"]["estimatedCredits"] == 1
        assert payload["lowCredit"] is False

    @patch.object(fa, "_download_job_csv", return_value=b"Email,First Name,Company\na@example.com,Ada,Contoso\n")
    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_verify_job_dry_run_does_not_call_snovio(self, mock_configured, mock_client_factory, mock_download):
        req = self._request(body={"dryRun": True}, route_params={"jobId": "job-1"})

        response = asyncio.run(fa.verify_job_emails(req))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["dryRun"] is True
        assert payload["estimate"]["estimatedCredits"] == 1
        mock_client_factory.assert_not_called()

    @patch.object(fa, "_upload_snovio_report", return_value="snovio-reports/job-1/sync.json")
    @patch.object(fa, "_download_job_csv", return_value=b"Email,First Name,Last Name,Company,Subject_Touch1,Body_Touch1\na@example.com,Ada,Lovelace,Contoso,S,B\n")
    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_sync_job_dry_run_reports_eligible_row(self, mock_configured, mock_client_factory, mock_download, mock_upload_report):
        mock_client = MagicMock()
        mock_client.get_user_campaigns.return_value = []
        mock_client.get_custom_fields.return_value = [{"label": "Subject_Touch1"}, {"label": "Body_Touch1"}]
        mock_client_factory.return_value = mock_client
        req = self._request(
            body={"listId": "123", "dryRun": True, "requireVerification": False},
            route_params={"jobId": "job-1"},
        )

        response = asyncio.run(fa.sync_job_to_snovio(req))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["summary"]["eligible"] == 1
        assert payload["rows"][0]["status"] == "skipped"
        mock_client.add_prospect_to_list.assert_not_called()

    @patch.object(fa, "_upload_snovio_report", return_value="snovio-reports/job-1/sync.json")
    @patch.object(fa, "_download_job_csv", return_value=b"Email,First Name,Last Name,Company\na@example.com,Ada,Lovelace,Contoso\n")
    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_sync_job_uses_selected_campaign_list_id(self, mock_configured, mock_client_factory, mock_download, mock_upload_report):
        mock_client = MagicMock()
        mock_client.get_user_campaigns.return_value = [{"id": "7", "campaign": "Help", "status": "Paused", "list_id": 999}]
        mock_client.get_custom_fields.return_value = []
        mock_client_factory.return_value = mock_client
        req = self._request(
            body={"campaignId": "7", "dryRun": True, "requireVerification": False},
            route_params={"jobId": "job-1"},
        )

        response = asyncio.run(fa.sync_job_to_snovio(req))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["listId"] == "999"
        assert payload["listSource"] == "campaign"
        assert payload["plannedListCreation"] is False

    @patch.object(fa, "_upload_snovio_report", return_value="snovio-reports/job-1/sync.json")
    @patch.object(fa, "_download_job_csv", return_value=b"Email,First Name,Last Name,Company\na@example.com,Ada,Lovelace,Contoso\n")
    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_sync_job_dry_run_plans_auto_created_list(self, mock_configured, mock_client_factory, mock_download, mock_upload_report):
        mock_client = MagicMock()
        mock_client.get_custom_fields.return_value = []
        mock_client_factory.return_value = mock_client
        req = self._request(
            body={
                "autoCreateList": True,
                "dryRun": True,
                "requireVerification": False,
                "templateName": "Help & Assistance - Leads",
                "sourceFileName": "inbound.csv",
            },
            route_params={"jobId": "job-1"},
        )

        response = asyncio.run(fa.sync_job_to_snovio(req))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["listId"] == ""
        assert payload["listSource"] == "planned_create"
        assert payload["plannedListCreation"] is True
        assert payload["listName"].startswith("Cloudware - Help & Assistance - Leads - inbound")
        mock_client.create_prospect_list.assert_not_called()

    @patch.object(fa, "_upload_snovio_report", return_value="snovio-reports/job-1/sync.json")
    @patch.object(fa, "_download_job_csv", return_value=b"Email,First Name,Last Name,Company\na@example.com,Ada,Lovelace,Contoso\n")
    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_sync_job_live_creates_list_before_sync(self, mock_configured, mock_client_factory, mock_download, mock_upload_report):
        mock_client = MagicMock()
        mock_client.create_prospect_list.return_value = [{"success": True, "data": {"id": 321}}]
        mock_client.get_custom_fields.return_value = []
        mock_client.get_prospects_by_email.return_value = {"data": []}
        mock_client.add_prospect_to_list.return_value = {"success": True, "id": "prospect-1", "added": True}
        mock_client_factory.return_value = mock_client
        req = self._request(
            body={"autoCreateList": True, "dryRun": False, "requireVerification": False, "listName": "Cloudware Test Leads"},
            route_params={"jobId": "job-1"},
        )

        response = asyncio.run(fa.sync_job_to_snovio(req))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["listId"] == "321"
        assert payload["listSource"] == "created"
        assert payload["createdList"][0]["data"]["id"] == 321
        assert payload["rows"][0]["status"] == "added"
        mock_client.create_prospect_list.assert_called_once_with("Cloudware Test Leads")
        mock_client.add_prospect_to_list.assert_called_once()

    @patch.object(fa, "_upload_snovio_report", return_value="snovio-reports/job-1/sync.json")
    @patch.object(fa, "_download_job_csv", return_value=b"Email,First Name,Last Name,Company\na@example.com,Ada,Lovelace,Contoso\n")
    @patch.object(fa, "_snovio_client")
    @patch.object(fa, "_snovio_configured", return_value=True)
    def test_sync_job_does_not_create_list_when_no_rows_are_eligible(self, mock_configured, mock_client_factory, mock_download, mock_upload_report):
        mock_client = MagicMock()
        mock_client.get_custom_fields.return_value = []
        mock_client_factory.return_value = mock_client
        req = self._request(
            body={"autoCreateList": True, "dryRun": False, "requireVerification": True, "listName": "Cloudware Empty"},
            route_params={"jobId": "job-1"},
        )

        response = asyncio.run(fa.sync_job_to_snovio(req))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["listId"] == ""
        assert payload["listSource"] == "planned_create"
        assert payload["plannedListCreation"] is True
        assert payload["rows"][0]["blockedReason"] == "verification_required"
        mock_client.create_prospect_list.assert_not_called()
        mock_client.add_prospect_to_list.assert_not_called()

    @patch.object(fa, "_upload_blob")
    def test_webhook_requires_shared_secret_and_persists_event(self, mock_upload):
        req = self._request(
            body={"event_object": "campaign_email", "event_action": "sent"},
            params={"token": "secret"},
        )

        with patch.object(fa, "SNOVIO_WEBHOOK_SECRET", "secret"):
            response = asyncio.run(fa.receive_snovio_webhook(req))
        payload = json.loads(response.body)

        assert response.status_code == 200
        assert payload["accepted"] is True
        mock_upload.assert_called_once()


class TestConfiguration:
    def test_batch_size_default(self):
        assert fa.BATCH_SIZE == 100

    def test_max_csv_size(self):
        assert fa.MAX_CSV_SIZE_BYTES == 50 * 1024 * 1024

    def test_default_model(self):
        assert fa.AZURE_OPENAI_DEPLOYMENT == "gpt-5.5"

    def test_snovio_rate_limit_default(self):
        assert fa.SNOVIO_REQUESTS_PER_MINUTE == 60

    def test_snovio_base_url_default(self):
        assert fa.SNOVIO_API_BASE_URL == "https://api.snov.io"
