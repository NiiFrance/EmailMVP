"""Snov.io API client helpers.

The client intentionally keeps the first integration layer small: OAuth token
caching, request throttling, and wrappers for the API surfaces needed by the
first rollout milestones.
"""

from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass
from threading import Lock
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SnovioConfigError(RuntimeError):
    """Raised when Snov.io credentials are not configured."""


class SnovioAPIError(RuntimeError):
    """Raised when Snov.io returns an error or an invalid response."""

    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class SnovioClient:
    client_id: str
    client_secret: str
    base_url: str = "https://api.snov.io"
    requests_per_minute: int = 60
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        self._access_token: str | None = None
        self._token_expires_at = 0.0
        self._request_times: deque[float] = deque()
        self._lock = Lock()

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret)

    def get_access_token(self) -> str:
        """Return a cached access token or request a new one."""
        if not self.configured:
            raise SnovioConfigError("Snov.io credentials are not configured.")

        now = time.time()
        if self._access_token and now < self._token_expires_at - 60:
            return self._access_token

        payload = self._request(
            "POST",
            "/v1/oauth/access_token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            authenticated=False,
        )

        token = payload.get("access_token")
        if not token:
            raise SnovioAPIError("Snov.io token response did not include an access token.")

        expires_in = int(payload.get("expires_in", 3600))
        self._access_token = str(token)
        self._token_expires_at = now + expires_in
        return self._access_token

    def get_balance(self) -> dict[str, Any]:
        return self._request("GET", "/v1/get-balance")

    def get_user_lists(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/v1/get-user-lists")
        return response if isinstance(response, list) else []

    def create_prospect_list(self, name: str) -> Any:
        if not name.strip():
            raise ValueError("name is required.")
        return self._request("POST", "/v1/lists", data={"name": name.strip()})

    def get_user_campaigns(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/v1/get-user-campaigns")
        return response if isinstance(response, list) else []

    def start_email_verification(self, emails: list[str], webhook_url: str | None = None) -> dict[str, Any]:
        if not emails:
            raise ValueError("At least one email is required for verification.")
        if len(emails) > 10:
            raise ValueError("Snov.io email verification accepts up to 10 emails per request.")

        data: dict[str, Any] = {"emails[]": emails}
        if webhook_url:
            data["webhook_url"] = webhook_url
        return self._request("POST", "/v2/email-verification/start", data=data)

    def get_email_verification_result(self, task_hash: str) -> dict[str, Any]:
        if not task_hash:
            raise ValueError("task_hash is required.")
        return self._request("GET", "/v2/email-verification/result", params={"task_hash": task_hash})

    def add_prospect_to_list(self, list_id: str, prospect: dict[str, Any]) -> dict[str, Any]:
        if not list_id:
            raise ValueError("list_id is required.")
        social_links = prospect.get("socialLinks") if isinstance(prospect.get("socialLinks"), dict) else {}
        linkedin_url = prospect.get("socialLinks[linkedIn]") or social_links.get("linkedIn")
        if not prospect.get("email") and not linkedin_url:
            raise ValueError("A prospect email or LinkedIn URL is required.")

        data = {
            **prospect,
            "listId": list_id,
            "updateContact": prospect.get("updateContact", True),
            "createDuplicates": prospect.get("createDuplicates", False),
        }
        return self._request("POST", "/v1/add-prospect-to-list", data=data)

    def get_custom_fields(self) -> list[dict[str, Any]]:
        response = self._request("GET", "/v1/prospect-custom-fields")
        return response if isinstance(response, list) else []

    def get_prospects_by_email(self, email: str) -> dict[str, Any]:
        if not email:
            raise ValueError("email is required.")
        return self._request("POST", "/v1/get-prospects-by-email", data={"email": email})

    def add_do_not_email(self, list_id: str, items: list[str]) -> Any:
        if not list_id:
            raise ValueError("list_id is required.")
        if not items:
            raise ValueError("At least one email or domain is required.")
        return self._request("POST", "/v1/do-not-email-list", data={"listId": list_id, "items[]": items})

    def change_recipient_status(self, email: str, campaign_id: str, status: str) -> dict[str, Any]:
        if status not in {"Active", "Paused", "Unsubscribed"}:
            raise ValueError("status must be Active, Paused, or Unsubscribed.")
        return self._request(
            "POST",
            "/v1/change-recipient-status",
            data={"email": email, "campaign_id": campaign_id, "status": status},
        )

    def get_campaign_analytics(self, filters: dict[str, Any]) -> dict[str, Any]:
        return self._request("GET", "/v2/statistics/campaign-analytics", params=filters)

    def get_campaign_progress(self, campaign_id: str) -> dict[str, Any]:
        if not campaign_id:
            raise ValueError("campaign_id is required.")
        return self._request("GET", f"/v2/campaigns/{campaign_id}/progress")

    def get_campaign_activity(self, activity: str, campaign_id: str, offset: int | None = None) -> Any:
        paths = {
            "sent": "/v1/emails-sent",
            "opened": "/v1/get-emails-opened",
            "clicked": "/v1/get-emails-clicked",
            "replies": "/v1/get-emails-replies",
            "finished": "/v1/prospect-finished",
        }
        if activity not in paths:
            raise ValueError("Unsupported campaign activity.")
        params: dict[str, Any] = {"campaignId": campaign_id}
        if offset is not None:
            params["offset"] = offset
        return self._request("GET", paths[activity], params=params)

    def list_webhooks(self) -> dict[str, Any]:
        return self._request("GET", "/v2/webhooks")

    def create_webhook(self, event_object: str, event_action: str, endpoint_url: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/v2/webhooks",
            json_body={"event_object": event_object, "event_action": event_action, "endpoint_url": endpoint_url},
        )

    def update_webhook(self, webhook_id: str, status: str) -> dict[str, Any]:
        return self._request("PUT", f"/v2/webhooks/{webhook_id}", json_body={"status": status})

    def delete_webhook(self, webhook_id: str) -> dict[str, Any]:
        return self._request("DELETE", f"/v2/webhooks/{webhook_id}")

    def start_company_domain_by_name(self, names: list[str], webhook_url: str | None = None) -> dict[str, Any]:
        if not names or len(names) > 10:
            raise ValueError("Provide 1 to 10 company names.")
        data: dict[str, Any] = {"names[]": names}
        if webhook_url:
            data["webhook_url"] = webhook_url
        return self._request("POST", "/v2/company-domain-by-name/start", data=data)

    def get_company_domain_by_name_result(self, task_hash: str) -> dict[str, Any]:
        return self._request("GET", "/v2/company-domain-by-name/result", params={"task_hash": task_hash})

    def start_emails_by_name_domain(self, rows: list[dict[str, str]], webhook_url: str | None = None) -> dict[str, Any]:
        if not rows or len(rows) > 10:
            raise ValueError("Provide 1 to 10 name/domain rows.")
        payload: dict[str, Any] = {"rows": rows}
        if webhook_url:
            payload["webhook_url"] = webhook_url
        return self._request("POST", "/v2/emails-by-domain-by-name/start", json_body=payload)

    def get_emails_by_name_domain_result(self, task_hash: str) -> dict[str, Any]:
        return self._request("GET", "/v2/emails-by-domain-by-name/result", params={"task_hash": task_hash})

    def start_linkedin_profiles_by_urls(self, urls: list[str], webhook_url: str | None = None) -> dict[str, Any]:
        if not urls or len(urls) > 10:
            raise ValueError("Provide 1 to 10 LinkedIn URLs.")
        data: dict[str, Any] = {"urls[]": urls}
        if webhook_url:
            data["webhook_url"] = webhook_url
        return self._request("POST", "/v2/li-profiles-by-urls/start", data=data)

    def get_linkedin_profiles_by_urls_result(self, task_hash: str) -> dict[str, Any]:
        return self._request("GET", "/v2/li-profiles-by-urls/result", params={"task_hash": task_hash})

    def get_profile_by_email(self, email: str) -> dict[str, Any]:
        return self._request("POST", "/v1/get-profile-by-email", data={"email": email})

    def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        authenticated: bool = True,
    ) -> Any:
        if authenticated:
            token = self.get_access_token()
        else:
            token = None

        self._wait_for_rate_limit_slot()

        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params, doseq=True)}"

        body = None
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif data is not None:
            body = urlencode(self._flatten_form_data(data), doseq=True).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"

        request = Request(url, data=body, headers=headers, method=method.upper())

        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return self._decode_response(response.read())
        except HTTPError as error:
            raise SnovioAPIError(self._error_message(error.read()), status_code=error.code) from error
        except URLError as error:
            raise SnovioAPIError(f"Snov.io request failed: {error.reason}") from error

    def _wait_for_rate_limit_slot(self) -> None:
        if self.requests_per_minute <= 0:
            return

        with self._lock:
            now = time.monotonic()
            while self._request_times and now - self._request_times[0] >= 60:
                self._request_times.popleft()

            if len(self._request_times) >= self.requests_per_minute:
                sleep_for = 60 - (now - self._request_times[0])
                if sleep_for > 0:
                    time.sleep(sleep_for)
                now = time.monotonic()
                while self._request_times and now - self._request_times[0] >= 60:
                    self._request_times.popleft()

            self._request_times.append(time.monotonic())

    @staticmethod
    def _flatten_form_data(data: dict[str, Any]) -> dict[str, Any]:
        flattened: dict[str, Any] = {}
        for key, value in data.items():
            if isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    flattened[f"{key}[{nested_key}]"] = nested_value
            else:
                flattened[key] = value
        return flattened

    @staticmethod
    def _decode_response(body: bytes) -> Any:
        if not body:
            return {}
        try:
            return json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise SnovioAPIError("Snov.io returned an invalid JSON response.") from error

    @staticmethod
    def _error_message(body: bytes) -> str:
        if not body:
            return "Snov.io request failed."
        try:
            payload = json.loads(body.decode("utf-8"))
            message = payload.get("error") or payload.get("message") or payload.get("error_description")
            if message:
                return f"Snov.io request failed: {message}"
        except Exception:
            pass
        return "Snov.io request failed."