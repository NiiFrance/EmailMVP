"""Tests for prompt_templates module."""

import json
import pytest

from prompt_templates import SYSTEM_PROMPT, build_user_prompt


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT validation
# ---------------------------------------------------------------------------

class TestSystemPrompt:
    def test_is_nonempty_string(self):
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 100

    def test_specifies_8_emails(self):
        assert "exactly 8 emails" in SYSTEM_PROMPT

    def test_specifies_json_output(self):
        assert '"subject"' in SYSTEM_PROMPT
        assert '"body"' in SYSTEM_PROMPT

    def test_all_8_touches_mentioned(self):
        touches = [
            "Introduction",
            "Diagnostic",
            "Benefit",
            "Social Proof",
            "Authority",
            "Promo Canvas",
            "Switch Plan",
            "Risk Reversal",
            "Danger",
            "Close the Loop",
        ]
        for touch in touches:
            assert touch in SYSTEM_PROMPT, f"Missing touch: {touch}"

    def test_hard_constraints_present(self):
        assert "maximum 7 words" in SYSTEM_PROMPT
        assert "200–260 words" in SYSTEM_PROMPT or "200-260 words" in SYSTEM_PROMPT
        assert "NO signature block" in SYSTEM_PROMPT
        assert "NO links" in SYSTEM_PROMPT
        assert "3 paragraphs" in SYSTEM_PROMPT
        assert "closing phrase" in SYSTEM_PROMPT

    def test_mentions_reliance(self):
        assert "Reliance Infosystems" in SYSTEM_PROMPT

    def test_no_markdown_fences_instruction(self):
        assert "No markdown" in SYSTEM_PROMPT

    def test_cold_email_context(self):
        assert "cold" in SYSTEM_PROMPT.lower()
        assert "does NOT know Reliance" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# build_user_prompt
# ---------------------------------------------------------------------------

class TestBuildUserPrompt:
    @pytest.fixture
    def sample_lead(self):
        return {
            "row_index": 0,
            "first_name": "Jane",
            "last_name": "Doe",
            "organization": "Contoso Ltd",
            "license_renewal": "Microsoft 365 E5",
            "engagement_objectives": "Streamline renewal process",
            "Industry": "Technology",
            "Headcount": "500-1000",
            "Title": "CFO",
        }

    def test_includes_primary_fields(self, sample_lead):
        prompt = build_user_prompt(sample_lead)
        assert "Jane" in prompt
        assert "Doe" in prompt
        assert "Contoso Ltd" in prompt
        assert "Microsoft 365 E5" in prompt
        assert "Streamline renewal process" in prompt

    def test_includes_demographic_data(self, sample_lead):
        prompt = build_user_prompt(sample_lead)
        assert "Industry: Technology" in prompt
        assert "Headcount: 500-1000" in prompt
        assert "Title: CFO" in prompt

    def test_excludes_internal_keys(self, sample_lead):
        prompt = build_user_prompt(sample_lead)
        # row_index and the primary keys should not appear as demographic lines
        assert "row_index:" not in prompt
        assert "first_name:" not in prompt
        assert "license_renewal:" not in prompt

    def test_8_email_instruction(self, sample_lead):
        prompt = build_user_prompt(sample_lead)
        assert "8 cold emails" in prompt
        assert "8-email touch sequence" in prompt

    def test_empty_demographics(self):
        lead = {
            "row_index": 0,
            "first_name": "Bob",
            "last_name": "Smith",
            "organization": "Acme",
            "license_renewal": "Azure",
            "engagement_objectives": "Migrate",
        }
        prompt = build_user_prompt(lead)
        assert "No additional demographic data available" in prompt

    def test_skips_nan_values(self):
        lead = {
            "row_index": 0,
            "first_name": "Bob",
            "last_name": "Smith",
            "organization": "Acme",
            "license_renewal": "Azure",
            "engagement_objectives": "Migrate",
            "Industry": "nan",
            "Country": "  ",
        }
        prompt = build_user_prompt(lead)
        assert "Industry" not in prompt
        assert "Country" not in prompt

    def test_returns_string(self, sample_lead):
        prompt = build_user_prompt(sample_lead)
        assert isinstance(prompt, str)
