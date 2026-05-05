"""Tests for column_mapper module."""

import json
from unittest.mock import MagicMock, patch
import pytest

from column_mapper import (
    REQUIRED_FIELDS,
    _normalize,
    fuzzy_match_columns,
    llm_match_columns,
    resolve_columns,
)


# ---------------------------------------------------------------------------
# _normalize
# ---------------------------------------------------------------------------

class TestNormalize:
    def test_lowercase_and_strip(self):
        assert _normalize("  First Name  ") == "first name"

    def test_underscores_to_spaces(self):
        assert _normalize("first_name") == "first name"

    def test_hyphens_to_spaces(self):
        assert _normalize("first-name") == "first name"

    def test_collapse_whitespace(self):
        assert _normalize("first   name") == "first name"


# ---------------------------------------------------------------------------
# fuzzy_match_columns — exact header variations
# ---------------------------------------------------------------------------

class TestFuzzyMatchColumns:
    def test_standard_linkedin_headers(self):
        """Headers from the standard LinkedIn Helper export (our original format)."""
        headers = [""] * 75
        headers[0] = "License Renewal"
        headers[1] = "Engagement Objectives"
        headers[10] = "First Name"
        headers[11] = "Last Name"
        headers[22] = "Organization"
        result = fuzzy_match_columns(headers)
        assert result["first_name"] == 10
        assert result["last_name"] == 11
        assert result["organization"] == 22
        assert result["license_renewal"] == 0
        assert result["engagement_objectives"] == 1

    def test_lowercase_headers(self):
        headers = ["first name", "last name", "company", "license", "engagement objectives"]
        result = fuzzy_match_columns(headers)
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organization"] == 2
        assert result["license_renewal"] == 3
        assert result["engagement_objectives"] == 4

    def test_underscore_headers(self):
        headers = ["first_name", "last_name", "organization", "license_renewal", "engagement_objectives"]
        result = fuzzy_match_columns(headers)
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organization"] == 2
        assert result["license_renewal"] == 3
        assert result["engagement_objectives"] == 4

    def test_alternative_names(self):
        headers = ["Given Name", "Surname", "Company Name", "Subscription", "Goal"]
        result = fuzzy_match_columns(headers)
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organization"] == 2
        assert result["license_renewal"] == 3
        assert result["engagement_objectives"] == 4

    def test_case_insensitive(self):
        headers = ["FIRST NAME", "LAST NAME", "COMPANY", "LICENSE", "ENGAGEMENT"]
        result = fuzzy_match_columns(headers)
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organization"] == 2
        assert result["license_renewal"] == 3
        assert result["engagement_objectives"] == 4

    def test_missing_columns_return_none(self):
        headers = ["First Name", "Last Name", "Organization"]
        result = fuzzy_match_columns(headers)
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organization"] == 2
        assert result["license_renewal"] is None
        assert result["engagement_objectives"] is None

    def test_no_matching_headers(self):
        headers = ["Column A", "Column B", "Column C"]
        result = fuzzy_match_columns(headers)
        assert all(v is None for v in result.values())

    def test_mixed_columns_with_extras(self):
        headers = ["ID", "Email", "First Name", "Last Name", "Phone", "Company", "Product License", "Engagement Objectives"]
        result = fuzzy_match_columns(headers)
        assert result["first_name"] == 2
        assert result["last_name"] == 3
        assert result["organization"] == 5
        assert result["license_renewal"] == 6
        assert result["engagement_objectives"] == 7

    def test_fname_lname_shorthand(self):
        headers = ["fname", "lname", "org", "sku", "initiative"]
        result = fuzzy_match_columns(headers)
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organization"] == 2
        assert result["license_renewal"] == 3
        assert result["engagement_objectives"] == 4


# ---------------------------------------------------------------------------
# llm_match_columns
# ---------------------------------------------------------------------------

