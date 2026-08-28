"""Tests for the Snov.io API client foundation."""

import json
from email.message import Message
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError, URLError

import pytest

from snovio_client import SnovioAPIError, SnovioClient, SnovioConfigError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_missing_credentials_raise_config_error():
    client = SnovioClient(client_id="", client_secret="")

    with pytest.raises(SnovioConfigError):
        client.get_access_token()


@patch("snovio_client.urlopen")
def test_access_token_is_cached(mock_urlopen):
    mock_urlopen.return_value = FakeResponse({"access_token": "token-1", "expires_in": 3600})
    client = SnovioClient(client_id="id", client_secret="secret")

    assert client.get_access_token() == "token-1"
    assert client.get_access_token() == "token-1"
    assert mock_urlopen.call_count == 1


@patch("snovio_client.urlopen")
def test_access_token_uses_shared_cache_callbacks(mock_urlopen):
    saved = {}
    first = SnovioClient(
        client_id="id",
        client_secret="secret",
        token_loader=lambda: saved.get("token"),
        token_saver=lambda token, expires_at: saved.update(token=(token, expires_at)),
    )
    mock_urlopen.return_value = FakeResponse({"access_token": "token-1", "expires_in": 3600})

    assert first.get_access_token() == "token-1"

    second = SnovioClient(
        client_id="id",
        client_secret="secret",
        token_loader=lambda: saved.get("token"),
    )
    assert second.get_access_token() == "token-1"
    assert mock_urlopen.call_count == 1


@patch("snovio_client.time.sleep")
def test_external_rate_reserver_is_used(mock_sleep):
    reservations = iter([1.5, 0.0])
    client = SnovioClient(
        client_id="id",
        client_secret="secret",
        rate_reserver=lambda: next(reservations),
    )

    client._wait_for_rate_limit_slot()

    mock_sleep.assert_called_once_with(1.5)


