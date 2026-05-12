"""Workflow helpers for Snov.io verification, sync, preflight, and reports."""

from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd


EMAIL_RE = re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")

EMAIL_HEADERS = ["email", "email address", "work email", "business email", "mail"]
FIRST_NAME_HEADERS = ["first name", "firstname", "given name", "prenom"]
LAST_NAME_HEADERS = ["last name", "lastname", "surname", "family name", "nom"]
FULL_NAME_HEADERS = ["full name", "fullname", "name", "contact name", "prospect name"]
COMPANY_HEADERS = ["company", "company name", "organization", "organisation", "employer", "account"]
DOMAIN_HEADERS = ["domain", "website", "company website", "company site", "url"]
TITLE_HEADERS = ["title", "job title", "position", "role"]
COUNTRY_HEADERS = ["country"]
LOCALITY_HEADERS = ["city", "locality", "location"]
LINKEDIN_HEADERS = ["linkedin", "linked in", "linkedin url", "profile url"]

BLOCKED_STATUSES = {"not_valid", "invalid", "failed"}
UNSAFE_UNKNOWN_REASONS = {"banned", "hidden_by_owner"}
SENDING_CAMPAIGN_STATUSES = {"active", "running", "started"}


def normalize_header(value: str) -> str:
    text = str(value).strip().lower()
    text = re.sub(r"[_\-./\\]+", " ", text)
    return re.sub(r"\s+", " ", text)


def find_column(headers: list[str], candidates: list[str], disqualifiers: list[str] | None = None) -> str | None:
    normalized_candidates = [normalize_header(item) for item in candidates]
    disqualifiers = disqualifiers or []
    for header in headers:
        normalized = normalize_header(header)
        if any(word in normalized for word in disqualifiers):
            continue
        if normalized in normalized_candidates:
            return header
    for header in headers:
        normalized = normalize_header(header)
        if any(word in normalized for word in disqualifiers):
            continue
        if any(candidate in normalized for candidate in normalized_candidates):
            return header
    return None


def infer_columns(df: pd.DataFrame) -> dict[str, str | None]:
    headers = [str(col) for col in df.columns]
    return {
        "email": find_column(headers, EMAIL_HEADERS, ["status", "sent", "open", "click", "bounce", "opt"]),
        "first_name": find_column(headers, FIRST_NAME_HEADERS),
        "last_name": find_column(headers, LAST_NAME_HEADERS),
        "full_name": find_column(headers, FULL_NAME_HEADERS, ["company", "campaign", "list"]),
        "company": find_column(headers, COMPANY_HEADERS, ["domain", "website", "url", "id"]),
        "domain": find_column(headers, DOMAIN_HEADERS),
        "position": find_column(headers, TITLE_HEADERS),
        "country": find_column(headers, COUNTRY_HEADERS),
        "locality": find_column(headers, LOCALITY_HEADERS),
        "linkedin": find_column(headers, LINKEDIN_HEADERS),
    }


def clean_value(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if text.lower() == "nan":
        return ""
    return text


def row_value(row: pd.Series, column_name: str | None) -> str:
    if not column_name or column_name not in row:
        return ""
    return clean_value(row[column_name])


def extract_email(row: pd.Series, columns: dict[str, str | None]) -> str:
    direct = row_value(row, columns.get("email"))
    if direct and EMAIL_RE.fullmatch(direct):
        return direct
    for value in row.to_dict().values():
        match = EMAIL_RE.search(clean_value(value))
        if match:
            return match.group(0)
    return direct


def extract_domain(row: pd.Series, columns: dict[str, str | None]) -> str:
    domain = row_value(row, columns.get("domain"))
    domain = re.sub(r"^https?://", "", domain, flags=re.IGNORECASE).strip("/")
    if domain:
        return domain
    email = extract_email(row, columns)
    if "@" in email:
        return email.split("@", 1)[1]
    return ""


def build_job_rows(df: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, str | None]]:
    columns = infer_columns(df)
    rows = []
    for idx, row in df.iterrows():
        email = extract_email(row, columns)
        rows.append({
            "rowIndex": int(idx),
            "email": email,
            "firstName": row_value(row, columns.get("first_name")),
            "lastName": row_value(row, columns.get("last_name")),
            "fullName": row_value(row, columns.get("full_name")),
            "companyName": row_value(row, columns.get("company")),
            "companySite": extract_domain(row, columns),
            "position": row_value(row, columns.get("position")),
            "country": row_value(row, columns.get("country")),
            "locality": row_value(row, columns.get("locality")),
            "linkedin": row_value(row, columns.get("linkedin")),
        })
    return rows, columns


def get_generated_custom_fields(row: pd.Series, available_labels: set[str] | None = None) -> dict[str, str]:
    fields = {}
    for column_name, value in row.to_dict().items():
        name = str(column_name)
        if not (name.startswith("Subject_Touch") or name.startswith("Body_Touch")):
            continue
        text = clean_value(value)
        if not text:
            continue
        if available_labels is not None and name not in available_labels:
            continue
        fields[name] = text
    return fields


