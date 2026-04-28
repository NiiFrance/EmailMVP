"""Prompt templates registry - 9 campaign motions for email generation.

Each template loads its system prompt from api/prompts/<id>.txt and shares
a common output schema: JSON array of {"subject": ..., "body": ...} objects.
"""

import json
import logging
import pathlib
import re

logger = logging.getLogger("emailmvp")

_PROMPTS_DIR = pathlib.Path(__file__).parent / "prompts"
_EMAIL_VALUE_RE = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")


# ---------------------------------------------------------------------------
# Prompt file loader
# ---------------------------------------------------------------------------

def _load_prompt(name: str) -> str:
    """Load a system prompt from the prompts/ directory."""
    path = _PROMPTS_DIR / f"{name}.txt"
    return path.read_text(encoding="utf-8").strip()


# ---------------------------------------------------------------------------
# Shared helpers — all templates produce [{"subject": ..., "body": ...}]
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove markdown code fences from model output."""
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        return "\n".join(lines)
    return text


def _parse_emails(response_text: str, expected_count: int) -> list[dict]:
    """Parse model response into a list of email dicts with subject + body."""
    text = _strip_fences(response_text.strip())

    # Handle DO NOT GENERATE responses from validation-aware templates
    if text.upper().startswith("DO NOT GENERATE"):
        raise ValueError(f"Model declined: {text[:200]}")

    emails = json.loads(text)

    if not isinstance(emails, list) or len(emails) != expected_count:
        raise ValueError(
            f"Expected {expected_count} emails, got "
            f"{len(emails) if isinstance(emails, list) else 'non-list'}"
        )

    for i, email in enumerate(emails):
        if "subject" not in email or "body" not in email:
            raise ValueError(f"Email {i+1} missing 'subject' or 'body' key")

    return emails


def _make_parser(expected_count: int):
    """Factory: return a parser function bound to a specific email count."""
    def parser(response_text: str) -> list[dict]:
        return _parse_emails(response_text, expected_count)
    return parser


def _output_headers(num_emails: int) -> list[str]:
    """Generate output column headers for N emails."""
    headers = []
    for i in range(1, num_emails + 1):
        headers.append(f"Subject_Touch{i}")
        headers.append(f"Body_Touch{i}")
    return headers


def _make_output_headers_fn(num_emails: int):
    """Factory: return an output_headers callable bound to a specific count."""
    def fn() -> list[str]:
        return _output_headers(num_emails)
    return fn


def _flatten_emails(emails: list[dict]) -> dict[str, str]:
    """Flatten parsed emails into {column_header: value} dict for CSV assembly."""
    flat = {}
    for idx, email in enumerate(emails):
        flat[f"Subject_Touch{idx+1}"] = email.get("subject", "")
        flat[f"Body_Touch{idx+1}"] = email.get("body", "")
    return flat


# ---------------------------------------------------------------------------
# User prompt builders
# ---------------------------------------------------------------------------

def _is_email_field(key: str) -> bool:
    normalized = str(key).strip().lower().replace("_", " ").replace("-", " ")
    return normalized in {"email", "e mail", "email address", "mail"} or normalized.endswith(" email")


def _prompt_safe_value(key: str, value) -> str:
    text = str(value).strip()
    if _is_email_field(key):
        return "[provided]"
    return _EMAIL_VALUE_RE.sub("[email redacted]", text)


def _append_context_line(context_lines: list[str], key: str, value) -> None:
    if value and str(value).strip() and str(value).strip().lower() != "nan":
        context_lines.append(f"{str(key).strip()}: {_prompt_safe_value(key, value)}")

def _build_cold_email_user_prompt(lead_data: dict) -> str:
    """Build a per-lead user prompt for the original cold email template."""
    first_name = lead_data.get("first_name", "")
    last_name = lead_data.get("last_name", "")
    organization = lead_data.get("organization", "")
    license_renewal = lead_data.get("license_renewal", "")
    engagement_objectives = lead_data.get("engagement_objectives", "")

    context_lines = []
    skip_keys = {
        "first_name", "last_name", "organization",
        "license_renewal", "engagement_objectives", "row_index",
    }
    for key, value in lead_data.items():
        if key in skip_keys:
            continue
        _append_context_line(context_lines, key, value)

    demographic_block = "\n".join(context_lines) if context_lines else "No additional demographic data available."

    return f"""Generate 8 cold emails for this lead:

