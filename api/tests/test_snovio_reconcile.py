from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from snovio_publish import new_state, reconcile


def uncertain(stage):
    state = new_state({"listName": "Unique-list", "listId": "123", "campaignTitle": "Draft"}, "account")
    state.update(status="needs_review", inFlight=stage)
    return state


def test_adopts_exact_list_without_creating_another():
    state = uncertain("create_list")
    client = MagicMock()
    client.get_user_lists.return_value = [{"id": 456, "name": "Unique-list"}]
    reconcile(state, client, b"")
    assert state["payload"]["listId"] == "456"
    assert state["status"] == "queued"
    client.create_prospect_list.assert_not_called()


@pytest.mark.parametrize("lists", [[], [{"id": 1, "name": "Other"}], [{"id": 1, "name": "Unique-list"}, {"id": 2, "name": "Unique-list"}]])
def test_ambiguous_list_stays_blocked(lists):
    state = uncertain("create_list")
    original = deepcopy(state)
    client = MagicMock()
    client.get_user_lists.return_value = lists
    with pytest.raises(ValueError):
        reconcile(state, client, b"")
    assert state == original


def test_confirmed_prospect_retries_update_without_recreating_list():
    state = uncertain("prospect:0")
    state["rows"] = {"0": {"status": "failed", "uncertain": True}}
    client = MagicMock()
    client.get_prospects_by_email.return_value = {"data": [{"lists": [{"id": 123}]}]}
    reconcile(state, client, b"Email\nqa@example.com\n")
    assert state["status"] == "queued"
    assert state["payload"]["updateExisting"] is True
    assert not state["rows"]
    client.add_prospect_to_list.assert_not_called()


def test_unconfirmed_prospect_is_not_replayed():
    state = uncertain("prospect:0")
    client = MagicMock()
    client.get_prospects_by_email.return_value = {"data": []}
    with pytest.raises(ValueError, match="No write was replayed"):
        reconcile(state, client, b"Email\nqa@example.com\n")
    assert state["status"] == "needs_review"


def test_reconcile_draft_preserves_campaign_id_and_steps():
    state = uncertain("create_campaign")
    state.update(emailRefs=["first"], touches=1)
    client = MagicMock()
    client.get_user_campaigns.return_value = [{"id": 77, "campaign": "Draft"}]
    client.get_campaign.return_value = {"data": {"id": 77, "list_id": 123, "status": "new"}}
    with patch("snovio_publish.map_email_step_contents", return_value=[{"stepId": 1, "contentId": 2}]):
        reconcile(state, client, b"")
    assert state["campaignId"] == 77
    assert state["status"] == "queued"
    client.create_campaign.assert_not_called()


def test_confirmed_absent_recipient_can_only_retry_without_duplicates():
    state = uncertain("prospect:0")
    client = MagicMock()
    client.get_prospects_by_email.return_value = {"data": []}
    reconcile(state, client, b"Email\nqa@example.com\n", confirm_missing=True)
    assert state["status"] == "queued"
    assert state["payload"]["_noDuplicateRows"] == [0]
    client.add_prospect_to_list.assert_not_called()


def test_confirmation_cannot_override_another_list_match():
    state = uncertain("prospect:0")
    client = MagicMock()
    client.get_prospects_by_email.return_value = {"data": [{"lists": [{"id": 999}]}]}
    with pytest.raises(ValueError, match="cannot be confirmed uniquely"):
        reconcile(state, client, b"Email\nqa@example.com\n", confirm_missing=True)


def test_reconcile_never_adopts_an_active_campaign():
    state = uncertain("create_campaign")
    state.update(emailRefs=["first"], touches=1)
    client = MagicMock()
    client.get_user_campaigns.return_value = [{"id": 77, "campaign": "Draft"}]
    client.get_campaign.return_value = {"data": {"id": 77, "list_id": 123, "status": "active"}}
    with pytest.raises(ValueError, match="inactive draft"):
        reconcile(state, client, b"")