def build_prospect_payload(
    row: pd.Series,
    columns: dict[str, str | None],
    list_id: str,
    available_custom_fields: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    labels = None
    if available_custom_fields is not None:
        labels = {clean_value(field.get("label")) for field in available_custom_fields if clean_value(field.get("label"))}

    first_name = row_value(row, columns.get("first_name"))
    last_name = row_value(row, columns.get("last_name"))
    full_name = row_value(row, columns.get("full_name")) or " ".join(part for part in [first_name, last_name] if part).strip()
    linkedin = row_value(row, columns.get("linkedin"))

    payload: dict[str, Any] = {
        "email": extract_email(row, columns),
        "fullName": full_name,
        "firstName": first_name,
        "lastName": last_name,
        "companyName": row_value(row, columns.get("company")),
        "companySite": extract_domain(row, columns),
        "position": row_value(row, columns.get("position")),
        "country": row_value(row, columns.get("country")),
        "locality": row_value(row, columns.get("locality")),
        "listId": list_id,
        "updateContact": True,
        "createDuplicates": False,
    }
    if linkedin:
        payload["socialLinks"] = {"linkedIn": linkedin}

    custom_fields = get_generated_custom_fields(row, labels)
    if custom_fields:
        payload["customFields"] = custom_fields

    return {key: value for key, value in payload.items() if value not in ("", None, {})}


def classify_verification(item: dict[str, Any], allow_unknown: bool = False) -> dict[str, Any]:
    result = item.get("result") or item
    email = clean_value(item.get("email") or result.get("email"))
    smtp_status = clean_value(result.get("smtp_status") or result.get("smtpStatus") or "unknown").lower()
    unknown_reason = clean_value(result.get("unknown_status_reason") or result.get("unknownStatusReason")).lower()
    is_valid_format = result.get("is_valid_format", result.get("isValidFormat", True))
    is_disposable = bool(result.get("is_disposable", result.get("isDisposable", False)))
    is_webmail = bool(result.get("is_webmail", result.get("isWebmail", False)))
    is_gibberish = bool(result.get("is_gibberish", result.get("isGibberish", False)))

    blocked_reason = ""
    if not email:
        blocked_reason = "missing_email"
    elif smtp_status in BLOCKED_STATUSES:
        blocked_reason = smtp_status
    elif is_valid_format is False:
        blocked_reason = "invalid_format"
    elif is_disposable:
        blocked_reason = "disposable"
    elif is_gibberish:
        blocked_reason = "gibberish"
    elif unknown_reason in UNSAFE_UNKNOWN_REASONS:
        blocked_reason = unknown_reason
    elif smtp_status == "unknown" and not allow_unknown:
        blocked_reason = unknown_reason or "unknown"

    return {
        "email": email,
        "smtpStatus": smtp_status or "unknown",
        "isValidFormat": is_valid_format,
        "isDisposable": is_disposable,
        "isWebmail": is_webmail,
        "isGibberish": is_gibberish,
        "unknownStatusReason": unknown_reason,
        "eligible": not bool(blocked_reason),
        "blockedReason": blocked_reason,
    }


def verification_lookup(results: list[dict[str, Any]], allow_unknown: bool = False) -> dict[str, dict[str, Any]]:
    lookup = {}
    for item in results:
        classified = classify_verification(item, allow_unknown=allow_unknown)
        if classified["email"]:
            lookup[classified["email"].lower()] = classified
    return lookup


def is_suppressed(email: str, suppressed_emails: set[str], suppressed_domains: set[str]) -> str:
    normalized = email.strip().lower()
    if not normalized:
        return "missing_email"
    if normalized in suppressed_emails:
        return "suppressed_email"
    domain = normalized.split("@", 1)[1] if "@" in normalized else ""
    if domain in suppressed_domains:
        return "suppressed_domain"
    return ""


def is_sending_campaign(campaign: dict[str, Any] | None) -> bool:
    if not campaign:
        return False
    status = clean_value(campaign.get("status")).lower()
    return status in SENDING_CAMPAIGN_STATUSES


def find_campaign(campaigns: list[dict[str, Any]], campaign_id: str) -> dict[str, Any] | None:
    for campaign in campaigns:
        if str(campaign.get("id")) == str(campaign_id):
            return campaign
    return None


def estimate_usage(lead_count: int, operation: str = "sync") -> dict[str, Any]:
    operation = operation.lower()
    estimates = {
        "sync": {"creditsPerLead": 0, "requests": lead_count},
        "verify": {"creditsPerLead": 1, "requests": math.ceil(lead_count / 10)},
        "enrich": {"creditsPerLead": 1, "requests": math.ceil(lead_count / 10)},
        "full": {"creditsPerLead": 2, "requests": math.ceil(lead_count / 10) * 2 + lead_count},
    }
    selected = estimates.get(operation, estimates["sync"])
    credits = selected["creditsPerLead"] * lead_count
    return {
        "operation": operation,
        "leadCount": lead_count,
        "estimatedCredits": credits,
        "estimatedRequests": selected["requests"],
        "estimatedMinutesAtRateLimit": math.ceil(selected["requests"] / 60) if selected["requests"] else 0,
    }


def summarize_report(rows: list[dict[str, Any]]) -> dict[str, int]:
    summary = {"total": len(rows), "eligible": 0, "blocked": 0, "added": 0, "updated": 0, "skipped": 0, "failed": 0}
    for row in rows:
        if row.get("eligible"):
            summary["eligible"] += 1
        if row.get("blockedReason"):
            summary["blocked"] += 1
        status = row.get("status")
        if status in summary:
            summary[status] += 1
    return summary