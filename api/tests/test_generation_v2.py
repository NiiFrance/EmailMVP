from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio
import json

import pytest

import tests.test_function_app as fixture
import generation_v2


def context_for(reference):
    context = MagicMock()
    context.get_input.return_value = reference
    context.current_utc_datetime = datetime(2026, 9, 5, tzinfo=timezone.utc)
    return context


def test_orchestration_uses_references_and_bounds_history():
    context = context_for({"instance_id": "job-v2", "config_hash": "hash", "owner": "owner"})
    generator = generation_v2.orchestrate(context, MagicMock())
    next(generator)
    generator.send({"count": 1000, "totalLeads": 1000})
    for index in range(24):
        generator.send({"done": True, "failed": False})
    with pytest.raises(StopIteration):
        generator.send({"done": True, "failed": False})
    continued = context.continue_as_new.call_args.args[0]
    assert continued["index"] == 25 and continued["failed"] == 0
    assert "results" not in continued and "leads" not in continued
    for call in context.call_activity_with_retry.call_args_list:
        assert "results" not in call.args[2] and "lead_data" not in call.args[2]


def test_throttling_uses_a_durable_timer_not_a_failed_row():
    context = context_for({"manifest": {"count": 1, "totalLeads": 1}})
    generator = generation_v2.orchestrate(context, MagicMock())
    next(generator)
    generator.send({"done": False, "retryAfter": 3600, "phase": "throttled"})
    assert context.create_timer.call_args.args[0].hour == 1
    generator.send(None)
    generator.send({"done": True, "failed": False})
    assert context.call_activity_with_retry.call_args.args[0] == "finish_generation_v2"
    with pytest.raises(StopIteration) as result:
        generator.send({"status": "completed", "failedLeads": 0})
    assert result.value.value["failedLeads"] == 0


def test_retry_after_is_not_shortened():
    error = SimpleNamespace(response=SimpleNamespace(headers={"retry-after": "3600"}))
    assert generation_v2.retry_after(error) == 3600
    error.response.headers = {"retry-after-ms": "90000"}
    assert generation_v2.retry_after(error) == 90


def test_snapshot_reference_is_content_addressed():
    first, encoded = generation_v2.encode_config({"job_id": "job", "template_config": {"snapshot": {"system_prompt": "old"}}})
    second, _ = generation_v2.encode_config({"template_config": {"snapshot": {"system_prompt": "new"}}, "job_id": "job"})
    assert len(first) == 64 and first != second
    assert b"old" in encoded


class Blob:
    def __init__(self):
        self.content = None
        self.writes = 0

    def upload_blob(self, content, overwrite=False, **kwargs):
        if self.content is not None and not overwrite:
            raise generation_v2.ResourceExistsError()
        self.content = content
        self.writes += 1

    def acquire_lease(self, **kwargs):
        return MagicMock()

    def download_blob(self, **kwargs):
        return SimpleNamespace(readall=lambda: self.content)


def runtime_fixture():
    store = MagicMock()
    store.get_job.return_value = {"status": "generating", "generationInstanceId": "instance"}
    store.change_generation_queue.return_value = {"granted": True}
    blobs = {}
    def blob(container, path):
        return blobs.setdefault((container, path), Blob())
    def download(container, path):
        target = blob(container, path)
        if target.content is None:
            raise generation_v2.ResourceNotFoundError()
        return target.content
    def upload(container, path, content):
        if hasattr(content, "read"):
            content = content.read()
        blob(container, path).upload_blob(content, overwrite=True)
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='[{"subject":"Hello","body":"Example"}]', refusal=None))])
    template = {"system_prompt": "Approved facts", "num_emails": 1, "build_user_prompt": lambda lead: "Example contact",
                "parse_response": json.loads, "output_headers": lambda: ["Subject_Touch1", "Body_Touch1"],
                "flatten_result": lambda parsed: {"Subject_Touch1": parsed[0]["subject"], "Body_Touch1": parsed[0]["body"]}}
    runtime = generation_v2.Runtime(store, download, upload, blob, lambda config: template, lambda: client, "input", "output", "model")
    reference = {"job_id": "job", "instance_id": "instance", "config_hash": "hash", "owner": "owner", "index": 0}
    upload("output", "generation-v2/config/hash.json", json.dumps({"job_id": "job", "template_config": {}}).encode())
    runtime.write(reference, "input/0.json", [{"row_index": 0}])
    return runtime, reference, store, client, blobs


def test_duplicate_activity_uses_checkpoint_without_another_model_call():
    runtime, reference, store, client, blobs = runtime_fixture()
    assert runtime.process(reference) == {"done": True, "failed": False}
    assert runtime.process(reference) == {"done": True, "failed": False}
    client.chat.completions.create.assert_called_once()
    client.close.assert_called_once()
    assert store.change_generation_queue.call_count == 1


