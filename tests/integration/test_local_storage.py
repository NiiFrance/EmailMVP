"""Run separately from stubbed API tests, against loopback Azurite only."""

import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
from threading import Thread
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import uuid

import pytest

os.environ["AzureWebJobsStorage"] = "UseDevelopmentStorage=true"
os.environ["STORAGE_CONNECTION_STRING"] = "UseDevelopmentStorage=true"
os.environ.pop("AzureWebJobsStorage__accountName", None)
os.environ.pop("AzureWebJobsStorage__clientId", None)
os.environ["AZURE_OPENAI_API_KEY"] = "local-synthetic-key"
os.environ["AZURE_OPENAI_GENERATION_DEPLOYMENT"] = "emailmvp-luna-canary"
os.environ["GENERATION_SCHEDULER_V2"] = "true"
os.environ["ONBOARDING_AUTO_INVITES"] = "true"
os.environ["ALLOWED_EMAIL_DOMAINS"] = "example.com"
os.environ["ADMIN_EMAILS"] = ""
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "api"))

import azure.functions as func
from azure.core.exceptions import ResourceExistsError
import data_store
import function_app
import generation_v2
import onboarding
from prompt_templates import get_template, template_snapshot


@pytest.fixture(scope="module", autouse=True)
def local_services():
    calls = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            count = body["response_format"]["json_schema"]["schema"]["properties"]["emails"]["minItems"]
            content = json.dumps({"emails": [{"subject": f"Synthetic subject {index + 1}", "body": "Fictional example. No message was sent."} for index in range(count)]})
            encoded = json.dumps({"id": "synthetic", "object": "chat.completion", "created": 1, "model": "local-synthetic",
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300}}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    function_app.AZURE_OPENAI_ENDPOINT = f"http://127.0.0.1:{server.server_port}"
    for container in [function_app.INPUT_CONTAINER, function_app.OUTPUT_CONTAINER]:
        try:
            function_app._blob_service().create_container(container)
        except ResourceExistsError:
            pass
    assert "127.0.0.1" in data_store._table_service().url
    yield calls
    server.shutdown()
    server.server_close()
    worker.join()


def principal(owner):
    return {"x-ms-client-principal": base64.b64encode(json.dumps({"userId": owner, "userDetails": "synthetic@example.com", "userRoles": ["authenticated"]}).encode()).decode()}


def test_real_table_concurrent_invites_and_owner_isolation():
    owner = str(uuid.uuid4())
    def claim(index):
        return data_store.change_onboarding(owner, "user", {"version": onboarding.VERSION, "action": "invite", "requestId": f"request-{index:08d}"})
    with ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(claim, range(20)))
    assert sum(result[1]["granted"] for result in results) == 1
    assert data_store.get_onboarding(owner)["invitations"] == 1
    assert data_store.get_onboarding(str(uuid.uuid4()))["invitations"] == 0


def test_real_http_request_obeys_owner_and_does_not_change_resume_context():
    owner = str(uuid.uuid4())
    data_store.upsert_user(owner, "synthetic@example.com", "Synthetic", "user")
    data_store.set_user_context(owner, {"jobId": "existing", "step": "step3"})
    before = data_store.get_user(owner)["lastContext"]
    request = func.HttpRequest("POST", "http://localhost/api/me/onboarding", headers=principal(owner), body=json.dumps({
        "action": "preferences", "version": onboarding.VERSION, "optOut": True, "oid": "different-owner", "role": "admin",
    }).encode())
    response = asyncio.run(function_app.onboarding_state(request))
    assert response.status_code == 200
    assert data_store.get_onboarding(owner)["optOut"]
    assert data_store.get_user(owner)["lastContext"] == before


def test_real_leases_snapshot_and_sdk_generate_once(local_services):
    owner, job_id = str(uuid.uuid4()), str(uuid.uuid4())
    template = get_template("cold_email")
    data_store._table(data_store.JOBS_TABLE).create_entity({"PartitionKey": owner, "RowKey": job_id, "status": "uploaded", "totalLeads": 1})
    function_app._upload_blob(function_app.INPUT_CONTAINER, f"{job_id}.csv", b"First Name,Last Name,Company,Email,License Renewal,Engagement Objectives\nAlex,Example,Example Company,alex@example.com,Microsoft 365,Review licenses\n")
    config = {"job_id": job_id, "column_map": {"first_name": 0, "last_name": 1, "organization": 2, "email": 3, "license_renewal": 4, "engagement_objectives": 5}, "template_config": template_snapshot(template)}
    reference = function_app._prepare_admission_v2(owner, config)
    repeated = function_app._prepare_admission_v2(owner, config)
    assert repeated == reference
    runtime = function_app._generation_runtime_v2()
    manifest = runtime.prepare(reference)
    assert manifest == {"count": 1, "totalLeads": 1}
    before = len(local_services)
    result = runtime.process({**reference, "index": 0})
    assert result == {"done": True, "failed": False}
    assert runtime.process({**reference, "index": 0}) == result
    assert len(local_services) - before == 1
    outcome = runtime.finish({**reference, "failed": 0})
    assert outcome["status"] == "completed"
    output = function_app._download_blob(function_app.OUTPUT_CONTAINER, f"{job_id}.csv")
    assert b"Synthetic subject" in output and b"No message was sent" in output
    assert reference["instance_id"] not in data_store.get_generation_queue()["jobs"]