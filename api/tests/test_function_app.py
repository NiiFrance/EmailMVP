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


class TestConfiguration:
    def test_batch_size_default(self):
        assert fa.BATCH_SIZE == 100

    def test_max_csv_size(self):
        assert fa.MAX_CSV_SIZE_BYTES == 50 * 1024 * 1024

    def test_default_model(self):
        assert fa.AZURE_OPENAI_DEPLOYMENT == "gpt-5.5"