def test_interrupted_response_is_not_blindly_regenerated():
    runtime, reference, store, client, blobs = runtime_fixture()
    runtime.write(reference, "rows/0.json", {"inFlight": True, "attempt": 1})
    assert runtime.process(reference) == {"done": True, "failed": True}
    client.chat.completions.create.assert_not_called()
    assert "explicitly" in runtime.read(reference, "rows/0.json")["result"]["error"]


def test_429_is_saved_even_if_shared_cooldown_storage_fails():
    runtime, reference, store, client, blobs = runtime_fixture()
    error = RuntimeError("Throttled")
    error.status_code = 429
    error.response = SimpleNamespace(headers={"retry-after": "3600"})
    client.chat.completions.create.side_effect = error
    store.change_generation_queue.side_effect = [{"granted": True}, RuntimeError("storage unavailable")]
    with pytest.raises(RuntimeError, match="storage unavailable"):
        runtime.process(reference)
    result = runtime.process(reference)
    assert not result["done"] and result["retryAfter"] > 3590
    client.chat.completions.create.assert_called_once()


def test_stale_operation_cannot_write_results():
    runtime, reference, store, client, blobs = runtime_fixture()
    store.get_job.return_value = {"status": "generating", "generationInstanceId": "new-instance"}
    with pytest.raises(ValueError, match="no longer owns"):
        runtime.process(reference)
    client.chat.completions.create.assert_not_called()


def test_assembly_replay_preserves_results_and_only_downloads_row_references():
    runtime, reference, store, client, blobs = runtime_fixture()
    runtime.upload("input", "job.csv", b"Email\nalex@example.com\n")
    runtime.write(reference, "manifest.json", {"count": 1, "totalLeads": 1})
    runtime.process(reference)
    result = runtime.finish(reference)
    assert result["successfulLeads"] == 1
    assert b"Hello" in runtime.download("output", "job.csv")
    writes = blobs["output", "job.csv"].writes
    assert runtime.finish(reference) == result
    assert blobs["output", "job.csv"].writes == writes


def test_dispatch_is_idempotent_and_never_starts_an_existing_instance():
    client = SimpleNamespace(get_status=AsyncMock(return_value=SimpleNamespace(runtime_status="Running")), start_new=AsyncMock())
    with patch.object(fixture.fa.data_store, "change_generation_queue", return_value=True):
        asyncio.run(fixture.fa._dispatch_generation_v2(client, {"instance_id": "instance"}))
    client.start_new.assert_not_called()


def test_dispatch_failure_retains_accepted_queue_work():
    reference = {"job_id": "job", "instance_id": "instance", "owner": "owner", "config_hash": "hash"}
    with patch.object(fixture.fa, "_prepare_admission_v2", return_value=reference), \
            patch.object(fixture.fa, "_dispatch_generation_v2", new=AsyncMock(side_effect=RuntimeError("network"))), \
            patch.object(fixture.fa.data_store, "change_generation_queue") as change:
        result = asyncio.run(fixture.fa._admit_generation_v2(MagicMock(), "owner", {"job_id": "job"}))
    assert result["status"] == "queued"
    change.assert_not_called()


def test_streamed_repair_preserves_other_rows_and_original_indices():
    runtime, reference, store, client, blobs = runtime_fixture()
    runtime.upload("output", "generation-v2/config/hash.json", json.dumps({"job_id": "job", "template_config": {}, "repair": True, "row_indices": [1]}).encode())
    runtime.upload("output", "job.csv", b"Email,Subject_Touch1,Body_Touch1,Generation_Status,Generation_Error\na@example.com,Keep subject,Keep body,completed,\nb@example.com,,,failed,old error\n")
    runtime.write(reference, "manifest.json", {"count": 1, "totalLeads": 2})
    runtime.write(reference, "rows/0.json", {"result": {"row_index": 1, "parsed": [{"subject": "Repaired", "body": "Repaired body"}]}})
    assert runtime.finish(reference)["successfulLeads"] == 2
    frame = generation_v2.parse_csv(runtime.download("output", "job.csv"))
    assert frame.iloc[0]["Subject_Touch1"] == "Keep subject" and frame.iloc[0]["Body_Touch1"] == "Keep body"
    assert frame.iloc[1]["Subject_Touch1"] == "Repaired"


def test_admission_pause_blocks_new_work_before_any_storage_write():
    with patch.dict(fixture.fa.os.environ, {"GENERATION_ADMISSIONS_PAUSED": "true"}), \
            patch.object(fixture.fa, "_prepare_admission_v2") as prepare:
        with pytest.raises(fixture.fa.generation_queue.Busy, match="Accepted jobs continue"):
            asyncio.run(fixture.fa._admit_generation_v2(MagicMock(), "owner", {"job_id": "job"}))
    prepare.assert_not_called()


def test_help_only_pilot_does_not_touch_v2_queue_storage():
    with patch.dict(fixture.fa.os.environ, {"GENERATION_SCHEDULER_V2": "false", "GENERATION_V2_DRAIN_ENABLED": "false"}), \
            patch.object(fixture.fa.data_store, "get_generation_queue") as get:
        asyncio.run(fixture.fa.recover_generation_v2(MagicMock(), MagicMock()))
    get.assert_not_called()