"""Smart column detection — fuzzy header matching with LLM fallback."""

import json
import logging
import re

logger = logging.getLogger("emailmvp")

# The five required fields and keyword patterns for fuzzy matching.
# Keys are the internal field names used throughout the app.
# Values are lists of lowercase substrings / patterns to match against headers.
# This is the DEFAULT set used when no template-specific fields are provided.
REQUIRED_FIELDS = {
    "first_name": ["first name", "firstname", "first_name", "fname", "given name", "givenname", "prenom"],
    "last_name": ["last name", "lastname", "last_name", "lname", "surname", "family name", "familyname", "nom"],
    "organization": ["current company", "company name", "company", "employer", "firm", "organization", "organisation", "org"],
    "license_renewal": ["license", "licence", "renewal", "subscription", "product", "sku"],
    "engagement_objectives": ["engagement", "objective", "goal", "purpose", "initiative"],
}

# Words that disqualify a header from matching a field, even if a keyword matches.
# Prevents e.g. "organization_domain_1" from matching the organization field.
_DISQUALIFY = {
    "organization": ["domain", "url", "id", "start", "end", "description", "location", "website", "position", "industry", "title"],
    "organisation_name": ["domain", "url", "id", "start", "end", "description", "location", "website", "position", "industry", "title"],
    "email_address": ["campaign", "id", "status", "type", "template", "sent", "open", "click", "bounce", "opt"],
}

# Keywords that identify a single combined "Full Name" column. Used as a fallback to
# derive first/last name when those dedicated columns are absent.
_FULL_NAME_KEYWORDS = ["full name", "fullname", "contact name", "prospect name", "lead name", "contact"]

# Human-friendly labels for required fields, used in error messages.
_FRIENDLY_FIELD = {
    "first_name": "First Name",
    "last_name": "Last Name",
    "organization": "Company / Organization",
    "organisation_name": "Company / Organization",
    "email_address": "Email",
    "license_renewal": "License or Renewal info",
    "engagement_objectives": "Engagement objective",
}


def _friendly_field(field: str) -> str:
    return _FRIENDLY_FIELD.get(field, field.replace("_", " ").title())


def find_full_name_column(headers: list[str], used_indices: set[int]) -> int | None:
    """Find a single combined full-name column, skipping first/last/company columns."""
    for idx, header in enumerate(headers):
        if idx in used_indices:
            continue
        norm = _normalize(header)
        if any(skip in norm for skip in ("first", "last", "surname", "given", "company", "organi", "user")):
            continue
        if any(kw in norm for kw in _FULL_NAME_KEYWORDS):
            return idx
    # Accept a bare "name" column only if nothing more specific matched.
    for idx, header in enumerate(headers):
        if idx in used_indices:
            continue
        if _normalize(header) == "name":
            return idx
    return None



def _normalize(header: str) -> str:
    """Lowercase, strip, collapse whitespace and remove common punctuation."""
    h = header.lower().strip()
    h = re.sub(r"[_\-./\\]+", " ", h)
    h = re.sub(r"\s+", " ", h)
    return h


def _is_disqualified(field: str, normalized_header: str) -> bool:
    """Check if a header is disqualified from matching a field."""
    for dq in _DISQUALIFY.get(field, []):
        if dq in normalized_header:
            return True
    return False


def fuzzy_match_columns(headers: list[str], required_fields: dict | None = None) -> dict[str, int | None]:
    """Match spreadsheet headers to required fields using keyword patterns.

    Args:
        headers: List of column header strings from the spreadsheet.
        required_fields: Optional dict mapping field names to keyword lists.
                         Defaults to REQUIRED_FIELDS if not provided.

    Returns a dict mapping each required field name to its column index, or None
    if no confident match was found.
    """
    fields = required_fields or REQUIRED_FIELDS
    matched: dict[str, int | None] = {field: None for field in fields}
    used_indices: set[int] = set()

    for field, keywords in fields.items():
        for idx, header in enumerate(headers):
            if idx in used_indices:
                continue
            norm = _normalize(header)
            if _is_disqualified(field, norm):
                continue
            for kw in keywords:
                if kw in norm:
                    matched[field] = idx
                    used_indices.add(idx)
                    break
            if matched[field] is not None:
                break

    return matched


