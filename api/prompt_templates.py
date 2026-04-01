"""Prompt templates registry — multiple system prompts for different generation tasks."""

import json
import logging

logger = logging.getLogger("emailmvp")

# ---------------------------------------------------------------------------
# Cold Email Template
# ---------------------------------------------------------------------------

COLD_EMAIL_SYSTEM_PROMPT = """You are an expert cold email copywriter for Reliance Infosystems, a Microsoft Solutions Partner.
Reliance Infosystems helps organizations manage, renew, upgrade, and optimize their Microsoft licensing.
The recipient does NOT know Reliance Infosystems. These are cold outreach emails.

Generate exactly 8 emails as a JSON array. Each email object has "subject" and "body" keys.

Touch sequence purposes:
1. Introduction — Introduce Reliance as a trusted Microsoft licensing advisor. Open with a warm, non-pushy greeting that acknowledges the recipient's role and organization. Briefly position Reliance as a partner who simplifies Microsoft licensing renewals.
2. Diagnostic — Ask a diagnostic question about their renewal or licensing pain points. Frame the question around common challenges (compliance gaps, over-licensing, budget pressure) to spark self-reflection.
3. Benefit — Highlight specific, tangible benefits of working with a Microsoft partner for renewals. Focus on outcomes: cost savings, compliance assurance, streamlined procurement, dedicated support.
4. Social Proof (anonymized) — Reference anonymized success stories from organizations in a similar industry or of similar size. Use phrases like "a mid-size logistics firm" or "a financial services company" — never reveal real names.
5. Authority — Position Reliance as a Microsoft-authorized, expert licensing partner. Reference Microsoft competencies, certifications, and deep expertise across Microsoft 365, Azure, Dynamics 365, and security solutions.
6. Promo Canvas — Reference current or recent Microsoft promotions, incentives, or licensing programs that may be relevant to the contact's renewal. Examples include: Microsoft FastTrack, Azure Hybrid Benefit, Microsoft 365 E5 Security add-on trials, CSP migration incentives, EA-to-MCA transition benefits, Software Assurance training vouchers, or seasonal end-of-quarter/end-of-fiscal-year promotional pricing. Tailor to common enterprise licensing scenarios without referencing specific license details from the lead's data.
7. Switch Plan / Risk Reversal — Address the perceived risk of switching licensing partners. Offer guarantees like a no-obligation licensing audit, seamless migration support, same-day response SLAs, or a dedicated account manager. Make switching feel easy and low-risk.
8. Danger / Close the Loop — Create urgency around renewal deadlines, potential compliance risks, or the cost of inaction. Frame this as the final outreach in the sequence. Include a clear, soft call to action (e.g., "Would a brief conversation be worthwhile?").

HARD CONSTRAINTS (every email MUST satisfy ALL):
- Subject: maximum 7 words
- Body: exactly 200–260 words (count carefully)
- Tone: calm, human, advisory, outcomes-driven
- At least 3 paragraphs in the body
- Include a closing phrase (e.g., "Warm regards," or "Kind regards,")
- NO signature block (no names, titles, phone numbers, links)
- NO links anywhere in the email content
- NO URLs, no "click here", no hyperlinks
- Use only plain ASCII characters — no em dashes, curly quotes, or special Unicode characters. Use regular hyphens (-), straight quotes (" and '), and standard punctuation only.
- Address the recipient by first name in each email
- NEVER mention specific license types (e.g., "Office 365 E3", "E1", "Microsoft 365 Business Basic", "Intune Suite", "Power BI Pro") or exact seat counts/quantities (e.g., "941 seats", "several hundred licenses"). The recipient must not feel we have detailed knowledge of their environment. Instead, use vague references like "your Microsoft environment", "your Microsoft licensing setup", "your upcoming renewal", or "your organization's Microsoft investment". You may acknowledge they use Microsoft products generally, but never enumerate specific SKUs, product names, or quantities.
- Personalize based on the recipient's name, organization, role, industry, and engagement objectives — but NOT based on specific license details

OUTPUT FORMAT:
Return ONLY a valid JSON array with exactly 8 objects:
[
  {"subject": "...", "body": "..."},
  {"subject": "...", "body": "..."},
  {"subject": "...", "body": "..."},
  {"subject": "...", "body": "..."},
  {"subject": "...", "body": "..."},
  {"subject": "...", "body": "..."},
  {"subject": "...", "body": "..."},
  {"subject": "...", "body": "..."}
]
No markdown, no code fences, no explanation. Just the JSON array."""

