"""Tests for Snov.io workflow helpers."""

import pandas as pd

from snovio_workflows import (
    assess_custom_field_readiness,
    build_job_rows,
    build_prospect_payload,
    classify_verification,
    estimate_usage,
    infer_columns,
    is_sending_campaign,
    summarize_report,
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


def test_custom_field_readiness_splits_present_and_missing():
    readiness = assess_custom_field_readiness(
        [{"label": "Subject_Touch1"}, {"label": "Body_Touch1"}],
        ["Subject_Touch1", "Body_Touch1", "Subject_Touch2", "Body_Touch2"],
    )

    assert readiness["ready"] is False
    assert readiness["present"] == ["Subject_Touch1", "Body_Touch1"]
    assert readiness["missing"] == ["Subject_Touch2", "Body_Touch2"]


def test_custom_field_readiness_ready_when_all_present():
    readiness = assess_custom_field_readiness(
        [{"label": "Subject_Touch1"}, {"label": "Body_Touch1"}],
        ["Subject_Touch1", "Body_Touch1"],
    )

    assert readiness["ready"] is True
    assert readiness["missing"] == []


def test_summarize_report_buckets_each_row_once():
    rows = [
        {"eligible": True, "blockedReason": None, "status": "added"},
        {"eligible": True, "blockedReason": None, "status": "updated"},
        {"eligible": False, "blockedReason": "duplicate_in_target_list", "status": "skipped"},
        {"eligible": False, "blockedReason": "verification_blocked", "status": "skipped"},
        {"eligible": True, "blockedReason": None, "status": "failed"},
    ]

    summary = summarize_report(rows)

    assert summary["total"] == 5
    assert summary["added"] == 1
    assert summary["updated"] == 1
    assert summary["duplicates"] == 1
    assert summary["blocked"] == 1
    assert summary["failed"] == 1
    # Duplicates and blocked rows must not also be counted as skipped.
    assert summary["skipped"] == 0
    # Every row lands in exactly one outcome bucket.
    assert summary["added"] + summary["updated"] + summary["duplicates"] + summary["blocked"] + summary["failed"] + summary["skipped"] == summary["total"]