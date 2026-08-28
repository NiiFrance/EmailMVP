# EmailMVP Cloudware Deployment Plan

Status: Validated
Mode: MODIFY / deploy-only
Approved by: User request on 2026-08-28, "Battle test it then"

## Goal
Deploy the tested Snov.io timeout and false-confirmation fixes to Cloudware production without provisioning or deleting resources.

## Azure Context
- Subscription: `8538aabe-e5de-4e8c-a29d-2914ecf1e65e` (DAH Subscription)
- Region: `eastus2`
- Resource group: `rg-emailmvp-cloudware-eastus2`
- Function App: `azfnkhj2hcaa7fpcm`
- Static Web App: `azswakhj2hcaa7fpcm`
- Public URL: `https://mango-bush-067ca3b0f.7.azurestaticapps.net`

## Architecture
Existing Azure Static Web Apps authentication proxies `/api/*` to Python Azure Functions. The Function App uses managed identity for Azure Blob, Queue, and Table Storage. Executed Snov.io syncs return HTTP 202, persist an operation request in Blob Storage, enqueue an ID-only message to `snovio-sync`, update an ETag-guarded job row in Table Storage, and expose an owner-scoped status endpoint. Snov.io MCP confirmations remain user-bound and single-use.

## Changes
- Deploy the `api/` package with queued sync trigger/status route and MCP `isError` handling.
- Set `SNOVIO_SYNC_QUEUE=snovio-sync`.
- Deploy `frontend/` with safe response parsing, background polling, and verified result display.
- Synchronize Function trigger metadata.
- Preserve Cloudware branding and production-only feature boundaries.

## Validation Proof
- Timestamp: 2026-08-28 UTC.
- Backend: shared venv `python -m pytest tests -q` -> 297 passed.
- Build: `python -m compileall` and `node --check frontend/app.js` -> passed.
- IaC compile: `az bicep build --file infra/main.bicep --stdout` -> passed.
- Initial full-IaC ARM validation/what-if -> blocked by caller lacking `roleAssignments/write`; no deployment attempted.
- Deploy-only validation: `validate-deployment.ps1 -Scope group -ResourceGroup rg-emailmvp-cloudware-eastus2 -Template .azure/deploy-only.bicep -Parameters .azure/validate.parameters.json` -> OVERALL PASS; 0 create, 0 modify, 0 delete.
- Policy: `policy_assignment_list` at subscription scope -> no assignments.
- Live state: Function App Running; required managed-identity storage data roles verified.
- Editor diagnostics: no errors in touched files.
- Live root cause: `sync_job_to_snovio` returned HTTP 200 after 112-165 seconds; SWA returned a plain-text backend timeout first.
- Live false-success evidence: Golda's confirmation invoked `app_add_prospects_to_list` in 148 ms without a list ID; the old endpoint returned 200 even for MCP `isError` results.

## All validation checks pass
- [x] Core Validation: Azure CLI installed/authenticated; deploy-only Bicep build and ARM validation pass; what-if is 0 create, 0 modify, 0 delete.
- [x] Docker Build: not applicable; this is a Python zip deployment.
- [x] Azure Policy Validation: subscription has no assigned policies; no deployment blocker.
- [x] Resource/RBAC Validation: Function App is Running; managed identity `636f3343-87ca-4cbf-a235-f3fc209918fb` has required Blob, Queue, and Table data roles on `azstkhj2hcaa7fpcm`.

## Role Assignment Verification
- Status: Verified.
- Identity: user-assigned Function identity from `infra/main.bicep`.
- Storage scope: account-level Blob Data Owner/Contributor, Queue Data Contributor, Table Data Contributor, and Monitoring Metrics Publisher.
- Key Vault scope: Key Vault Secrets Officer for the deployment-managed vault.
- Issue: Blob Data Owner and Blob Data Contributor overlap; existing non-blocking redundancy, unchanged in this code-only release.

## Deployment Steps
1. Verify existing resources and capture the current package/commit rollback identifiers.
2. Verify managed identity Blob Data, Queue Data, and Table Data permissions.
3. Set the non-secret `SNOVIO_SYNC_QUEUE` app setting.
4. Zip-deploy `api/` excluding tests, caches, and virtual environments with remote build.
5. Synchronize triggers and verify `process_snovio_sync` and `get_snovio_sync_status` are indexed.
6. Deploy the matching `frontend/` directory to the existing production SWA environment.
7. Smoke-test auth, Settings, OAuth status, JSON errors, and webhook protection.
8. Create and delete a uniquely named test list through exact confirmation.
9. Queue a harmless one-lead sync to a uniquely named test list, verify 202 -> running -> completed, verify one report and one list, then delete the test list. Send no outreach.

## Rollback
Redeploy the captured previous Function package and matching prior frontend commit. Restore immediately if trigger indexing, queue processing, authentication, owner scoping, or reversible Snov.io tests fail.
