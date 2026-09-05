from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from unittest.mock import patch

import tests.test_function_app as fixture

fa = fixture.fa


class Entity(dict):
    def __init__(self, values, version):
        super().__init__(values)
        self.metadata = {"etag": str(version)}


class AtomicTable:
    def __init__(self):
        self.lock = Lock()
        self.row = None
        self.version = 0

    def get_entity(self, partition, key):
        with self.lock:
            if self.row is None:
                raise fa.data_store.ResourceNotFoundError()
            return Entity(deepcopy(self.row), self.version)

    def create_entity(self, row):
        with self.lock:
            if self.row is not None:
                raise fa.data_store.ResourceExistsError()
            self.row = deepcopy(row)
            self.version += 1

    def update_entity(self, row, **kwargs):
        with self.lock:
            if kwargs["etag"] != str(self.version):
                raise fa.data_store.ResourceModifiedError()
            self.row = deepcopy(row)
            self.version += 1


def test_concurrent_workers_share_one_slot():
    table = AtomicTable()
    with patch.object(fa.data_store, "_table", return_value=table), patch.object(fa.data_store.time, "time", return_value=1000):
        with ThreadPoolExecutor(max_workers=12) as workers:
            delays = list(workers.map(lambda unused: fa.data_store.reserve_snovio_rest_slot("account", 20), range(40)))
    assert delays.count(0.0) == 1
    assert all(delay == 3.0 for delay in delays if delay)


def test_three_app_budgets_do_not_burst_at_window_boundary():
    accepted = []
    for app in range(3):
        table = AtomicTable()
        with patch.object(fa.data_store, "_table", return_value=table):
            for second in range(181):
                with patch.object(fa.data_store.time, "time", return_value=1000 + second):
                    if fa.data_store.reserve_snovio_rest_slot("shared-account", 20) == 0:
                        accepted.append(second)
    for end in range(60, 181):
        assert sum(end - 60 < second <= end for second in accepted) <= 60


def test_secret_rotation_keeps_same_rate_bucket():
    with patch.object(fa.data_store, "reserve_snovio_rest_slot", return_value=0.0) as reserve:
        fa._build_snovio_client("account", "old-secret").rate_reserver()
        fa._build_snovio_client("account", "new-secret").rate_reserver()
    assert reserve.call_args_list[0] == reserve.call_args_list[1]