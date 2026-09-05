import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from unittest.mock import MagicMock, patch

import onboarding
import pytest
import tests.test_function_app as fixture

fa = fixture.fa


class Entity(dict):
    def __init__(self, row, revision):
        super().__init__(row)
        self.metadata = {"etag": str(revision)}


class Table:
    def __init__(self):
        self.rows = {}
        self.revision = 0
        self.lock = Lock()

    def get_entity(self, owner, key):
        with self.lock:
            if (owner, key) not in self.rows:
                raise fa.data_store.ResourceNotFoundError()
            return Entity(deepcopy(self.rows[owner, key]), self.revision)

    def create_entity(self, entity):
        with self.lock:
            key = (entity["PartitionKey"], entity["RowKey"])
            if key in self.rows:
                raise fa.data_store.ResourceExistsError()
            self.rows[key] = deepcopy(entity)
            self.revision += 1

    def update_entity(self, entity, **options):
        with self.lock:
            if options["etag"] != str(self.revision):
                raise fa.data_store.ResourceModifiedError()
            self.rows[entity["PartitionKey"], entity["RowKey"]] = deepcopy(entity)
            self.revision += 1


def test_concurrent_invitation_claim_has_one_winner():
    table = Table()
    with patch.object(fa.data_store, "_table", return_value=table):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(lambda index: fa.data_store.change_onboarding("owner", "user", {
                "action": "invite", "version": onboarding.VERSION, "requestId": f"tab-{index:08d}"
            }), range(20)))
        assert sum(result[1]["granted"] for result in results) == 1
        assert fa.data_store.get_onboarding("owner")["invitations"] == 1
        assert fa.data_store.get_onboarding("other")["invitations"] == 0


def test_state_get_is_read_only_and_owner_scoped():
    request = MagicMock(method="GET")
    with patch.object(fa, "_require_user", return_value=({"oid": "owner", "role": "user"}, None)), \
            patch.object(fa.data_store, "get_onboarding", return_value=onboarding.initial_state()) as get, \
            patch.object(fa.data_store, "change_onboarding") as change:
        response = asyncio.run(fa.onboarding_state(request))
    assert response.status_code == 200
    get.assert_called_once_with("owner")
    change.assert_not_called()
    state = json.loads(response.body)["state"]
    assert "runId" not in state and "claimId" not in state
    assert "admin-template" not in state["availableTours"]


def test_anonymous_request_is_rejected_before_storage():
    with patch.object(fa, "_require_user", return_value=(None, fa._json_response({}, 401))), \
            patch.object(fa.data_store, "get_onboarding") as get:
        response = asyncio.run(fa.onboarding_state(MagicMock()))
    assert response.status_code == 401
    get.assert_not_called()


def test_client_owner_and_role_are_not_used():
    request = MagicMock(method="POST")
    payload = {"action": "preferences", "version": onboarding.VERSION, "optOut": True, "oid": "victim", "role": "admin"}
    request.get_body.return_value = json.dumps(payload).encode()
    request.get_json.return_value = payload
    with patch.object(fa, "_require_user", return_value=({"oid": "actual-owner", "role": "user"}, None)), \
            patch.object(fa.data_store, "change_onboarding", return_value=(onboarding.initial_state(), {})) as change:
        response = asyncio.run(fa.onboarding_state(request))
    assert response.status_code == 200
    assert change.call_args.args[:2] == ("actual-owner", "user")


@pytest.mark.parametrize("body,status", [(b"[]", 400), (b"null", 400), (b"invalid", 400), (b"\xff", 400), (b" " * 4097, 413)])
def test_bad_payload_is_rejected_without_storage(body, status):
    request = MagicMock(method="POST")
    request.get_body.return_value = body
    with patch.object(fa, "_require_user", return_value=({"oid": "owner", "role": "user"}, None)), \
            patch.object(fa.data_store, "change_onboarding") as change:
        response = asyncio.run(fa.onboarding_state(request))
    assert response.status_code == status
    change.assert_not_called()


def test_invitation_flag_blocks_claims():
    request = MagicMock(method="POST")
    request.get_body.return_value = json.dumps({"action": "invite", "version": onboarding.VERSION, "requestId": "request-one"}).encode()
    with patch.object(fa, "_require_user", return_value=({"oid": "owner", "role": "user"}, None)), \
            patch.dict(fa.os.environ, {"ONBOARDING_AUTO_INVITES": "false"}), \
            patch.object(fa.data_store, "change_onboarding") as change:
        response = asyncio.run(fa.onboarding_state(request))
    assert not json.loads(response.body)["granted"]
    change.assert_not_called()


def test_content_version_change_does_not_reset_account_preferences():
    table = Table()
    with patch.object(fa.data_store, "_table", return_value=table):
        fa.data_store.change_onboarding("owner", "user", {"action": "preferences", "version": onboarding.VERSION, "optOut": True})
        with patch.object(onboarding, "VERSION", "future-content"):
            assert fa.data_store.get_onboarding("owner")["optOut"]
    assert list(table.rows) == [("owner", onboarding.ACCOUNT_KEY)]