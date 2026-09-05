import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from template_builder import normalize_brief, preview_brief


def test_preview_returns_validated_samples_without_publishing():
    client = MagicMock()
    emails = [{"subject": "Hi", "body": "Hello Alex"}] * 2
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
        finish_reason="stop", message=SimpleNamespace(content=json.dumps({"emails": emails}), refusal=None)
    )])
    result = preview_brief(client, "test", {"audience": "IT", "offer": "License review", "facts": "Review available", "cta": "Book a call", "numEmails": 2})
    assert result["sampleEmails"] == emails
    assert "Never invent prices" in result["systemPrompt"]
    assert result["brief"]["numEmails"] == 2
    assert result["deployment"] == "test"
    assert result["model"] == "test"
    assert result["usage"] is None


@pytest.mark.parametrize("payload", [{}, {"numEmails": 13}, {"numEmails": "bad"}])
def test_brief_requires_valid_inputs(payload):
    with pytest.raises(ValueError):
        normalize_brief(payload)