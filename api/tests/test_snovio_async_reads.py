import asyncio
from threading import Event
from unittest.mock import MagicMock, patch

import pytest

import tests.test_function_app as fixture

fa = fixture.fa


@pytest.mark.parametrize("handler,worker", [
    (fa.get_snovio_options, "_get_snovio_options"),
    (fa.get_snovio_preflight, "_get_snovio_preflight"),
    (fa.get_snovio_balance, "_get_snovio_balance"),
    (fa.create_snovio_session, "_create_snovio_session"),
])
def test_throttled_read_does_not_block_event_loop(handler, worker):
    released = Event()
    started = Event()

    def blocking(request):
        started.set()
        assert released.wait(2), "The async event loop was blocked by a REST call"
        return "done"

    async def exercise():
        task = asyncio.create_task(handler(MagicMock()))
        assert await asyncio.to_thread(started.wait, 2)
        released.set()
        assert await task == "done"

    with patch.object(fa, worker, side_effect=blocking):
        asyncio.run(exercise())


def test_preflight_checks_ownership_before_reading_csv():
    request = MagicMock(params={"jobId": "another-job"})
    with patch.object(fa, "_require_allowed_domain", return_value=None), \
            patch.object(fa, "_query_params", return_value={"jobId": "another-job"}), \
            patch.object(fa, "_require_job_owner", return_value=(None, fa._json_response({"error": "Not found"}, 404))), \
            patch.object(fa, "_download_job_csv") as download:
        response = asyncio.run(fa.get_snovio_preflight(request))
    assert response.status_code == 404
    download.assert_not_called()


def test_connection_rate_limit_does_not_claim_credentials_are_wrong():
    request = MagicMock()
    request.get_json.return_value = {"clientId": "synthetic", "clientSecret": "synthetic"}
    probe = MagicMock()
    probe.get_access_token.side_effect = fa.SnovioAPIError("Rate limited", status_code=429)
    with patch.object(fa, "_require_allowed_domain", return_value=None), \
            patch.object(fa, "_build_snovio_client", return_value=probe) as build:
        response = asyncio.run(fa.create_snovio_session(request))
    assert response.status_code == 429
    build.assert_called_once_with("synthetic", "synthetic")