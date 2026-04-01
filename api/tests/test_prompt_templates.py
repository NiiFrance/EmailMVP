"""Tests for prompt_templates module."""

import json
import pytest

from prompt_templates import (
    SYSTEM_PROMPT,
    build_user_prompt,
    COLD_EMAIL_SYSTEM_PROMPT,
    E_INVOICE_SYSTEM_PROMPT,
    PROMPT_REGISTRY,
    get_template,
    list_templates,
    build_custom_template,
    MAX_CUSTOM_PROMPT_LENGTH,
    _parse_cold_email_response,
    _parse_e_invoice_response,
    _parse_custom_response,
    _cold_email_output_headers,
    _e_invoice_output_headers,
    _flatten_cold_email,
    _flatten_e_invoice,
    _flatten_custom,
    _custom_output_headers_from_parsed,
)


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


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    def test_system_prompt_alias(self):
        assert SYSTEM_PROMPT is COLD_EMAIL_SYSTEM_PROMPT

    def test_build_user_prompt_alias(self):
        lead = {"first_name": "X", "last_name": "Y", "organization": "Z",
                "license_renewal": "L", "engagement_objectives": "E"}
        assert "X" in build_user_prompt(lead)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class TestPromptRegistry:
    def test_cold_email_in_registry(self):
        assert "cold_email" in PROMPT_REGISTRY

    def test_e_invoice_in_registry(self):
        assert "e_invoice" in PROMPT_REGISTRY

    def test_registry_entries_have_required_keys(self):
        required_keys = {"id", "name", "description", "system_prompt",
                         "build_user_prompt", "parse_response", "output_headers",
                         "flatten_result", "num_outputs", "output_label", "required_fields"}
        for tid, tmpl in PROMPT_REGISTRY.items():
            for key in required_keys:
                assert key in tmpl, f"Template '{tid}' missing key '{key}'"

    def test_get_template_known(self):
        tmpl = get_template("cold_email")
        assert tmpl["id"] == "cold_email"

    def test_get_template_unknown_raises(self):
        with pytest.raises(KeyError):
            get_template("nonexistent_template")

    def test_list_templates_returns_list(self):
        result = list_templates()
        assert isinstance(result, list)
        assert len(result) >= 2
        assert all("id" in t and "name" in t and "description" in t for t in result)

    def test_list_templates_ids(self):
        ids = [t["id"] for t in list_templates()]
        assert "cold_email" in ids
        assert "e_invoice" in ids


# ---------------------------------------------------------------------------
# E-Invoice System Prompt
# ---------------------------------------------------------------------------

class TestEInvoicePrompt:
    def test_is_nonempty_string(self):
        assert isinstance(E_INVOICE_SYSTEM_PROMPT, str)
        assert len(E_INVOICE_SYSTEM_PROMPT) > 100

    def test_specifies_5_scripts(self):
        assert "exactly 5" in E_INVOICE_SYSTEM_PROMPT

    def test_mentions_reliance(self):
        assert "Reliance Infosystems" in E_INVOICE_SYSTEM_PROMPT

    def test_persona_table(self):
        for persona in ["CFO_FINANCE", "CTO_IT", "CEO_MD", "PROCUREMENT_OPS", "GENERAL_BUSINESS"]:
            assert persona in E_INVOICE_SYSTEM_PROMPT

    def test_e_invoice_user_prompt(self):
        tmpl = get_template("e_invoice")
        lead = {"first_name": "Kofi", "last_name": "Asante",
                "organisation_name": "Gold Coast Ltd", "email_address": "kofi@gc.com",
                "Title": "CFO"}
        prompt = tmpl["build_user_prompt"](lead)
        assert "Kofi" in prompt
        assert "Gold Coast Ltd" in prompt
        assert "kofi@gc.com" in prompt


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

class TestParseColdEmail:
    def test_valid_8_emails(self):
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(8)]
        result = _parse_cold_email_response(json.dumps(emails))
        assert len(result) == 8

    def test_strips_markdown_fences(self):
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(8)]
        text = "```json\n" + json.dumps(emails) + "\n```"
        result = _parse_cold_email_response(text)
        assert len(result) == 8

    def test_wrong_count_raises(self):
        emails = [{"subject": "S", "body": "B"}]
        with pytest.raises(ValueError, match="Expected 8"):
            _parse_cold_email_response(json.dumps(emails))

    def test_missing_keys_raises(self):
        emails = [{"subject": "S"}] * 8
        with pytest.raises(ValueError, match="missing"):
            _parse_cold_email_response(json.dumps(emails))

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_cold_email_response("not json")


