import json

import pytest

from prompt_templates import _parse_emails, email_output_schema, get_template, resolve_snapshot, template_snapshot


def test_snapshot_keeps_original_prompt_and_count():
    template = dict(get_template("leads"))
    snapshot = template_snapshot(template)
    template["system_prompt"] = "changed later"
    template["num_emails"] = 12
    resolved = resolve_snapshot(snapshot)
    assert resolved["system_prompt"] != "changed later"
    assert resolved["num_emails"] == snapshot["snapshot"]["numEmails"]


def test_schema_matches_parser_count():
    schema = email_output_schema(4)["json_schema"]["schema"]
    assert schema["properties"]["emails"]["minItems"] == 4
    assert schema["properties"]["emails"]["maxItems"] == 4
    emails = [{"subject": "Hello", "body": "Body"}] * 4
    assert _parse_emails(json.dumps({"emails": emails}), 4) == emails


@pytest.mark.parametrize("email", [{"subject": "", "body": "body"}, {"subject": None, "body": "body"}, "not an object"])
def test_parser_rejects_unusable_email_fields(email):
    with pytest.raises(ValueError):
        _parse_emails(json.dumps({"emails": [email]}), 1)