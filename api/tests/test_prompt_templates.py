"""Tests for prompt_templates module — 9-template registry."""

import json
import pytest

from prompt_templates import (
    SYSTEM_PROMPT,
    build_user_prompt,
    PROMPT_REGISTRY,
    get_template,
    list_templates,
    _parse_emails,
    _make_parser,
    _output_headers,
    _make_output_headers_fn,
    _flatten_emails,
    _build_cold_email_user_prompt,
    FIELDS_COLD_EMAIL,
    FIELDS_NAME_ORG,
    FIELDS_NAME_EMAIL_ORG,
    FIELDS_FIRST_NAME_ONLY,
)


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT backward-compatible alias
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

    def test_mentions_cloudware(self):
        assert "Cloudware" in SYSTEM_PROMPT

    def test_cold_email_context(self):
        assert "cold" in SYSTEM_PROMPT.lower()
        assert "does NOT know Cloudware" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Template Registry — all 9 templates
# ---------------------------------------------------------------------------

EXPECTED_IDS = [
    "cold_email", "csp_renewal_with_license", "csp_renewal_without_license",
    "e7_upsell", "ea_to_csp", "leads", "marketplace", "price_change",
    "cloud_ascent",
]


class TestPromptRegistry:
    def test_all_9_templates_present(self):
        for tid in EXPECTED_IDS:
            assert tid in PROMPT_REGISTRY, f"Missing template: {tid}"

    def test_exactly_9_templates(self):
        assert len(PROMPT_REGISTRY) == 9

    def test_no_extra_templates(self):
        assert set(PROMPT_REGISTRY.keys()) == set(EXPECTED_IDS)

    def test_registry_entries_have_required_keys(self):
        required_keys = {
            "id", "name", "group", "description", "num_emails",
            "system_prompt", "build_user_prompt", "parse_response",
            "output_headers", "flatten_result", "required_fields",
        }
        for tid, tmpl in PROMPT_REGISTRY.items():
            for key in required_keys:
                assert key in tmpl, f"Template '{tid}' missing key '{key}'"

    def test_all_system_prompts_nonempty(self):
        for tid, tmpl in PROMPT_REGISTRY.items():
            assert isinstance(tmpl["system_prompt"], str)
            assert len(tmpl["system_prompt"]) > 50, f"Template '{tid}' has short system_prompt"

    def test_group_values(self):
        valid_groups = {"Renewals", "Migrations", "Demand Generation", "Inbound"}
        for tid, tmpl in PROMPT_REGISTRY.items():
            assert tmpl["group"] in valid_groups, f"Template '{tid}' has invalid group '{tmpl['group']}'"

    def test_num_emails_values(self):
        expected = {
            "cold_email": 8, "csp_renewal_with_license": 4,
            "csp_renewal_without_license": 4, "e7_upsell": 5,
            "ea_to_csp": 4, "leads": 2, "marketplace": 4,
            "price_change": 4, "cloud_ascent": 4,
        }
        for tid, count in expected.items():
            assert PROMPT_REGISTRY[tid]["num_emails"] == count, f"{tid} num_emails mismatch"

    def test_get_template_known(self):
        tmpl = get_template("cold_email")
        assert tmpl["id"] == "cold_email"

    def test_get_template_unknown_raises(self):
        with pytest.raises(KeyError):
            get_template("nonexistent_template")


# ---------------------------------------------------------------------------
# list_templates
# ---------------------------------------------------------------------------

class TestListTemplates:
    def test_returns_list(self):
        result = list_templates()
        assert isinstance(result, list)
        assert len(result) == 9

    def test_has_required_fields(self):
        result = list_templates()
        for t in result:
            assert "id" in t
            assert "name" in t
            assert "group" in t
            assert "description" in t
            assert "num_emails" in t

    def test_all_ids_present(self):
        ids = [t["id"] for t in list_templates()]
        for tid in EXPECTED_IDS:
            assert tid in ids


# ---------------------------------------------------------------------------
# Required field sets
# ---------------------------------------------------------------------------

