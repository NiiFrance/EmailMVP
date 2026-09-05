from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from snovio_publish import CHUNK_SIZE, new_state, report_for, retry_failed, run_chunk


@pytest.mark.parametrize("count", [100, 500, 1001])
def test_bounded_chunks_resume_and_skip_successful_rows(count):
    state = new_state({"listId": "123", "mode": "list"}, "account")
    snapshots = []
    written = []

    def sync(client, job, payload, **kwargs):
        if payload["dryRun"]:
            return {"listId": "123", "rows": [{"rowIndex": index, "eligible": True} for index in range(count)]}, None
        assert len(payload["_rowIndices"]) <= CHUNK_SIZE
        for index in payload["_rowIndices"]:
            row = {"rowIndex": index, "eligible": True, "status": "failed" if index == 5 and index not in written else "added"}
            kwargs["before_write"](row)
            written.append(index)
            kwargs["on_row"](row)
        return {}, None

    def save(current):
        snapshots.append(deepcopy(current))

    for delivery in range(count // CHUNK_SIZE + 2):
        run_chunk(state, MagicMock(), "job", b"unused", save, sync)
        if state["status"] == "partial":
            break
        state = deepcopy(snapshots[-1])
    assert state["status"] == "partial"
    assert report_for(state, "job")["summary"]["failed"] == 1
    retry_failed(state)
    run_chunk(state, MagicMock(), "job", b"unused", save, sync)
    assert state["status"] == "completed"
    assert len(written) == count + 1
    run_chunk(state, MagicMock(), "job", b"unused", save, sync)
    assert len(written) == count + 1


def test_ambiguous_resource_creation_is_not_replayed():
    state = new_state({"mode": "draft"}, "account")
    state["inFlight"] = "create_campaign"
    client = MagicMock()
    run_chunk(state, client, "job", b"unused", MagicMock(), MagicMock())
    assert state["status"] == "needs_review"
    client.create_campaign.assert_not_called()
    with pytest.raises(ValueError):
        retry_failed(state)


def test_failed_rows_never_create_campaign():
    state = new_state({"mode": "draft", "listId": "123"}, "account")
    state.update(candidates=[0], total=1, rows={"0": {"rowIndex": 0, "eligible": True, "status": "failed"}})
    client = MagicMock()
    run_chunk(state, client, "job", b"unused", MagicMock(), MagicMock())
    assert state["status"] == "partial"
    client.create_campaign.assert_not_called()


def test_failed_content_reuses_existing_draft_on_retry():
    state = new_state({"mode": "draft", "listId": "123", "listName": "Test", "senderAccountIds": ["42"]}, "account")
    state.update(candidates=[0], total=1, touches=1, rows={"0": {"rowIndex": 0, "eligible": True, "status": "added"}})
    client = MagicMock()
    client.get_sender_accounts.return_value = [{"id": 42, "valid": True}]
    client.create_campaign.return_value = {"data": {"id": 77}}
    client.get_campaign.return_value = {"data": {"id": 77, "status": "new"}}
    client.create_email_step_content.side_effect = [RuntimeError("Synthetic failure"), {"success": True}]
    with patch("snovio_publish.map_email_step_contents", return_value=[{"stepId": 5, "contentId": 6}]):
        run_chunk(state, client, "job", b"unused", MagicMock(), MagicMock())
        assert state["status"] == "partial"
        assert state["campaignId"] == 77
        retry_failed(state)
        state["candidates"] = [0]
        run_chunk(state, client, "job", b"unused", MagicMock(), MagicMock())
    assert state["status"] == "completed"
    client.create_campaign.assert_called_once()
    assert client.create_email_step_content.call_count == 2
    client.add_prospect_to_list.assert_not_called()
    client.change_campaign_state.assert_not_called()


def test_worker_crash_during_write_requires_review():
    state = new_state({"mode": "list", "listId": "123"}, "account")
    state.update(candidates=[0, 1], total=2)
    saved = []

    def sync(client, job, payload, **kwargs):
        kwargs["before_write"]({"rowIndex": 0})
        kwargs["on_row"]({"rowIndex": 0, "eligible": True, "status": "added"})
        kwargs["before_write"]({"rowIndex": 1})
        raise RuntimeError("Worker interrupted")

    with pytest.raises(RuntimeError):
        run_chunk(state, MagicMock(), "job", b"unused", lambda value: saved.append(deepcopy(value)), sync)
    resumed = saved[-1]
    run_chunk(resumed, MagicMock(), "job", b"unused", MagicMock(), sync)
    assert resumed["status"] == "needs_review"
    assert resumed["rows"]["0"]["status"] == "added"


def test_checkpoint_fence_prevents_stale_worker_write():
    from publish_checkpoint import PublishCheckpoint
    blob = MagicMock()
    with PublishCheckpoint(blob, lambda: False) as checkpoint:
        with pytest.raises(RuntimeError, match="ownership"):
            checkpoint.save({"status": "completed"})
    blob.upload_blob.assert_not_called()


def test_checkpoint_lease_loss_prevents_write():
    from publish_checkpoint import PublishCheckpoint
    blob = MagicMock()
    with PublishCheckpoint(blob, lambda: True) as checkpoint:
        checkpoint.lost.set()
        with pytest.raises(RuntimeError, match="lease"):
            checkpoint.save({"status": "completed"})
    blob.upload_blob.assert_not_called()