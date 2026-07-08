"""Tests for the Snov.io campaign ("customer journey") builders."""

from snovio_campaigns import (
    build_campaign_payload,
    build_campaign_sequence,
    build_touch_content,
    detect_touch_count,
    map_email_step_contents,
    merge_field,
    touch_field_labels,
)


def test_merge_field_and_touch_labels():
    assert merge_field("Body_Touch2") == "{{Body_Touch2}}"
    assert touch_field_labels(2) == [
        "Subject_Touch1",
        "Body_Touch1",
        "Subject_Touch2",
        "Body_Touch2",
    ]


def test_detect_touch_count_uses_highest_contiguous_pair():
    headers = ["Email", "Subject_Touch1", "Body_Touch1", "Subject_Touch2", "Body_Touch2"]
    assert detect_touch_count(headers) == 2


def test_detect_touch_count_requires_matching_subject_and_body():
    headers = ["Subject_Touch1", "Body_Touch1", "Subject_Touch2"]  # touch 2 missing a body
    assert detect_touch_count(headers) == 1


def test_build_campaign_sequence_alternates_email_and_delay():
    sequence, email_refs = build_campaign_sequence(3, delay_days=2, ref_seed=1000)

    assert len(email_refs) == 3
    types = [step["type"] for step in sequence["steps"]]
    assert types == ["email", "delay", "email", "delay", "email", "goal"]
    assert sequence["entry"] == email_refs[0]
    # Each email links to the following step; the last email links to the goal.
    assert sequence["steps"][0]["next"] == sequence["steps"][1]["_ref"]
    assert sequence["steps"][-2]["next"] == sequence["steps"][-1]["_ref"]
    assert sequence["steps"][-1]["type"] == "goal"


def test_build_campaign_sequence_single_touch_has_no_delay():
    sequence, email_refs = build_campaign_sequence(1, delay_days=5, ref_seed=10)
    types = [step["type"] for step in sequence["steps"]]
    assert types == ["email", "goal"]
    assert len(email_refs) == 1


def test_build_campaign_payload_requires_sender_and_list():
    sequence, _ = build_campaign_sequence(1, ref_seed=1)
    payload = build_campaign_payload("My journey", [42], "123", sequence)

    assert payload["title"] == "My journey"
    assert payload["email_accounts"] == [42]
    assert payload["recipients"]["list_id"] == 123
    assert payload["sending_settings"]["skip_recipients_without_variables_data"] is True
    assert payload["sequence"] is sequence


def test_build_touch_content_wires_merge_variables():
    contents = build_touch_content(2)
    assert contents[0] == {
        "touch": 1,
        "subject": "{{Subject_Touch1}}",
        "body": "{{Body_Touch1}}",
        "plain_text": True,
    }
    assert contents[1]["subject"] == "{{Subject_Touch2}}"


def test_map_email_step_contents_resolves_step_and_content_ids():
    response = {
        "data": {
            "id": 9,
            "sequence": {
                "steps": [
                    {"_ref": "100", "type": "email", "content": [{"id": 1000}]},
                    {"_ref": "goal", "type": "goal"},
                ]
            },
        }
    }
    mapped = map_email_step_contents(response, ["100"])
    assert mapped == [{"touch": 1, "ref": "100", "stepId": "100", "contentId": 1000}]


def test_map_email_step_contents_handles_missing_step():
    mapped = map_email_step_contents({"data": {"sequence": {"steps": []}}}, ["100"])
    assert mapped[0]["stepId"] is None
    assert mapped[0]["contentId"] is None