class TestRequiredFields:
    def test_cold_email_fields(self):
        assert "first_name" in FIELDS_COLD_EMAIL
        assert "last_name" in FIELDS_COLD_EMAIL
        assert "organization" in FIELDS_COLD_EMAIL
        assert "license_renewal" in FIELDS_COLD_EMAIL
        assert "engagement_objectives" in FIELDS_COLD_EMAIL

    def test_name_org_fields(self):
        assert "first_name" in FIELDS_NAME_ORG
        assert "organization" in FIELDS_NAME_ORG
        assert len(FIELDS_NAME_ORG) == 2

    def test_name_email_org_fields(self):
        assert "first_name" in FIELDS_NAME_EMAIL_ORG
        assert "organization" in FIELDS_NAME_EMAIL_ORG
        assert "email_address" in FIELDS_NAME_EMAIL_ORG

    def test_first_name_only_fields(self):
        assert "first_name" in FIELDS_FIRST_NAME_ONLY
        assert len(FIELDS_FIRST_NAME_ONLY) == 1

    def test_cold_email_uses_its_fields(self):
        assert PROMPT_REGISTRY["cold_email"]["required_fields"] is FIELDS_COLD_EMAIL

    def test_leads_uses_first_name_only(self):
        assert PROMPT_REGISTRY["leads"]["required_fields"] is FIELDS_FIRST_NAME_ONLY

    def test_csp_without_license_uses_email_org(self):
        assert PROMPT_REGISTRY["csp_renewal_without_license"]["required_fields"] is FIELDS_NAME_EMAIL_ORG


# ---------------------------------------------------------------------------
# Shared parser — _parse_emails
# ---------------------------------------------------------------------------

class TestParseEmails:
    def test_valid_4_emails(self):
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(4)]
        result = _parse_emails(json.dumps(emails), 4)
        assert len(result) == 4

    def test_valid_8_emails(self):
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(8)]
        result = _parse_emails(json.dumps(emails), 8)
        assert len(result) == 8

    def test_valid_2_emails(self):
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(2)]
        result = _parse_emails(json.dumps(emails), 2)
        assert len(result) == 2

    def test_strips_markdown_fences(self):
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(4)]
        text = "```json\n" + json.dumps(emails) + "\n```"
        result = _parse_emails(text, 4)
        assert len(result) == 4

    def test_wrong_count_raises(self):
        emails = [{"subject": "S", "body": "B"}]
        with pytest.raises(ValueError, match="Expected 4"):
            _parse_emails(json.dumps(emails), 4)

    def test_missing_keys_raises(self):
        emails = [{"subject": "S"}] * 4
        with pytest.raises(ValueError, match="missing"):
            _parse_emails(json.dumps(emails), 4)

    def test_invalid_json_raises(self):
        with pytest.raises(json.JSONDecodeError):
            _parse_emails("not json", 4)

    def test_do_not_generate_raises(self):
        with pytest.raises(ValueError, match="Model declined"):
            _parse_emails("DO NOT GENERATE - Missing: first_name", 4)


class TestMakeParser:
    def test_factory_returns_callable(self):
        parser = _make_parser(4)
        assert callable(parser)

    def test_factory_bound_count(self):
        parser = _make_parser(5)
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(5)]
        result = parser(json.dumps(emails))
        assert len(result) == 5

    def test_factory_wrong_count_raises(self):
        parser = _make_parser(4)
        emails = [{"subject": "S", "body": "B"}] * 3
        with pytest.raises(ValueError, match="Expected 4"):
            parser(json.dumps(emails))


# ---------------------------------------------------------------------------
# Output headers
# ---------------------------------------------------------------------------

class TestOutputHeaders:
    def test_4_emails(self):
        headers = _output_headers(4)
        assert len(headers) == 8
        assert headers[0] == "Subject_Touch1"
        assert headers[-1] == "Body_Touch4"

    def test_8_emails(self):
        headers = _output_headers(8)
        assert len(headers) == 16
        assert headers[-1] == "Body_Touch8"

    def test_2_emails(self):
        headers = _output_headers(2)
        assert len(headers) == 4
        assert headers == ["Subject_Touch1", "Body_Touch1", "Subject_Touch2", "Body_Touch2"]

    def test_factory_returns_callable(self):
        fn = _make_output_headers_fn(4)
        assert callable(fn)
        assert len(fn()) == 8


# ---------------------------------------------------------------------------
# Flatten
# ---------------------------------------------------------------------------

class TestFlattenEmails:
    def test_flatten_4(self):
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(4)]
        flat = _flatten_emails(emails)
        assert len(flat) == 8
        assert flat["Subject_Touch1"] == "S0"
        assert flat["Body_Touch4"] == "B3"

    def test_flatten_8(self):
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(8)]
        flat = _flatten_emails(emails)
        assert len(flat) == 16
        assert flat["Subject_Touch1"] == "S0"
        assert flat["Body_Touch8"] == "B7"


# ---------------------------------------------------------------------------
# User prompt builders
# ---------------------------------------------------------------------------