First Name: {first_name}
Last Name: {last_name}
Organization: {organization}
Microsoft License for Renewal: {license_renewal}
Engagement Objectives: {engagement_objectives}

Additional Demographic & Psychographic Information:
{demographic_block}

Generate the 8-email touch sequence now."""


def build_user_prompt(lead_data: dict) -> str:
    """Generic user prompt — dumps all lead columns for the model to use.

    Used by all marketing-team templates where the system prompt tells the
    model which fields are mandatory and how to use optional context.
    """
    context_lines = []
    for key, value in lead_data.items():
        if key == "row_index":
            continue
        _append_context_line(context_lines, key, value)

    data_block = "\n".join(context_lines) if context_lines else "No data available."

    return f"""Process this lead using the instructions provided:

Lead Data:
{data_block}

Generate the output now."""


# ---------------------------------------------------------------------------
# Required fields — keyword lists for column mapper
# ---------------------------------------------------------------------------

_KW_FIRST_NAME = [
    "first name", "firstname", "first_name", "fname",
    "given name", "givenname", "prenom",
]
_KW_LAST_NAME = [
    "last name", "lastname", "last_name", "lname",
    "surname", "family name", "familyname", "nom",
]
_KW_ORGANIZATION = [
    "current company", "company name", "company", "employer",
    "firm", "organization", "organisation", "org",
]
_KW_EMAIL = [
    "email", "e-mail", "email address", "email_address", "mail",
]
_KW_LICENSE = [
    "license", "licence", "renewal", "subscription", "product", "sku",
]
_KW_ENGAGEMENT = [
    "engagement", "objective", "goal", "purpose", "initiative",
]

# Field sets shared across templates
FIELDS_COLD_EMAIL = {
    "first_name": _KW_FIRST_NAME,
    "last_name": _KW_LAST_NAME,
    "organization": _KW_ORGANIZATION,
    "license_renewal": _KW_LICENSE,
    "engagement_objectives": _KW_ENGAGEMENT,
}

FIELDS_NAME_ORG = {
    "first_name": _KW_FIRST_NAME,
    "organization": _KW_ORGANIZATION,
}

FIELDS_NAME_EMAIL_ORG = {
    "first_name": _KW_FIRST_NAME,
    "organization": _KW_ORGANIZATION,
    "email_address": _KW_EMAIL,
}

FIELDS_FIRST_NAME_ONLY = {
    "first_name": _KW_FIRST_NAME,
}


# ---------------------------------------------------------------------------
# Template Registry
# ---------------------------------------------------------------------------

PROMPT_REGISTRY = {
    # --- Renewals ---
    "csp_renewal_with_license": {
        "id": "csp_renewal_with_license",
        "name": "CSP Renewal - With License",
        "group": "Renewals",
        "description": "Hyper-personalised renewal influence messages for customers with known license context. 4 emails per lead.",
        "num_emails": 4,
        "system_prompt": _load_prompt("csp_renewal_with_license"),
        "build_user_prompt": build_user_prompt,
        "parse_response": _make_parser(4),
        "output_headers": _make_output_headers_fn(4),
        "flatten_result": _flatten_emails,
        "required_fields": FIELDS_NAME_ORG,
    },
    "csp_renewal_without_license": {
        "id": "csp_renewal_without_license",
        "name": "CSP Renewal - Without License",
        "group": "Renewals",
        "description": "Discovery-led renewal influence when exact license mix is unknown. 4 emails per lead.",
        "num_emails": 4,
        "system_prompt": _load_prompt("csp_renewal_without_license"),
        "build_user_prompt": build_user_prompt,
        "parse_response": _make_parser(4),
        "output_headers": _make_output_headers_fn(4),
        "flatten_result": _flatten_emails,
        "required_fields": FIELDS_NAME_EMAIL_ORG,
    },
    "price_change": {
        "id": "price_change",
        "name": "Price Change Early Renewal",
        "group": "Renewals",
        "description": "Help customers protect current pricing ahead of Microsoft price increases. 4 emails per lead.",
        "num_emails": 4,
        "system_prompt": _load_prompt("price_change"),
        "build_user_prompt": build_user_prompt,
        "parse_response": _make_parser(4),
        "output_headers": _make_output_headers_fn(4),
        "flatten_result": _flatten_emails,
        "required_fields": FIELDS_NAME_ORG,
    },
    # --- Migrations ---
    "ea_to_csp": {
        "id": "ea_to_csp",
        "name": "EA to CSP Migration",
        "group": "Migrations",
        "description": "Position CSP as a better licensing path for EA customers. 4 emails per lead.",
        "num_emails": 4,
        "system_prompt": _load_prompt("ea_to_csp"),
        "build_user_prompt": build_user_prompt,
        "parse_response": _make_parser(4),
        "output_headers": _make_output_headers_fn(4),
        "flatten_result": _flatten_emails,
        "required_fields": FIELDS_NAME_ORG,
    },
    "e7_upsell": {
        "id": "e7_upsell",
        "name": "E7 Upsell - AI Governance",
        "group": "Migrations",
        "description": "Position E7 as the governed AI operating layer for enterprise readiness. 5 emails per lead.",
        "num_emails": 5,
        "system_prompt": _load_prompt("e7_upsell"),
        "build_user_prompt": build_user_prompt,
        "parse_response": _make_parser(5),
        "output_headers": _make_output_headers_fn(5),
        "flatten_result": _flatten_emails,
        "required_fields": FIELDS_NAME_EMAIL_ORG,
    },
    # --- Demand Generation ---
    "cloud_ascent": {
        "id": "cloud_ascent",
        "name": "CloudAscent - Solution Focus",
        "group": "Demand Generation",
        "description": "Propensity-led single-solution outreach based on Microsoft signals. 4 emails per lead.",
        "num_emails": 4,
        "system_prompt": _load_prompt("cloud_ascent"),
        "build_user_prompt": build_user_prompt,
        "parse_response": _make_parser(4),
        "output_headers": _make_output_headers_fn(4),
        "flatten_result": _flatten_emails,
        "required_fields": FIELDS_NAME_ORG,
    },
    "marketplace": {
        "id": "marketplace",
        "name": "Marketplace Offers",
        "group": "Demand Generation",
        "description": "Demand generation for Microsoft Marketplace offers. 4 emails per lead.",
        "num_emails": 4,
        "system_prompt": _load_prompt("marketplace"),
        "build_user_prompt": build_user_prompt,
        "parse_response": _make_parser(4),
        "output_headers": _make_output_headers_fn(4),
        "flatten_result": _flatten_emails,
        "required_fields": FIELDS_NAME_ORG,
    },
    "cold_email": {
        "id": "cold_email",
        "name": "Cold Email - Original",
        "group": "Demand Generation",
        "description": "8-touch cold email sequence for Microsoft licensing outreach. 8 emails per lead.",
        "num_emails": 8,
        "system_prompt": _load_prompt("cold_email"),
        "build_user_prompt": _build_cold_email_user_prompt,
        "parse_response": _make_parser(8),
        "output_headers": _make_output_headers_fn(8),
        "flatten_result": _flatten_emails,
        "required_fields": FIELDS_COLD_EMAIL,
    },
    # --- Inbound ---
    "leads": {
        "id": "leads",
        "name": "Help & Assistance - Leads",
        "group": "Inbound",
        "description": "Respond to inbound Microsoft help requests with professional outreach. 2 emails per lead.",
        "num_emails": 2,
        "system_prompt": _load_prompt("leads"),
        "build_user_prompt": build_user_prompt,
        "parse_response": _make_parser(2),
        "output_headers": _make_output_headers_fn(2),
        "flatten_result": _flatten_emails,
        "required_fields": FIELDS_FIRST_NAME_ONLY,
    },
}

# Backward-compatible alias
SYSTEM_PROMPT = _load_prompt("cold_email")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_template(template_id: str) -> dict:
    """Get a template by ID. Raises KeyError if not found."""
    return PROMPT_REGISTRY[template_id]


def list_templates() -> list[dict]:
    """Return template metadata for the frontend (id, name, group, description, num_emails)."""
    return [
        {
            "id": t["id"],
            "name": t["name"],
            "group": t["group"],
            "description": t["description"],
            "num_emails": t["num_emails"],
        }
        for t in PROMPT_REGISTRY.values()
    ]
