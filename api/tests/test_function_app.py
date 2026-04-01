"""Tests for function_app module — unit tests with mocked Azure/Anthropic dependencies."""

import json
import io
import sys
from unittest.mock import patch, MagicMock, AsyncMock
from types import ModuleType

import pytest

# ---------------------------------------------------------------------------
# We must inject mock modules BEFORE importing function_app, because it
# unconditionally imports azure.functions, azure.durable_functions, etc.
# Using [] assignment (not setdefault) so we overwrite any stale entries.
# ---------------------------------------------------------------------------

# Build a fake azure package hierarchy
_azure = ModuleType("azure")
_azure.functions = MagicMock()
_azure.durable_functions = MagicMock()

_azure_storage = ModuleType("azure.storage")
_azure_storage.blob = MagicMock()
_azure.storage = _azure_storage

# DFApp must behave like a class whose instances have decorator methods.
# Make all decorator methods pass-through so the real functions remain callable.
_mock_dfapp_instance = MagicMock()
for _deco_name in ("route", "orchestration_trigger", "activity_trigger",
                   "durable_client_input"):
    getattr(_mock_dfapp_instance, _deco_name).return_value = lambda f: f
_mock_dfapp = MagicMock(return_value=_mock_dfapp_instance)
_azure.durable_functions.DFApp = _mock_dfapp

sys.modules["azure"] = _azure
sys.modules["azure.functions"] = _azure.functions
sys.modules["azure.durable_functions"] = _azure.durable_functions
sys.modules["azure.storage"] = _azure_storage
sys.modules["azure.storage.blob"] = _azure_storage.blob
sys.modules["anthropic"] = MagicMock()

import function_app as fa


# ---------------------------------------------------------------------------
# Helper — build a minimal CSV
# ---------------------------------------------------------------------------

def _mini_csv(num_rows: int = 2) -> bytes:
    """Build a CSV with enough columns (75) and the given number of data rows."""
    def col_letter(idx):
        r = ""
        while True:
            r = chr(idx % 26 + ord("A")) + r
            idx = idx // 26 - 1
            if idx < 0:
                break
        return r

    headers = [col_letter(i) for i in range(75)]
    lines = [",".join(headers)]
    for i in range(num_rows):
        row = [""] * 75
        row[0] = "M365 E5"
        row[1] = "Renew"
        row[10] = f"Lead{i}"
        row[11] = "Test"
        row[22] = f"Org{i}"
        lines.append(",".join(row))
    return "\n".join(lines).encode("utf-8")


# ---------------------------------------------------------------------------
# _upload_blob / _download_blob — integration-style smoke tests with mocks
# ---------------------------------------------------------------------------

class TestBlobHelpers:
    @patch.object(fa, "_blob_service")
    def test_upload_blob_calls_upload(self, mock_svc):
        mock_container = MagicMock()
        mock_svc.return_value.get_container_client.return_value = mock_container

        fa._upload_blob("test-container", "file.csv", b"data")

        mock_container.upload_blob.assert_called_once_with(name="file.csv", data=b"data", overwrite=True)

    @patch.object(fa, "_blob_service")
    def test_download_blob_returns_bytes(self, mock_svc):
        mock_blob = MagicMock()
        mock_blob.download_blob.return_value.readall.return_value = b"csv content"
        mock_svc.return_value.get_blob_client.return_value = mock_blob

        result = fa._download_blob("test-container", "file.csv")
        assert result == b"csv content"


# ---------------------------------------------------------------------------
# process_lead_activity — test the Claude-calling logic
# ---------------------------------------------------------------------------