class TestBuildColdEmailUserPrompt:
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
        }

    def test_includes_primary_fields(self, sample_lead):
        prompt = _build_cold_email_user_prompt(sample_lead)
        assert "Jane" in prompt
        assert "Doe" in prompt
        assert "Contoso Ltd" in prompt
        assert "Microsoft 365 E5" in prompt

    def test_includes_demographic_data(self, sample_lead):
        prompt = _build_cold_email_user_prompt(sample_lead)
        assert "Industry: Technology" in prompt
        assert "Headcount: 500-1000" in prompt

    def test_excludes_internal_keys(self, sample_lead):
        prompt = _build_cold_email_user_prompt(sample_lead)
        assert "row_index:" not in prompt

    def test_8_email_instruction(self, sample_lead):
        prompt = _build_cold_email_user_prompt(sample_lead)
        assert "8 cold emails" in prompt

    def test_empty_demographics(self):
        lead = {
            "row_index": 0,
            "first_name": "Bob",
            "last_name": "Smith",
            "organization": "Acme",
            "license_renewal": "Azure",
            "engagement_objectives": "Migrate",
        }
        prompt = _build_cold_email_user_prompt(lead)
        assert "No additional demographic data available" in prompt


class TestBuildGenericUserPrompt:
    def test_dumps_all_fields(self):
        lead = {
            "row_index": 0,
            "first_name": "Kofi",
            "organization": "Acme Ltd",
            "Title": "CTO",
        }
        prompt = build_user_prompt(lead)
        assert "first_name: Kofi" in prompt
        assert "organization: Acme Ltd" in prompt
        assert "Title: CTO" in prompt

    def test_excludes_row_index(self):
        lead = {"row_index": 5, "first_name": "Test"}
        prompt = build_user_prompt(lead)
        assert "row_index" not in prompt

    def test_skips_nan_values(self):
        lead = {"row_index": 0, "first_name": "Bob", "Industry": "nan", "Country": "  "}
        prompt = build_user_prompt(lead)
        assert "Industry" not in prompt
        assert "Country" not in prompt

    def test_returns_string(self):
        prompt = build_user_prompt({"row_index": 0, "first_name": "X"})
        assert isinstance(prompt, str)


# ---------------------------------------------------------------------------
# Template-specific prompt content validation
# ---------------------------------------------------------------------------

class TestTemplatePromptContent:
    """Validate that each template's system prompt loaded correctly from disk."""

    def test_cold_email_mentions_cloudware(self):
        assert "Cloudware" in get_template("cold_email")["system_prompt"]

    def test_csp_renewal_with_license_mentions_4_emails(self):
        prompt = get_template("csp_renewal_with_license")["system_prompt"]
        assert "4" in prompt

    def test_leads_mentions_2_emails(self):
        prompt = get_template("leads")["system_prompt"]
        assert "2" in prompt

    def test_e7_upsell_mentions_5_emails(self):
        prompt = get_template("e7_upsell")["system_prompt"]
        assert "5" in prompt

    def test_cloud_ascent_mentions_propensity(self):
        prompt = get_template("cloud_ascent")["system_prompt"]
        assert "propensity" in prompt.lower() or "CloudAscent" in prompt

    def test_marketplace_mentions_marketplace(self):
        prompt = get_template("marketplace")["system_prompt"]
        assert "marketplace" in prompt.lower()

    def test_ea_to_csp_mentions_ea(self):
        prompt = get_template("ea_to_csp")["system_prompt"]
        assert "EA" in prompt


# ---------------------------------------------------------------------------
# End-to-end: each template's parser + flatten round-trip
# ---------------------------------------------------------------------------

class TestTemplateRoundTrip:
    """For each template, generate fake JSON, parse it, flatten it, and verify output headers match."""

    @pytest.mark.parametrize("template_id", EXPECTED_IDS)
    def test_parse_flatten_roundtrip(self, template_id):
        tmpl = get_template(template_id)
        n = tmpl["num_emails"]

        # Build fake model response
        emails = [{"subject": f"S{i}", "body": f"B{i}"} for i in range(n)]
        response_text = json.dumps(emails)

        # Parse
        parsed = tmpl["parse_response"](response_text)
        assert len(parsed) == n

        # Flatten
        flat = tmpl["flatten_result"](parsed)
        expected_headers = tmpl["output_headers"]()
        assert set(flat.keys()) == set(expected_headers)

    @pytest.mark.parametrize("template_id", EXPECTED_IDS)
    def test_user_prompt_builder(self, template_id):
        tmpl = get_template(template_id)
        lead = {"row_index": 0, "first_name": "Test", "organization": "TestCorp"}
        prompt = tmpl["build_user_prompt"](lead)
        assert isinstance(prompt, str)
        assert len(prompt) > 10