class TestLLMMatchColumns:
    def test_successful_llm_mapping(self):
        headers = ["Prenom", "Nom de Famille", "Entreprise", "Abonnement", "Objectif"]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"first_name": 0, "last_name": 1}'))]
        )

        result = llm_match_columns(headers, ["first_name", "last_name"], mock_client, "gpt-53-chat")
        assert result["first_name"] == 0
        assert result["last_name"] == 1

    def test_llm_returns_null(self):
        headers = ["A", "B", "C"]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"first_name": null}'))]
        )

        result = llm_match_columns(headers, ["first_name"], mock_client, "gpt-53-chat")
        assert result["first_name"] is None

    def test_llm_failure_returns_none(self):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("API error")

        result = llm_match_columns(["A"], ["first_name"], mock_client, "gpt-53-chat")
        assert result["first_name"] is None

    def test_llm_out_of_range_index(self):
        headers = ["A", "B"]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='{"first_name": 99}'))]
        )

        result = llm_match_columns(headers, ["first_name"], mock_client, "gpt-53-chat")
        assert result["first_name"] is None

    def test_llm_strips_markdown_fences(self):
        headers = ["Given Name", "Family Name"]
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(content='```json\n{"first_name": 0}\n```'))]
        )

        result = llm_match_columns(headers, ["first_name"], mock_client, "gpt-53-chat")
        assert result["first_name"] == 0


# ---------------------------------------------------------------------------
# resolve_columns — end-to-end
# ---------------------------------------------------------------------------

class TestResolveColumns:
    def test_all_fuzzy_matched(self):
        headers = ["First Name", "Last Name", "Company", "License Renewal", "Engagement Objectives"]
        result = resolve_columns(headers)
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organization"] == 2
        assert result["license_renewal"] == 3
        assert result["engagement_objectives"] == 4

    def test_raises_when_fields_missing_no_client(self):
        headers = ["Column A", "Column B"]
        with pytest.raises(ValueError, match="Could not detect required columns"):
            resolve_columns(headers)

    def test_llm_fallback_fills_gaps(self):
        headers = ["Prenom", "Nom", "Societe", "License", "Engagement"]
        # Fuzzy will match license and engagement but not prenom/nom/societe
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = MagicMock(
            choices=[MagicMock(message=MagicMock(
                content='{"first_name": 0, "last_name": 1, "organization": 2}'
            ))]
        )

        result = resolve_columns(headers, client=mock_client, deployment="gpt-53-chat")
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organization"] == 2

    def test_raises_when_llm_also_fails(self):
        headers = ["X", "Y", "Z"]
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("fail")

        with pytest.raises(ValueError, match="Could not detect required columns"):
            resolve_columns(headers, client=mock_client, deployment="gpt-53-chat")

    def test_returns_int_values_only(self):
        headers = ["first_name", "last_name", "organization", "license", "objective"]
        result = resolve_columns(headers)
        for v in result.values():
            assert isinstance(v, int)


# ---------------------------------------------------------------------------
# Custom required_fields parameter
# ---------------------------------------------------------------------------

class TestCustomRequiredFields:
    """Test that fuzzy_match and resolve_columns work with non-default required_fields."""

    E_INVOICE_FIELDS = {
        "first_name": ["first name", "firstname", "first_name", "fname"],
        "last_name": ["last name", "lastname", "last_name", "lname", "surname"],
        "organisation_name": ["company", "organization", "organisation", "org", "employer"],
        "email_address": ["email", "e-mail", "email address", "email_address", "mail"],
    }

    def test_fuzzy_match_e_invoice_fields(self):
        headers = ["First Name", "Last Name", "Organisation", "Email Address", "Phone"]
        result = fuzzy_match_columns(headers, required_fields=self.E_INVOICE_FIELDS)
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organisation_name"] == 2
        assert result["email_address"] == 3

    def test_resolve_columns_e_invoice(self):
        headers = ["First Name", "Surname", "Company Name", "Email"]
        result = resolve_columns(headers, required_fields=self.E_INVOICE_FIELDS)
        assert result["first_name"] == 0
        assert result["last_name"] == 1
        assert result["organisation_name"] == 2
        assert result["email_address"] == 3

    def test_resolve_raises_for_missing_custom_field(self):
        headers = ["Name", "Phone"]
        with pytest.raises(ValueError, match="Could not detect"):
            resolve_columns(headers, required_fields=self.E_INVOICE_FIELDS)

    def test_none_required_fields_falls_back_to_default(self):
        headers = ["First Name", "Last Name", "Company", "License", "Engagement"]
        result = fuzzy_match_columns(headers, required_fields=None)
        assert "first_name" in result
        assert "license_renewal" in result
