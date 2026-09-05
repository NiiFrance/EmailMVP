"""Lease-backed publication checkpoints shared by HTTP retries and queue workers."""

import json
from threading import Event, Thread


class PublishCheckpoint:
    def __init__(self, blob, fence):
        self.blob = blob
        self.fence = fence
        self.stopped = Event()
        self.lost = Event()

    def __enter__(self):
        self.lease = self.blob.acquire_lease(lease_duration=60)
        self.thread = Thread(target=self._renew, daemon=True)
        self.thread.start()
        return self

    def _renew(self):
        while not self.stopped.wait(20):
            try:
                self.lease.renew()
            except Exception:
                self.lost.set()
                return

    def load(self):
        return json.loads(self.blob.download_blob(lease=self.lease).readall())

    def save(self, state):
        self.assert_current()
        self.blob.upload_blob(json.dumps(state).encode("utf-8"), overwrite=True, lease=self.lease)

    def assert_current(self):
        if self.lost.is_set() or not self.fence():
            raise RuntimeError("Publication lease or operation ownership was lost.")

    def __exit__(self, *args):
        self.stopped.set()
        self.thread.join()
        if not self.lost.is_set():
            self.lease.release()