class TestProcessLeadActivity:
    def _valid_response(self):
        """Return a valid 8-email JSON response."""
        emails = [{"subject": f"Subj {i+1}", "body": f"Body {i+1}"} for i in range(8)]
        return json.dumps(emails)

    @patch.object(fa, "ANTHROPIC_API_KEY", "test-key")
    @patch.object(fa, "ANTHROPIC_BASE_URL", "https://example.com/anthropic")
    @patch("function_app.AnthropicFoundry")
    def test_success_returns_8_emails(self, mock_foundry_cls):
        mock_client = MagicMock()
        mock_foundry_cls.return_value = mock_client

        # Mock the message response
        mock_block = MagicMock()
        mock_block.text = self._valid_response()
        mock_message = MagicMock()
        mock_message.content = [mock_block]
        mock_client.messages.create.return_value = mock_message

        lead = {
            "row_index": 3,
            "first_name": "Jane",
            "last_name": "Doe",
            "organization": "Contoso",
            "license_renewal": "M365 E5",
            "engagement_objectives": "Renew",
        }

        result = fa.process_lead_activity(lead)

        assert result["row_index"] == 3
        assert "emails" in result
        assert len(result["emails"]) == 8
        assert result["emails"][0]["subject"] == "Subj 1"

    @patch.object(fa, "ANTHROPIC_API_KEY", "test-key")
    @patch.object(fa, "ANTHROPIC_BASE_URL", "https://example.com/anthropic")
    @patch("function_app.AnthropicFoundry")
    def test_strips_markdown_fences(self, mock_foundry_cls):
        mock_client = MagicMock()
        mock_foundry_cls.return_value = mock_client

        # Wrap the valid JSON in markdown code fences
        fenced = "```json\n" + self._valid_response() + "\n```"
        mock_block = MagicMock()
        mock_block.text = fenced
        mock_message = MagicMock()
        mock_message.content = [mock_block]
        mock_client.messages.create.return_value = mock_message

        result = fa.process_lead_activity({"row_index": 0, "first_name": "X"})
        assert "emails" in result
        assert len(result["emails"]) == 8

    @patch.object(fa, "ANTHROPIC_API_KEY", "test-key")
    @patch.object(fa, "ANTHROPIC_BASE_URL", "https://example.com/anthropic")
    @patch("function_app.AnthropicFoundry")
    def test_wrong_email_count_returns_error(self, mock_foundry_cls):
        mock_client = MagicMock()
        mock_foundry_cls.return_value = mock_client

        emails = [{"subject": "s", "body": "b"} for _ in range(5)]
        mock_block = MagicMock()
        mock_block.text = json.dumps(emails)
        mock_message = MagicMock()
        mock_message.content = [mock_block]
        mock_client.messages.create.return_value = mock_message

        result = fa.process_lead_activity({"row_index": 0, "first_name": "X"})
        assert "error" in result
        assert "Expected 8" in result["error"]

    @patch.object(fa, "ANTHROPIC_API_KEY", "test-key")
    @patch.object(fa, "ANTHROPIC_BASE_URL", "https://example.com/anthropic")
    @patch("function_app.AnthropicFoundry")
    def test_missing_keys_returns_error(self, mock_foundry_cls):
        mock_client = MagicMock()
        mock_foundry_cls.return_value = mock_client

        emails = [{"subject": "s", "body": "b"} for _ in range(7)]
        emails.append({"subject": "s"})  # missing "body"
        mock_block = MagicMock()
        mock_block.text = json.dumps(emails)
        mock_message = MagicMock()
        mock_message.content = [mock_block]
        mock_client.messages.create.return_value = mock_message

        result = fa.process_lead_activity({"row_index": 0, "first_name": "X"})
        assert "error" in result
        assert "missing" in result["error"].lower()

    @patch.object(fa, "ANTHROPIC_API_KEY", "test-key")
    @patch.object(fa, "ANTHROPIC_BASE_URL", "https://example.com/anthropic")
    @patch("function_app.AnthropicFoundry")
    def test_invalid_json_returns_error(self, mock_foundry_cls):
        mock_client = MagicMock()
        mock_foundry_cls.return_value = mock_client

        mock_block = MagicMock()
        mock_block.text = "this is not json at all"
        mock_message = MagicMock()
        mock_message.content = [mock_block]
        mock_client.messages.create.return_value = mock_message

        result = fa.process_lead_activity({"row_index": 5, "first_name": "X"})
        assert result["row_index"] == 5
        assert "error" in result
        assert "Invalid JSON" in result["error"]

    @patch.object(fa, "ANTHROPIC_API_KEY", "test-key")
    @patch.object(fa, "ANTHROPIC_BASE_URL", "https://example.com/anthropic")
    @patch("function_app.AnthropicFoundry")
    def test_api_exception_returns_error(self, mock_foundry_cls):
        mock_client = MagicMock()
        mock_foundry_cls.return_value = mock_client
        mock_client.messages.create.side_effect = RuntimeError("network error")

        result = fa.process_lead_activity({"row_index": 1, "first_name": "X"})
        assert result["row_index"] == 1
        assert "error" in result
        assert "network error" in result["error"]


# ---------------------------------------------------------------------------
# extract_leads_activity
# ---------------------------------------------------------------------------

class TestExtractLeadsActivity:
    @patch.object(fa, "_download_blob")
    def test_returns_lead_dicts(self, mock_dl):
        csv_bytes = _mini_csv(3)
        mock_dl.return_value = csv_bytes

        leads = fa.extract_leads_activity("job-123")

        assert len(leads) == 3
        assert leads[0]["first_name"] == "Lead0"
        assert leads[2]["organization"] == "Org2"
        mock_dl.assert_called_once_with(fa.INPUT_CONTAINER, "job-123.csv")


# ---------------------------------------------------------------------------
# assemble_csv_activity
# ---------------------------------------------------------------------------

class TestAssembleCsvActivity:
    @patch.object(fa, "_upload_blob")
    @patch.object(fa, "_download_blob")
    def test_uploads_enriched_csv(self, mock_dl, mock_ul):
        csv_bytes = _mini_csv(1)
        mock_dl.return_value = csv_bytes

        results = [{
            "row_index": 0,
            "emails": [{"subject": f"S{i}", "body": f"B{i}"} for i in range(8)],
        }]

        output = fa.assemble_csv_activity({"job_id": "abc", "results": results})

        assert output == "abc.csv"
        mock_ul.assert_called_once()
        call_args = mock_ul.call_args
        assert call_args[0][0] == fa.OUTPUT_CONTAINER
        assert call_args[0][1] == "abc.csv"
        # The third arg should be CSV bytes
        enriched = call_args[0][2]
        assert b"Subject_Touch1" in enriched


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

class TestConfiguration:
    def test_batch_size_default(self):
        assert fa.BATCH_SIZE == 15

    def test_max_csv_size(self):
        assert fa.MAX_CSV_SIZE_BYTES == 50 * 1024 * 1024

    def test_default_model(self):
        assert fa.ANTHROPIC_MODEL == "claude-opus-4-6"