# Backward-compatible alias
SYSTEM_PROMPT = COLD_EMAIL_SYSTEM_PROMPT


def _build_cold_email_user_prompt(lead_data: dict) -> str:
    """Build a per-lead user prompt for cold email generation."""
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
        if value and str(value).strip() and str(value).strip().lower() != "nan":
            context_lines.append(f"{key}: {value}")

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


def _parse_cold_email_response(response_text: str) -> list[dict]:
    """Parse GPT response into list of email dicts. Raises on invalid format."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    emails = json.loads(text)

    if not isinstance(emails, list) or len(emails) != 8:
        raise ValueError(
            f"Expected 8 emails, got {len(emails) if isinstance(emails, list) else 'non-list'}"
        )

    for i, email in enumerate(emails):
        if "subject" not in email or "body" not in email:
            raise ValueError(f"Email {i+1} missing 'subject' or 'body' key")

    return emails


def _cold_email_output_headers() -> list[str]:
    """Return the output column headers for cold email template."""
    headers = []
    for i in range(1, 9):
        headers.append(f"Subject_Touch{i}")
        headers.append(f"Body_Touch{i}")
    return headers


def _flatten_cold_email(emails: list[dict]) -> dict[str, str]:
    """Flatten parsed emails into {column_header: value} dict for CSV assembly."""
    flat = {}
    for idx, email in enumerate(emails):
        flat[f"Subject_Touch{idx+1}"] = email.get("subject", "")
        flat[f"Body_Touch{idx+1}"] = email.get("body", "")
    return flat


# ---------------------------------------------------------------------------
# E-Invoice Outreach Template
# ---------------------------------------------------------------------------

E_INVOICE_SYSTEM_PROMPT = """You are a senior B2B sales strategist and outreach copywriter specializing in African digital finance — specifically e-invoicing, e-payment, and Microsoft-based ERP/finance modernization.

Your client: Reliance Infosystems (a Microsoft Solutions Partner). They help African organizations modernize their invoicing, payment, and financial processes using Microsoft solutions (Dynamics 365, Power Platform, Azure).

The recipient does NOT know Reliance Infosystems. These are cold outreach messages.

---

PERSONA SELECTION LOGIC

Based on the contact's title, seniority, and department, select ONE persona:

| Persona Tag        | Who it targets                                   | Tone & Focus |
|--------------------|--------------------------------------------------|--------------|
| CFO_FINANCE        | CFO, Finance Director, VP Finance, Controller    | ROI, compliance risk, cash flow, audit readiness |
| CTO_IT             | CTO, IT Director, Head of IT, VP Technology      | Integration, automation, API reliability, security |
| CEO_MD             | CEO, Managing Director, General Manager, Founder | Strategic growth, competitive advantage, board-level simplicity |
| PROCUREMENT_OPS    | Procurement Manager, Operations Head, Supply Chain | Process efficiency, vendor management, approval workflows |
| GENERAL_BUSINESS   | Any title that does not clearly fit above         | Balanced: cost savings + efficiency + modernization |

If the contact's title is empty or ambiguous, default to GENERAL_BUSINESS.

---

CHANNEL STRATEGY

Based on the persona AND the contact's likely communication preferences:
- If email_address is a corporate domain: prefer "email_first" strategy
- If email_address is personal (gmail, yahoo, etc.): prefer "linkedin_first" strategy
- Always include both channels in the sequence regardless of strategy

---

GENERATION RULES

Generate exactly 5 outreach scripts as a JSON object. The top level has:
- "persona_selected": the persona tag you chose (string)
- "channel_strategy": "email_first" or "linkedin_first" (string)
- "scripts": array of exactly 5 objects

Each script object has these keys:
- "touch_number": integer (1-5)
- "touch_type": one of "Introduction", "Value Proposition", "Social Proof", "Objection Handler", "Final Push"
- "channel": "email" or "linkedin"
- "subject": string (email subjects max 7 words; LinkedIn messages use "" empty string for subject)
- "message_body": string (the full message text)
- "cta": string (the call-to-action, separate from body)
- "send_delay_days": integer (days after previous touch; touch 1 = 0)

