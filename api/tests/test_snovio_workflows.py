"""Tests for Snov.io workflow helpers."""

import pandas as pd

from snovio_workflows import (
    build_job_rows,
    build_prospect_payload,
    classify_verification,
    estimate_usage,
    infer_columns,
    is_sending_campaign,
)


def test_infer_columns_and_build_rows():
    df = pd.DataFrame([
        {
            "Work Email": "ada@example.com",
            "First Name": "Ada",
            "Last Name": "Lovelace",
            "Company Name": "Contoso",
            "LinkedIn URL": "https://linkedin.com/in/ada",
        }
    ])

    rows, columns = build_job_rows(df)

    assert columns["email"] == "Work Email"
    assert rows[0]["email"] == "ada@example.com"
    assert rows[0]["companyName"] == "Contoso"


def test_verification_blocks_unsafe_rows_by_default():
    result = classify_verification({
        "email": "test@example.com",
        "result": {
            "smtp_status": "unknown",
            "is_valid_format": True,
            "is_disposable": False,
            "is_webmail": False,
            "is_gibberish": True,
            "unknown_status_reason": "banned",
        },
    })

    assert result["eligible"] is False
    assert result["blockedReason"] == "gibberish"


def test_verification_allows_safe_unknown_when_policy_enabled():
    result = classify_verification({
        "email": "test@example.com",
        "result": {
            "smtp_status": "unknown",
            "is_valid_format": True,
            "is_disposable": False,
            "is_webmail": False,
            "is_gibberish": False,
            "unknown_status_reason": "catchall",
        },
    }, allow_unknown=True)

    assert result["eligible"] is True


def test_build_prospect_payload_preserves_matching_generated_custom_fields():
    df = pd.DataFrame([
        {
            "Email": "ada@example.com",
            "First Name": "Ada",
            "Last Name": "Lovelace",
            "Company": "Contoso",
            "Subject_Touch1": "Hello",
            "Body_Touch1": "Body",
        }
    ])
    columns = infer_columns(df)

    payload = build_prospect_payload(df.iloc[0], columns, "123", [{"label": "Subject_Touch1"}])

    assert payload["firstName"] == "Ada"
    assert payload["customFields"] == {"Subject_Touch1": "Hello"}


def test_estimate_usage_for_full_workflow():
    estimate = estimate_usage(25, "full")

    assert estimate["estimatedCredits"] == 50
    assert estimate["estimatedRequests"] == 31


def test_active_campaign_detection():
    assert is_sending_campaign({"status": "Active"}) is True
    assert is_sending_campaign({"status": "Paused"}) is False