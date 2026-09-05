import json
import uuid

import pytest

import generation_queue as queue


def test_admission_is_idempotent_and_limits_each_owner():
    state, result = queue.admit(None, "job-a", "owner-a", "config", 0)
    assert result["created"]
    repeat, result = queue.admit(state, "job-a", "owner-a", "config", 1)
    assert repeat == state and not result["created"]
    with pytest.raises(queue.Busy):
        queue.admit(state, "job-b", "owner-a", "config", 1)
    with pytest.raises(queue.Busy):
        queue.admit(state, "job-a", "owner-b", "config", 1)
    with pytest.raises(queue.Busy):
        queue.admit(state, "job-a", "owner-a", "changed", 1)


def test_100_accounts_fit_storage_and_101st_is_rejected():
    state = None
    for index in range(100):
        state, _ = queue.admit(state, str(uuid.uuid4()), str(uuid.uuid4()), "f" * 64, 1788580256.123)
    assert len(json.dumps(state).encode("utf-16-le")) < 60000
    with pytest.raises(queue.Busy):
        queue.admit(state, "extra", "extra", "config", 0)


def test_waiting_accounts_take_turns_and_slow_accounts_do_not_block():
    state, _ = queue.admit(None, "first", "owner1", "config", 0)
    state, _ = queue.admit(state, "second", "owner2", "config", 0)
    state, _ = queue.admit(state, "offline", "owner3", "config", 0)
    state, first = queue.reserve(state, "first", 3000, 0)
    assert first["granted"]
    state, second = queue.reserve(state, "second", 3000, 0)
    assert not second["granted"] and second["retryAfter"] == 3
    state, first = queue.reserve(state, "first", 3000, 1)
    assert not first["granted"]
    state, second = queue.reserve(state, "second", 3000, 1)
    assert second["granted"]
    state, first = queue.reserve(state, "first", 3000, 2)
    assert first["granted"]


def test_long_provider_retry_after_cools_down_shared_deployment():
    state, _ = queue.admit(None, "first", "owner1", "config", 0)
    state, _ = queue.admit(state, "second", "owner2", "config", 0)
    state = queue.defer(state, "first", 0, 3600)
    state, first = queue.reserve(state, "first", 3000, 10)
    assert not first["granted"] and first["retryAfter"] == 3590
    state, second = queue.reserve(state, "second", 3000, 10)
    assert not second["granted"] and second["retryAfter"] == 3590


def test_dispatch_lease_and_release_are_idempotent():
    state, _ = queue.admit(None, "first", "owner1", "config", 0)
    state, granted = queue.claim_dispatch(state, "first", 0)
    assert granted
    state, granted = queue.claim_dispatch(state, "first", 1)
    assert not granted
    state, granted = queue.claim_dispatch(state, "first", 121)
    assert granted
    state = queue.release(state, "first")
    assert queue.release(state, "first") == state


def test_quota_allocations_leave_interactive_headroom():
    assert 3 * queue.REQUESTS_PER_MINUTE < 667
    assert 3 * queue.TOKENS_PER_MINUTE < 667000


def test_expired_waiter_does_not_block_recoverable_work():
    state, _ = queue.admit(None, "first", "owner1", "config", 0)
    state, _ = queue.admit(state, "second", "owner2", "config", 0)
    state, _ = queue.reserve(state, "second", 3000, 0)
    state, _ = queue.reserve(state, "first", 3000, 0)
    state, result = queue.reserve(state, "second", 3000, 121)
    assert result["granted"]


def test_persisted_concurrent_owner_admission_has_one_winner():
    from concurrent.futures import ThreadPoolExecutor
    from unittest.mock import patch
    from tests.test_onboarding_api import Table, fa
    table = Table()

    def admit(index):
        try:
            return fa.data_store.change_generation_queue("admit", f"job-{index}", owner="same-owner", config_hash="config")
        except queue.Busy:
            return {"accepted": False}

    with patch.object(fa.data_store, "_table", return_value=table):
        with ThreadPoolExecutor(max_workers=10) as pool:
            results = list(pool.map(admit, range(20)))
        assert sum(bool(result.get("accepted")) for result in results) == 1
        assert len(fa.data_store.get_generation_queue()["jobs"]) == 1


def test_rolling_token_ceiling_prevents_large_request_bursts():
    state, _ = queue.admit(None, "job", "owner", "config", 0)
    state, result = queue.reserve(state, "job", 100000, 0)
    assert result["granted"]
    state, result = queue.reserve(state, "job", 100000, 34)
    assert not result["granted"] and result["retryAfter"] == 26
    state, result = queue.reserve(state, "job", 100000, 60)
    assert result["granted"]


def test_full_queue_with_real_instance_ids_and_waiters_fits_each_property():
    state = None
    ids = []
    now = 1788580256.123456
    for index in range(100):
        job = str(uuid.uuid4()) + "-v2-" + "f" * 12
        ids.append(job)
        state, _ = queue.admit(state, job, str(uuid.uuid4()), "f" * 64, now)
    for job in ids:
        state, _ = queue.reserve(state, job, 32768, now)
        state, _ = queue.claim_dispatch(state, job, now)
    state["sequence"] = 10000000
    from unittest.mock import patch
    from tests.test_onboarding_api import Table, fa
    table = Table()
    table.create_entity({"PartitionKey": "queue", "RowKey": "v2", "state": json.dumps({key: value for key, value in state.items() if key not in {"jobs", "reservations"}}),
                         "jobs": json.dumps(state["jobs"]), "reservations": json.dumps(state["reservations"])})
    with patch.object(fa.data_store, "_table", return_value=table):
        fa.data_store.change_generation_queue("defer", ids[0], retry_after=60)
        assert len(fa.data_store.get_generation_queue()["jobs"]) == 100
    entity = table.rows["queue", "v2"]
    assert max(len(entity[key].encode("utf-16-le")) for key in ["jobs0", "jobs1", "reservations", "state"]) < 60000


def test_waiters_use_queue_aware_backoff():
    import heapq
    state = None
    events = []
    for owner in range(100):
        state, _ = queue.admit(state, str(owner), str(owner), "hash", 0)
        heapq.heappush(events, (0, owner))
    attempts = 0
    while events:
        now, owner = heapq.heappop(events)
        attempts += 1
        state, result = queue.reserve(state, str(owner), 5000, now)
        if result["granted"]:
            state = queue.release(state, str(owner))
        else:
            heapq.heappush(events, (now + result["retryAfter"], owner))
    assert attempts < 1000


def test_reservations_do_not_mutate_previous_state():
    state, _ = queue.admit(None, "job", "owner", "config", 0)
    before = json.dumps(state, sort_keys=True)
    next_state, _ = queue.reserve(state, "job", 5000, 0)
    assert json.dumps(state, sort_keys=True) == before
    queue.defer(next_state, "job", 1, 60)
    assert next_state["jobs"]["job"]["readyAt"] == 0