class TestParseEInvoice:
    def _valid_response(self, do_not_generate=False):
        if do_not_generate:
            return json.dumps({
                "persona_selected": "NONE",
                "channel_strategy": "none",
                "scripts": [],
                "do_not_generate": True,
                "reason": "Missing data",
            })
        scripts = [
            {"touch_number": i, "touch_type": "Intro", "channel": "email",
             "subject": "S", "message_body": "B", "cta": "C", "send_delay_days": 0}
            for i in range(1, 6)
        ]
        return json.dumps({
            "persona_selected": "CFO_FINANCE",
            "channel_strategy": "email_first",
            "do_not_generate": False,
            "scripts": scripts,
        })

    def test_valid_5_scripts(self):
        result = _parse_e_invoice_response(self._valid_response())
        assert len(result) == 1
        assert len(result[0]["scripts"]) == 5

    def test_do_not_generate(self):
        result = _parse_e_invoice_response(self._valid_response(do_not_generate=True))
        assert result[0]["do_not_generate"] is True

    def test_wrong_count_raises(self):
        data = {"persona_selected": "X", "channel_strategy": "Y",
                "scripts": [{"touch_number": 1}]}
        with pytest.raises(ValueError, match="Expected 5"):
            _parse_e_invoice_response(json.dumps(data))


class TestParseCustom:
    def test_json_array(self):
        result = _parse_custom_response('[{"a": 1}, {"a": 2}]')
        assert len(result) == 2

    def test_json_object(self):
        result = _parse_custom_response('{"a": 1}')
        assert len(result) == 1

    def test_strips_fences(self):
        result = _parse_custom_response('```json\n[{"a": 1}]\n```')
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Output headers
# ---------------------------------------------------------------------------

class TestOutputHeaders:
    def test_cold_email_headers_count(self):
        headers = _cold_email_output_headers()
        assert len(headers) == 16
        assert headers[0] == "Subject_Touch1"
        assert headers[-1] == "Body_Touch8"

    def test_e_invoice_headers(self):
        headers = _e_invoice_output_headers()
        # 4 top-level + 5 scripts * 6 fields = 34
        assert len(headers) == 34
        assert "Persona_Selected" in headers
        assert "Touch1_Body" in headers
        assert "Touch5_CTA" in headers


# ---------------------------------------------------------------------------
# Flatten functions
# ---------------------------------------------------------------------------

class TestFlattenColdEmail:
    def test_flatten(self):
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(8)]
        flat = _flatten_cold_email(emails)
        assert flat["Subject_Touch1"] == "S0"
        assert flat["Body_Touch8"] == "B7"
        assert len(flat) == 16


class TestFlattenEInvoice:
    def test_flatten_valid(self):
        scripts = [
            {"touch_type": "Intro", "channel": "email", "subject": "S",
             "message_body": "B", "cta": "C", "send_delay_days": 0}
            for _ in range(5)
        ]
        parsed = [{"persona_selected": "CFO_FINANCE", "channel_strategy": "email_first",
                    "do_not_generate": False, "scripts": scripts}]
        flat = _flatten_e_invoice(parsed)
        assert flat["Persona_Selected"] == "CFO_FINANCE"
        assert flat["Touch1_Body"] == "B"
        assert flat["Touch5_CTA"] == "C"

    def test_flatten_dng(self):
        parsed = [{"persona_selected": "NONE", "channel_strategy": "none",
                    "do_not_generate": True, "reason": "Bad data", "scripts": []}]
        flat = _flatten_e_invoice(parsed)
        assert flat["Do_Not_Generate"] == "True"
        assert flat["DNG_Reason"] == "Bad data"
        assert flat["Touch1_Body"] == ""


class TestFlattenCustom:
    def test_simple_flat(self):
        parsed = [{"key1": "val1", "key2": "val2"}]
        flat = _flatten_custom(parsed)
        assert flat["key1"] == "val1"

    def test_nested(self):
        parsed = [{"outer": {"inner": "val"}}]
        flat = _flatten_custom(parsed)
        assert flat["outer_inner"] == "val"


class TestCustomOutputHeaders:
    def test_discovers_keys(self):
        parsed = [{"name": "Kofi", "score": 90}]
        headers = _custom_output_headers_from_parsed(parsed)
        assert "name" in headers
        assert "score" in headers

    def test_nested_keys(self):
        parsed = [{"meta": {"status": "ok"}}]
        headers = _custom_output_headers_from_parsed(parsed)
        assert "meta_status" in headers


# ---------------------------------------------------------------------------
# Custom template builder
# ---------------------------------------------------------------------------

class TestBuildCustomTemplate:
    def test_builds_valid_template(self):
        tmpl = build_custom_template("You are a helpful assistant.")
        assert tmpl["id"] == "custom"
        assert tmpl["system_prompt"] == "You are a helpful assistant."
        assert tmpl["required_fields"] is None
        assert tmpl["output_headers"] is None

    def test_rejects_too_long_prompt(self):
        with pytest.raises(ValueError, match="too long"):
            build_custom_template("x" * (MAX_CUSTOM_PROMPT_LENGTH + 1))