Touch sequence:
1. Introduction (Day 0) — Warm opener acknowledging the contact's role and African business context. Position e-invoicing modernization as timely and relevant.
2. Value Proposition (Day 3) — Specific benefits: compliance with emerging e-invoicing regulations across Africa, cash flow improvement, reduced manual processes, integration with existing Microsoft stack.
3. Social Proof (Day 7) — Anonymized success story from a similar African organization or industry. Use phrases like "a financial services company in West Africa" or "a logistics firm in East Africa" — never reveal real names.
4. Objection Handler (Day 12) — Address common concerns: implementation disruption, cost, integration complexity, change management. Provide risk-reversal guarantees.
5. Final Push (Day 18) — Create urgency around regulatory timelines, competitive advantage, or fiscal year budgeting. Clear, soft CTA.

HARD CONSTRAINTS (every script MUST satisfy ALL):
- message_body: 150-200 words
- Tone: professional, consultative, culturally aware of African business context
- At least 2 paragraphs in message_body
- NO signature block (no names, titles, phone numbers, links)
- NO URLs, no "click here", no hyperlinks
- Use only plain ASCII characters — no em dashes, curly quotes, or special Unicode
- Address the recipient by first name
- Reference their organization naturally
- LinkedIn messages should feel conversational, not email-like
- Email messages should be slightly more formal than LinkedIn

VALIDATION RULES — if ANY are true, set "do_not_generate" to true and return a minimal object:
- first_name is empty AND organisation_name is empty
- email_address is clearly invalid (no @ symbol, clearly fake)

For do_not_generate leads, return:
{"persona_selected": "NONE", "channel_strategy": "none", "scripts": [], "do_not_generate": true, "reason": "..."}

OUTPUT FORMAT:
Return ONLY a valid JSON object:
{
  "persona_selected": "CFO_FINANCE",
  "channel_strategy": "email_first",
  "do_not_generate": false,
  "scripts": [
    {"touch_number": 1, "touch_type": "Introduction", "channel": "email", "subject": "...", "message_body": "...", "cta": "...", "send_delay_days": 0},
    {"touch_number": 2, "touch_type": "Value Proposition", "channel": "linkedin", "subject": "", "message_body": "...", "cta": "...", "send_delay_days": 3},
    {"touch_number": 3, "touch_type": "Social Proof", "channel": "email", "subject": "...", "message_body": "...", "cta": "...", "send_delay_days": 7},
    {"touch_number": 4, "touch_type": "Objection Handler", "channel": "linkedin", "subject": "", "message_body": "...", "cta": "...", "send_delay_days": 12},
    {"touch_number": 5, "touch_type": "Final Push", "channel": "email", "subject": "...", "message_body": "...", "cta": "...", "send_delay_days": 18}
  ]
}
No markdown, no code fences, no explanation. Just the JSON object."""


def _build_e_invoice_user_prompt(lead_data: dict) -> str:
    """Build a per-lead user prompt for e-invoice outreach generation."""
    first_name = lead_data.get("first_name", "")
    last_name = lead_data.get("last_name", "")
    organisation_name = lead_data.get("organisation_name", "")
    email_address = lead_data.get("email_address", "")

    context_lines = []
    skip_keys = {
        "first_name", "last_name", "organisation_name", "email_address", "row_index",
    }
    for key, value in lead_data.items():
        if key in skip_keys:
            continue
        if value and str(value).strip() and str(value).strip().lower() != "nan":
            context_lines.append(f"{key}: {value}")

    demographic_block = "\n".join(context_lines) if context_lines else "No additional data available."

    return f"""Generate 5 outreach scripts for this lead:

First Name: {first_name}
Last Name: {last_name}
Organisation: {organisation_name}
Email Address: {email_address}

Additional Information:
{demographic_block}

Generate the 5-script outreach sequence now."""


def _parse_e_invoice_response(response_text: str) -> list[dict]:
    """Parse GPT response for e-invoice template. Returns list with single result dict."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    result = json.loads(text)

    if not isinstance(result, dict):
        raise ValueError("Expected a JSON object, got " + type(result).__name__)

    # do_not_generate leads
    if result.get("do_not_generate"):
        return [result]

    scripts = result.get("scripts", [])
    if not isinstance(scripts, list) or len(scripts) != 5:
        raise ValueError(
            f"Expected 5 scripts, got {len(scripts) if isinstance(scripts, list) else 'non-list'}"
        )

    return [result]


