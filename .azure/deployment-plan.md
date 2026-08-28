# EmailMVP Reliance Deployment Plan

Status: Validated
Mode: MODIFY / deploy-only
Approved by: User request on 2026-08-28, "Battle test it then"

## Goal
Deploy the tested Snov.io sync and Copilot confirmation hardening to Reliance production without provisioning or deleting resources.

## Azure Context
- Subscription: `8538aabe-e5de-4e8c-a29d-2914ecf1e65e` (DAH Subscription)
- Region: `eastus2`
- Resource group: `rg-emailmvp-eastus2`
- Function App: `azfny76j3nkoga2rw`
- Static Web App: `azsway76j3nkoga2rw`
- Public URL: `https://brave-pebble-0633e900f.7.azurestaticapps.net`

## Architecture
Existing Azure Static Web Apps authentication proxies `/api/*` to Python Azure Functions. The Function App uses managed identity for Azure Blob, Queue, and Table Storage. Executed Snov.io syncs return HTTP 202, persist an operation request in Blob Storage, enqueue an ID-only message to `snovio-sync`, update an ETag-guarded job row in Table Storage, and expose an owner-scoped status endpoint. Snov.io MCP confirmations remain user-bound and single-use.

## Changes
- Deploy the `api/` package with queued sync trigger/status route and MCP error handling.
- Set `SNOVIO_SYNC_QUEUE=snovio-sync`.
- Deploy `frontend/` with safe response parsing and sync polling.
- Synchronize Function trigger metadata.
- Preserve Reliance branding and production-only feature boundaries.

## Validation Proof
- Timestamp: 2026-08-28 UTC.
- Backend: shared venv `python -m pytest tests -q` -> 299 passed.
- Build: `python -m compileall` and `node --check frontend/app.js` -> passed.
- IaC compile: `az bicep build --file infra/main.bicep --stdout` -> passed.
- Initial full-IaC ARM validation/what-if -> blocked by caller lacking `roleAssignments/write`; no deployment attempted.
- Deploy-only validation: `validate-deployment.ps1 -Scope group -ResourceGroup rg-emailmvp-eastus2 -Template .azure/deploy-only.bicep -Parameters .azure/validate.parameters.json` -> OVERALL PASS; 0 create, 0 modify, 0 delete.
- Policy: `policy_assignment_list` at subscription scope -> no assignments.
- Live state: Function App Running; required managed-identity storage data roles verified.
- Editor diagnostics: no errors in touched files.
- Live Cloudware root cause and corrected behavior were reproduced with focused tests before this portable commit was applied.

## All validation checks pass
- [x] Core Validation: Azure CLI installed/authenticated; deploy-only Bicep build and ARM validation pass; what-if is 0 create, 0 modify, 0 delete.
- [x] Docker Build: not applicable; this is a Python zip deployment.
- [x] Azure Policy Validation: subscription has no assigned policies; no deployment blocker.
- [x] Resource/RBAC Validation: Function App is Running; managed identity `9d32a871-5636-4c72-a4ba-04db7772c371` has required Blob, Queue, and Table data roles on `azsty76j3nkoga2rw`.

## Role Assignment Verification
- Status: Verified.
- Identity: user-assigned Function identity from `infra/main.bicep`.
- Storage scope: account-level Blob Data Owner/Contributor, Queue Data Contributor, Table Data Contributor, and Monitoring Metrics Publisher.
- Key Vault scope: Key Vault Secrets Officer for the deployment-managed vault.
- Issue: Blob Data Owner and Blob Data Contributor overlap; existing non-blocking redundancy, unchanged in this code-only release.

## Deployment Steps
1. Verify existing resources and capture current package/commit rollback identifiers.
2. Verify managed identity retains Blob Data, Queue Data, and Table Data permissions.
3. Set the non-secret `SNOVIO_SYNC_QUEUE` app setting.
4. Zip-deploy `api/` excluding tests, caches, and virtual environments with remote build.
5. Synchronize triggers and verify `process_snovio_sync` plus `get_snovio_sync_status` are indexed.
6. Deploy the matching `frontend/` directory to the existing production SWA environment.
7. Smoke-test authentication, JSON errors, OAuth status, and anonymous webhook protection.
8. Run only non-outbound reversible checks if a Reliance Snov.io test connection is available.

## Rollback
Redeploy the captured previous Function package and matching prior frontend commit. Restore immediately if trigger indexing, queue processing, authentication, or owner scoping fails.
