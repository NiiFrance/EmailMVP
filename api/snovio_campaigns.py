"""Helpers for building Snov.io drip campaigns ("customer journeys").

A campaign step holds a single content template; per-recipient personalization is
delivered through Snov.io merge variables. To preserve the unique, per-lead emails
produced by the generator we store each touch as a prospect custom field
(``Subject_Touch{n}`` / ``Body_Touch{n}``) and reference it from the matching email
step via a merge variable. The result is one campaign in which every recipient
receives their own drafted content for each touch.

The campaign is always built in Snov.io's ``new``/draft state. Launching is left to
a human in the Snov.io UI.
"""

from __future__ import annotations

import re
import time
from typing import Any


# Column headers emitted by the generator for each touch.
SUBJECT_PREFIX = "Subject_Touch"
BODY_PREFIX = "Body_Touch"

_TOUCH_RE = re.compile(r"^(Subject|Body)_Touch(\d+)$")


def merge_field(label: str) -> str:
    """Return the Snov.io merge-variable token for a custom field label.

    Snov.io renders prospect variables with ``{{label}}`` syntax. Custom fields use
    the same form, so a field named ``Body_Touch1`` is referenced as ``{{Body_Touch1}}``.
    """
    return "{{" + label + "}}"


def touch_field_labels(num_touches: int) -> list[str]:
    """Return the ordered custom-field labels required for ``num_touches`` touches."""
    if num_touches < 1:
        raise ValueError("num_touches must be >= 1.")
    labels: list[str] = []
    for touch in range(1, num_touches + 1):
        labels.append(f"{SUBJECT_PREFIX}{touch}")
        labels.append(f"{BODY_PREFIX}{touch}")
    return labels


def detect_touch_count(headers: list[str]) -> int:
    """Infer the number of touches from generated CSV headers.

    Looks for ``Body_Touch{n}`` columns and returns the highest contiguous ``n``
    that also has a matching ``Subject_Touch{n}`` column.
    """
    subjects: set[int] = set()
    bodies: set[int] = set()
    for header in headers:
        match = _TOUCH_RE.match(str(header).strip())
        if not match:
            continue
        kind, number = match.group(1), int(match.group(2))
        (subjects if kind == "Subject" else bodies).add(number)

    touch = 0
    while (touch + 1) in subjects and (touch + 1) in bodies:
        touch += 1
    return touch