def _e_invoice_output_headers() -> list[str]:
    """Return the output column headers for e-invoice template."""
    headers = ["Persona_Selected", "Channel_Strategy", "Do_Not_Generate", "DNG_Reason"]
    for i in range(1, 6):
        headers.extend([
            f"Touch{i}_Type",
            f"Touch{i}_Channel",
            f"Touch{i}_Subject",
            f"Touch{i}_Body",
            f"Touch{i}_CTA",
            f"Touch{i}_Delay_Days",
        ])
    return headers


def _flatten_e_invoice(parsed: list[dict]) -> dict[str, str]:
    """Flatten parsed e-invoice result into {column_header: value} dict."""
    result = parsed[0]
    flat = {
        "Persona_Selected": result.get("persona_selected", ""),
        "Channel_Strategy": result.get("channel_strategy", ""),
        "Do_Not_Generate": str(result.get("do_not_generate", False)),
        "DNG_Reason": result.get("reason", ""),
    }

    scripts = result.get("scripts", [])
    for i in range(1, 6):
        if i <= len(scripts):
            s = scripts[i - 1]
            flat[f"Touch{i}_Type"] = s.get("touch_type", "")
            flat[f"Touch{i}_Channel"] = s.get("channel", "")
            flat[f"Touch{i}_Subject"] = s.get("subject", "")
            flat[f"Touch{i}_Body"] = s.get("message_body", "")
            flat[f"Touch{i}_CTA"] = s.get("cta", "")
            flat[f"Touch{i}_Delay_Days"] = str(s.get("send_delay_days", ""))
        else:
            flat[f"Touch{i}_Type"] = ""
            flat[f"Touch{i}_Channel"] = ""
            flat[f"Touch{i}_Subject"] = ""
            flat[f"Touch{i}_Body"] = ""
            flat[f"Touch{i}_CTA"] = ""
            flat[f"Touch{i}_Delay_Days"] = ""

    return flat


# ---------------------------------------------------------------------------
# Custom Prompt Template
# ---------------------------------------------------------------------------

CUSTOM_SYSTEM_PROMPT_WRAPPER = """You are an AI assistant. Follow the user's instructions precisely.

IMPORTANT: Return your response as a valid JSON array of objects. Each object represents one generated item.
No markdown, no code fences, no explanation. Just the JSON array."""


def _build_custom_user_prompt(lead_data: dict) -> str:
    """Build a user prompt that dumps all lead data for a custom template."""
    context_lines = []
    skip_keys = {"row_index"}
    for key, value in lead_data.items():
        if key in skip_keys:
            continue
        if value and str(value).strip() and str(value).strip().lower() != "nan":
            context_lines.append(f"{key}: {value}")

    data_block = "\n".join(context_lines) if context_lines else "No data available."

    return f"""Process this lead using the instructions in the system prompt:

Lead Data:
{data_block}

Generate the output now."""


def _parse_custom_response(response_text: str) -> list[dict]:
    """Parse a custom prompt response — accepts JSON array or JSON object."""
    text = response_text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        lines = [l for l in lines if not l.strip().startswith("```")]
        text = "\n".join(lines)

    parsed = json.loads(text)

    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return parsed

    raise ValueError(f"Expected JSON array or object, got {type(parsed).__name__}")


