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
}


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


def resolve_columns(
    headers: list[str],
    client=None,
    deployment: str = "",
    required_fields: dict | None = None,
) -> dict[str, int]:
    """Resolve all required fields to column indices.

    1. Fuzzy-match first.
    2. For any unresolved fields, try LLM if a client is provided.
    3. Raise ValueError if any required field is still unresolved.

    Args:
        headers: List of column header strings.
        client: Optional AzureOpenAI client for LLM fallback.
        deployment: Model deployment name.
        required_fields: Optional dict mapping field names to keyword lists.
                         Defaults to REQUIRED_FIELDS if not provided.

    Returns:
        A dict mapping each required field name to its 0-based column index.
    """
    fields = required_fields or REQUIRED_FIELDS
    matched = fuzzy_match_columns(headers, fields)

    unresolved = [f for f, idx in matched.items() if idx is None]

    if unresolved and client:
        llm_result = llm_match_columns(headers, unresolved, client, deployment)
        for field, idx in llm_result.items():
            if idx is not None:
                matched[field] = idx

    # Check for any still-unresolved fields
    still_missing = [f for f, idx in matched.items() if idx is None]
    if still_missing:
        raise ValueError(
            f"Could not detect required columns: {', '.join(still_missing)}. "
            f"Please ensure your file has columns for: "
            f"{', '.join(fields.keys())}"
        )

    # At this point every value is an int (not None)
    return {f: idx for f, idx in matched.items() if idx is not None}