def build_campaign_sequence(
    num_touches: int,
    delay_days: int = 3,
    goal_name: str = "end",
    ref_seed: int | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Build a Snov.io campaign sequence of ``num_touches`` email steps.

    Steps alternate email -> delay -> email -> ... -> goal. A delay is inserted
    between consecutive emails only when ``delay_days`` is greater than zero.

    Returns a tuple of ``(sequence, email_refs)`` where ``email_refs`` is the ordered
    list of email step ``_ref`` identifiers (touch 1..N) so callers can attach content
    after the campaign is created.
    """
    if num_touches < 1:
        raise ValueError("num_touches must be >= 1.")
    if delay_days < 0:
        raise ValueError("delay_days must be >= 0.")

    base = int(ref_seed if ref_seed is not None else time.time() * 1000)
    goal_ref = str(base + 9_000_000)
    steps: list[dict[str, Any]] = []
    email_refs: list[str] = []

    for index in range(num_touches):
        email_ref = str(base + index * 2)
        email_refs.append(email_ref)
        is_last = index == num_touches - 1

        if is_last:
            next_ref = goal_ref
        elif delay_days > 0:
            next_ref = str(base + index * 2 + 1)
        else:
            next_ref = str(base + (index + 1) * 2)

        steps.append({
            "_ref": email_ref,
            "type": "email",
            "content_slots": 1,
            "next": next_ref,
        })

        if not is_last and delay_days > 0:
            steps.append({
                "_ref": str(base + index * 2 + 1),
                "type": "delay",
                "waiting_type": "days",
                "waiting_val": delay_days,
                "next": str(base + (index + 1) * 2),
            })

    steps.append({"_ref": goal_ref, "type": "goal", "goal_name": goal_name})

    return {"entry": email_refs[0], "steps": steps}, email_refs


def build_campaign_payload(
    title: str,
    email_account_ids: list[int],
    list_id: str | int,
    sequence: dict[str, Any],
    *,
    priority: str = "medium",
    track_opens: bool = True,
    track_clicks: bool = True,
    schedule_id: int | None = None,
    timezone: str | None = None,
    black_list_id: int | None = None,
    daily_sending_all: int | None = None,
    daily_sending_new_recipients: int | None = None,
    archive_in_months: int = 3,
    complete_after_last_step: bool = True,
    skip_who_replied: bool = True,
    provider_matching: bool = False,
) -> dict[str, Any]:
    """Assemble the ``POST /v2/campaigns/create`` payload for an email drip campaign."""
    if not title.strip():
        raise ValueError("Campaign title is required.")
    if not email_account_ids:
        raise ValueError("At least one sender email account is required.")
    if not str(list_id).strip():
        raise ValueError("list_id is required.")

    sending_settings: dict[str, Any] = {
        "sending_priority": "first_email",
        "daily_sending_all": daily_sending_all,
        "daily_sending_new_recipients": daily_sending_new_recipients,
        "skip_unverifiable": False,
        "skip_unverified": False,
        "skip_who_replied": skip_who_replied,
        # Recipients missing a per-touch custom field are skipped rather than
        # being sent an email with an unresolved merge variable.
        "skip_recipients_without_variables_data": True,
        "one_click_unsubscribe": True,
    }

    recipients: dict[str, Any] = {"list_id": _coerce_int(list_id)}
    if black_list_id:
        recipients["black_list_id"] = _coerce_int(black_list_id)

    payload: dict[str, Any] = {
        "title": title.strip(),
        "priority": priority,
        "email_accounts": [_coerce_int(account) for account in email_account_ids],
        "linkedin_accounts": [],
        "tracking": {"open": track_opens, "link_click": track_clicks},
        "sending_settings": sending_settings,
        "recipients": recipients,
        "complete_campaign_after_last_step": complete_after_last_step,
        "archive_in_months": archive_in_months,
        "provider_matching": provider_matching,
        "sequence": sequence,
    }
    if schedule_id:
        payload["schedule_id"] = _coerce_int(schedule_id)
    if timezone:
        payload["timezone"] = timezone
    return payload


def build_touch_content(num_touches: int) -> list[dict[str, Any]]:
    """Build the per-touch content templates wired to merge variables.

    Email bodies are sent as plain text so that newlines in the generated content
    are preserved when Snov.io renders the merge variable.
    """
    contents: list[dict[str, Any]] = []
    for touch in range(1, num_touches + 1):
        contents.append({
            "touch": touch,
            "subject": merge_field(f"{SUBJECT_PREFIX}{touch}"),
            "body": merge_field(f"{BODY_PREFIX}{touch}"),
            "plain_text": True,
        })
    return contents


def map_email_step_contents(campaign_response: dict[str, Any], email_refs: list[str]) -> list[dict[str, Any]]:
    """Resolve created email steps to their step and content-slot identifiers.

    Returns one entry per touch: ``{touch, ref, stepId, contentId}``. ``stepId``
    prefers a numeric ``id`` when Snov.io returns one and falls back to the ``_ref``.
    ``contentId`` is the first content slot's id (each email step is created with a
    single slot).
    """
    data = campaign_response.get("data", campaign_response) if isinstance(campaign_response, dict) else {}
    sequence = data.get("sequence", {}) if isinstance(data, dict) else {}
    steps = sequence.get("steps", []) if isinstance(sequence, dict) else []
    by_ref = {str(step.get("_ref")): step for step in steps if isinstance(step, dict)}

    mapped: list[dict[str, Any]] = []
    for index, ref in enumerate(email_refs):
        step = by_ref.get(str(ref))
        if not isinstance(step, dict):
            mapped.append({"touch": index + 1, "ref": ref, "stepId": None, "contentId": None})
            continue
        contents = step.get("content") or []
        content_id = None
        if contents and isinstance(contents[0], dict):
            content_id = contents[0].get("id")
        mapped.append({
            "touch": index + 1,
            "ref": ref,
            "stepId": step.get("id", ref),
            "contentId": content_id,
        })
    return mapped


def _coerce_int(value: Any) -> Any:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return value