def _custom_output_headers_from_parsed(parsed: list[dict]) -> list[str]:
    """Dynamically discover output headers from parsed custom response."""
    headers = []
    seen = set()

    def _collect_keys(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_key = f"{prefix}{k}" if not prefix else f"{prefix}_{k}"
                if isinstance(v, (dict, list)):
                    _collect_keys(v, full_key)
                else:
                    if full_key not in seen:
                        seen.add(full_key)
                        headers.append(full_key)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _collect_keys(item, f"{prefix}_Item{i+1}")

    for item in parsed:
        _collect_keys(item)

    return headers


def _flatten_custom(parsed: list[dict]) -> dict[str, str]:
    """Flatten a custom response into {column_header: value} dict."""
    flat = {}

    def _flatten_obj(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                full_key = f"{prefix}{k}" if not prefix else f"{prefix}_{k}"
                if isinstance(v, (dict, list)):
                    _flatten_obj(v, full_key)
                else:
                    flat[full_key] = str(v) if v is not None else ""
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _flatten_obj(item, f"{prefix}_Item{i+1}")

    for item in parsed:
        _flatten_obj(item)

    return flat


# ---------------------------------------------------------------------------
# Template Registry
# ---------------------------------------------------------------------------

PROMPT_REGISTRY = {
    "cold_email": {
        "id": "cold_email",
        "name": "Cold Email Sequences",
        "description": "Generate 8 personalized cold emails per lead for Microsoft licensing outreach.",
        "system_prompt": COLD_EMAIL_SYSTEM_PROMPT,
        "build_user_prompt": _build_cold_email_user_prompt,
        "parse_response": _parse_cold_email_response,
        "output_headers": _cold_email_output_headers,
        "flatten_result": _flatten_cold_email,
        "num_outputs": 8,
        "output_label": "emails",
        "required_fields": {
            "first_name": ["first name", "firstname", "first_name", "fname", "given name", "givenname", "prenom"],
            "last_name": ["last name", "lastname", "last_name", "lname", "surname", "family name", "familyname", "nom"],
            "organization": ["current company", "company name", "company", "employer", "firm", "organization", "organisation", "org"],
            "license_renewal": ["license", "licence", "renewal", "subscription", "product", "sku"],
            "engagement_objectives": ["engagement", "objective", "goal", "purpose", "initiative"],
        },
    },
    "e_invoice": {
        "id": "e_invoice",
        "name": "E-Invoice Outreach",
        "description": "Generate 5 outreach scripts per lead for e-invoicing and digital finance modernization.",
        "system_prompt": E_INVOICE_SYSTEM_PROMPT,
        "build_user_prompt": _build_e_invoice_user_prompt,
        "parse_response": _parse_e_invoice_response,
        "output_headers": _e_invoice_output_headers,
        "flatten_result": _flatten_e_invoice,
        "num_outputs": 5,
        "output_label": "scripts",
        "required_fields": {
            "first_name": ["first name", "firstname", "first_name", "fname", "given name", "givenname", "prenom"],
            "last_name": ["last name", "lastname", "last_name", "lname", "surname", "family name", "familyname", "nom"],
            "organisation_name": ["current company", "company name", "company", "employer", "firm", "organization", "organisation", "org"],
            "email_address": ["email", "e-mail", "email address", "email_address", "mail"],
        },
    },
}

# Maximum character length for custom prompts
MAX_CUSTOM_PROMPT_LENGTH = 10000


def get_template(template_id: str) -> dict:
    """Get a template by ID. Raises KeyError if not found."""
    return PROMPT_REGISTRY[template_id]


def list_templates() -> list[dict]:
    """Return a list of available templates (id, name, description) for the frontend."""
    return [
        {"id": t["id"], "name": t["name"], "description": t["description"]}
        for t in PROMPT_REGISTRY.values()
    ]


def build_custom_template(custom_prompt: str) -> dict:
    """Build a runtime template from a user-supplied custom prompt."""
    if len(custom_prompt) > MAX_CUSTOM_PROMPT_LENGTH:
        raise ValueError(
            f"Custom prompt too long ({len(custom_prompt)} chars). "
            f"Maximum is {MAX_CUSTOM_PROMPT_LENGTH} characters."
        )

    return {
        "id": "custom",
        "name": "Custom Prompt",
        "description": "User-supplied custom prompt.",
        "system_prompt": custom_prompt,
        "build_user_prompt": _build_custom_user_prompt,
        "parse_response": _parse_custom_response,
        "output_headers": None,  # Discovered dynamically from first response
        "flatten_result": _flatten_custom,
        "num_outputs": None,  # Unknown
        "output_label": "items",
        "required_fields": None,  # Skip column mapping — pass all columns
    }


# Backward-compatible alias
def build_user_prompt(lead_data: dict) -> str:
    """Build a cold email user prompt (backward-compatible alias)."""
    return _build_cold_email_user_prompt(lead_data)