@patch("snovio_client.urlopen")
def test_balance_uses_bearer_token(mock_urlopen):
    mock_urlopen.side_effect = [
        FakeResponse({"access_token": "token-1", "expires_in": 3600}),
        FakeResponse({"success": True, "data": {"balance": "12.00"}}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret")

    result = client.get_balance()

    balance_request = mock_urlopen.call_args_list[1].args[0]
    assert result["data"]["balance"] == "12.00"
    assert balance_request.get_header("Authorization") == "Bearer token-1"


@patch("snovio_client.urlopen")
def test_http_error_is_sanitized(mock_urlopen):
    mock_urlopen.side_effect = HTTPError(
        url="https://api.snov.io/v1/get-balance",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=BytesIO(b'{"error":"Rate limit exceeded"}'),
    )
    client = SnovioClient(client_id="id", client_secret="secret")
    client._access_token = "token-1"
    client._token_expires_at = 9999999999

    with pytest.raises(SnovioAPIError) as exc:
        client.get_balance()

    assert exc.value.status_code == 429
    assert "Rate limit exceeded" in str(exc.value)


@patch("snovio_client.time.sleep")
@patch("snovio_client.urlopen")
def test_rate_limit_retries_after_server_delay(mock_urlopen, mock_sleep):
    headers = Message()
    headers["Retry-After"] = "2"
    mock_urlopen.side_effect = [
        HTTPError(
            url="https://api.snov.io/v1/get-balance",
            code=429,
            msg="Too Many Requests",
            hdrs=headers,
            fp=BytesIO(b'{"error":"Rate limit exceeded"}'),
        ),
        FakeResponse({"success": True, "data": {"balance": "12.00"}}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret", max_retries=1)
    client._access_token = "token-1"
    client._token_expires_at = 9999999999

    result = client.get_balance()

    assert result["data"]["balance"] == "12.00"
    mock_sleep.assert_called_once_with(2.0)


@patch("snovio_client.random.uniform", return_value=0.0)
@patch("snovio_client.time.sleep")
@patch("snovio_client.urlopen")
def test_transient_network_error_retries_with_backoff(mock_urlopen, mock_sleep, _mock_uniform):
    mock_urlopen.side_effect = [
        URLError("temporary DNS failure"),
        FakeResponse({"success": True, "data": {"balance": "5.00"}}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret", max_retries=1, retry_base_seconds=0.25)
    client._access_token = "token-1"
    client._token_expires_at = 9999999999

    assert client.get_balance()["data"]["balance"] == "5.00"
    mock_sleep.assert_called_once_with(0.25)


def test_email_verification_batch_limit():
    client = SnovioClient(client_id="id", client_secret="secret")

    with pytest.raises(ValueError, match="up to 10"):
        client.start_email_verification([f"person{i}@example.com" for i in range(11)])


@patch("snovio_client.urlopen")
def test_custom_fields_are_flattened_for_prospect_sync(mock_urlopen):
    mock_urlopen.side_effect = [
        FakeResponse({"access_token": "token-1", "expires_in": 3600}),
        FakeResponse({"success": True, "id": "prospect-1", "added": True}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret")

    result = client.add_prospect_to_list(
        "123",
        {"email": "person@example.com", "customFields": {"Subject_Touch1": "Hello"}},
    )

    request = mock_urlopen.call_args_list[1].args[0]
    assert result["added"] is True
    assert b"customFields%5BSubject_Touch1%5D=Hello" in request.data


@patch("snovio_client.urlopen")
def test_create_prospect_list_posts_name(mock_urlopen):
    mock_urlopen.side_effect = [
        FakeResponse({"access_token": "token-1", "expires_in": 3600}),
        FakeResponse([{"success": True, "data": {"id": 1234567}}]),
    ]
    client = SnovioClient(client_id="id", client_secret="secret")

    result = client.create_prospect_list("Cloudware Leads")

    request = mock_urlopen.call_args_list[1].args[0]
    assert result[0]["data"]["id"] == 1234567
    assert request.full_url == "https://api.snov.io/v1/lists"
    assert b"name=Cloudware+Leads" in request.data


def test_create_prospect_list_requires_name():
    client = SnovioClient(client_id="id", client_secret="secret")

    with pytest.raises(ValueError):
        client.create_prospect_list("  ")


@patch("snovio_client.urlopen")
def test_get_sender_accounts_unwraps_data(mock_urlopen):
    mock_urlopen.side_effect = [
        FakeResponse({"access_token": "token-1", "expires_in": 3600}),
        FakeResponse({"data": [{"id": 11, "email_from": "den@snov.io", "valid": True}]}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret")

    accounts = client.get_sender_accounts()

    assert accounts[0]["email_from"] == "den@snov.io"


@patch("snovio_client.urlopen")
def test_create_campaign_posts_json_body(mock_urlopen):
    mock_urlopen.side_effect = [
        FakeResponse({"access_token": "token-1", "expires_in": 3600}),
        FakeResponse({"success": True, "data": {"id": 555, "status": "new"}}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret")

    result = client.create_campaign({"title": "Journey", "recipients": {"list_id": 1}})

    request = mock_urlopen.call_args_list[1].args[0]
    assert result["data"]["id"] == 555
    assert request.full_url == "https://api.snov.io/v2/campaigns/create"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(request.data.decode("utf-8"))["title"] == "Journey"


def test_create_campaign_requires_title():
    client = SnovioClient(client_id="id", client_secret="secret")

    with pytest.raises(ValueError, match="title"):
        client.create_campaign({"recipients": {"list_id": 1}})


@patch("snovio_client.urlopen")
def test_get_profile_by_email_uses_documented_get_contract(mock_urlopen):
    mock_urlopen.side_effect = [
        FakeResponse({"access_token": "token-1", "expires_in": 3600}),
        FakeResponse({"success": True, "data": {"email": "ada@example.com"}}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret")

    client.get_profile_by_email("ada@example.com")

    request = mock_urlopen.call_args_list[1].args[0]
    assert request.get_method() == "GET"
    assert request.full_url == "https://api.snov.io/v1/get-profile-by-email?email=ada%40example.com"


@patch("snovio_client.urlopen")
def test_get_campaign_all_replies_uses_v2_multichannel_endpoint(mock_urlopen):
    mock_urlopen.side_effect = [
        FakeResponse({"access_token": "token-1", "expires_in": 3600}),
        FakeResponse({"success": True, "data": []}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret")

    client.get_campaign_all_replies("555")

    request = mock_urlopen.call_args_list[1].args[0]
    assert request.full_url == "https://api.snov.io/v2/campaigns/555/all-replies"


@patch("snovio_client.urlopen")
def test_create_email_step_content_targets_step_path(mock_urlopen):
    mock_urlopen.side_effect = [
        FakeResponse({"access_token": "token-1", "expires_in": 3600}),
        FakeResponse({"success": True, "data": {"id": 1000}}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret")

    client.create_email_step_content(555, 100, 1000, subject="{{Subject_Touch1}}", body="{{Body_Touch1}}", plain_text=True)

    request = mock_urlopen.call_args_list[1].args[0]
    assert request.full_url == "https://api.snov.io/v2/campaigns/555/steps/100/content/create"
    body = json.loads(request.data.decode("utf-8"))
    assert body["subject"] == "{{Subject_Touch1}}"
    assert body["plain_text"] is True


@patch("snovio_client.urlopen")
def test_change_campaign_state_uses_documented_action(mock_urlopen):
    mock_urlopen.side_effect = [
        FakeResponse({"access_token": "token-1", "expires_in": 3600}),
        FakeResponse({"success": True}),
    ]
    client = SnovioClient(client_id="id", client_secret="secret")

    client.change_campaign_state(555, "launch")

    request = mock_urlopen.call_args_list[1].args[0]
    assert json.loads(request.data.decode("utf-8")) == {"action": "launch"}


@pytest.mark.parametrize("legacy_action", ["start", "archived"])
def test_change_campaign_state_rejects_legacy_actions(legacy_action):
    client = SnovioClient(client_id="id", client_secret="secret")

    with pytest.raises(ValueError):
        client.change_campaign_state(555, legacy_action)