def llm_match_columns(
    headers: list[str],
    unresolved: list[str],
    client,
    deployment: str,
) -> dict[str, int | None]:
    """Use GPT to resolve remaining unmatched fields.

    Args:
        headers: The full list of column headers from the spreadsheet.
        unresolved: List of field names that fuzzy matching could not resolve.
        client: An AzureOpenAI client instance.
        deployment: The model deployment name.

    Returns:
        A dict mapping each unresolved field to its column index, or None.
    """
    prompt = (
        "You are a data-mapping assistant. A user uploaded a spreadsheet with these column headers:\n"
        f"{json.dumps(headers)}\n\n"
        "Map each of the following required fields to the BEST matching column header index (0-based). "
        "If no column is a reasonable match, use null.\n\n"
        "Required fields:\n"
    )
    for field in unresolved:
        prompt += f"- {field}\n"

    prompt += (
        "\nRespond with ONLY a JSON object mapping field names to column indices (integers) or null. "
        "Example: {\"first_name\": 3, \"organization\": null}\n"
        "No explanation, no markdown fences."
    )

    try:
        completion = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "user", "content": prompt}],
            max_completion_tokens=256,
        )
        text = (completion.choices[0].message.content or "").strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        mapping = json.loads(text)
        result: dict[str, int | None] = {}
        for field in unresolved:
            val = mapping.get(field)
            if isinstance(val, int) and 0 <= val < len(headers):
                result[field] = val
            else:
                result[field] = None
        return result

    except Exception as e:
        logger.warning("LLM column mapping failed: %s", e)
        return {field: None for field in unresolved}


def _resolve_core(headers: list[str], client, deployment: str, fields: dict):
    """Shared detection core. Returns (result, matched, full_idx, still_missing).

    ``result`` maps directly-resolved fields (and ``full_name`` when first/last are
    derived from it) to indices. ``matched`` includes first/last keys pointing at the
    full-name column when derived. ``still_missing`` lists fields with no column.
    """
    matched = fuzzy_match_columns(headers, fields)

    unresolved = [f for f, idx in matched.items() if idx is None]

    if unresolved and client:
        llm_result = llm_match_columns(headers, unresolved, client, deployment)
        for field, idx in llm_result.items():
            if idx is not None:
                matched[field] = idx

    result = {f: idx for f, idx in matched.items() if idx is not None}

    # Full-name fallback: if first_name and/or last_name are required but still
    # unmatched, derive them from a single "Full Name" column (split at extraction
    # time) instead of rejecting the upload. extract_lead_data handles the split.
    full_idx = None
    missing_name_fields = [f for f in fields if f in ("first_name", "last_name") and matched.get(f) is None]
    if missing_name_fields:
        full_idx = find_full_name_column(headers, set(result.values()))
        if full_idx is not None:
            result["full_name"] = full_idx
            for f in missing_name_fields:
                matched[f] = full_idx  # mark satisfied (value derived from full name)

    still_missing = [f for f, idx in matched.items() if idx is None]
    return result, matched, full_idx, still_missing


def resolve_columns(
    headers: list[str],
    client=None,
    deployment: str = "",
    required_fields: dict | None = None,
) -> dict[str, int]:
    """Resolve all required fields to column indices, raising if any is missing.

    1. Fuzzy-match first.
    2. For any unresolved fields, try LLM if a client is provided.
    3. Derive first/last name from a "Full Name" column when present.
    4. Raise ValueError if any required field is still unresolved.
    """
    fields = required_fields or REQUIRED_FIELDS
    result, _matched, _full_idx, still_missing = _resolve_core(headers, client, deployment, fields)
    if still_missing:
        missing_labels = ", ".join(_friendly_field(f) for f in still_missing)
        all_labels = ", ".join(_friendly_field(f) for f in fields)
        raise ValueError(
            f"Could not find a column for: {missing_labels}. "
            f"This campaign needs columns for: {all_labels}. "
            f"Tip: a single \u201cFull Name\u201d column can stand in for First/Last Name."
        )

    # full_name (when present) is returned so extraction can split it; the dedicated
    # first_name/last_name keys are omitted when derived from it.
    return result


def detect_columns(
    headers: list[str],
    client=None,
    deployment: str = "",
    required_fields: dict | None = None,
) -> dict:
    """Detect column mapping WITHOUT raising — powers the review/correction UI.

    Returns a dict with one entry per required field (best-guess column index,
    friendly label, and whether it was derived from a Full Name column), plus the
    list of unresolved fields and the detected full-name column index (if any).
    """
    fields = required_fields or REQUIRED_FIELDS
    result, matched, full_idx, still_missing = _resolve_core(headers, client, deployment, fields)
    field_info = []
    for f in fields:
        idx = matched.get(f)
        derived = f in ("first_name", "last_name") and f not in result and idx is not None and idx == full_idx
        field_info.append({
            "field": f,
            "label": _friendly_field(f),
            "index": idx,
            "derivedFromFullName": bool(derived),
        })
    return {
        "fields": field_info,
        "unresolved": still_missing,
        "fullNameIndex": full_idx,
    }
