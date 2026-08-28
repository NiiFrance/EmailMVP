# EmailMVP Test-Bed Deployment Plan

Status: Validated
Mode: MODIFY / deploy-only
Approved by: User request on 2026-08-28, "Start implementation"

## Goal
Deploy reversible campaign-history removal and restoration to the existing test-bed application without provisioning resources or deleting campaign data.

## Azure Context
- Subscription: `8538aabe-e5de-4e8c-a29d-2914ecf1e65e` (DAH Subscription)
- Region: `eastus2`
- Resource group: `rg-emailmvp-dah`
- Function App: `azfnocp2inqabawqu`
- Static Web App: `azswaocp2inqabawqu`
- Public URL: `https://ashy-ocean-0a8e5f60f.7.azurestaticapps.net`

## Architecture
Existing Azure Static Web Apps authentication proxies `/api/*` to Python Azure Functions. Campaign history is stored per Entra object ID in Azure Table Storage. The release adds an `archived` flag on existing job rows; no blobs, Durable state, or Snov.io resources are deleted. The Home UI excludes archived rows from active statistics and lazy-loads a restore section.

## Changes
- Deploy the `api/` package with owner-only job archive/restore routes and archive-aware list queries.
- Deploy `frontend/` with Remove actions for Drafted/Failed entries and a collapsed Archived campaigns restore section.
- Synchronize Function trigger metadata.
- Do not modify Snov.io resources, job files, Durable state, dashboard, delegation, learning, identity, SKU, networking, or RBAC.

## Validation Proof
- Timestamp: 2026-08-28 UTC.
- Backend: `api/.venv/Scripts/python -m pytest tests -q` -> 337 passed, including 12 focused archive tests.
- Build: `node --check frontend/app.js` -> passed.
- IaC compile: `az bicep build --file infra/main.bicep --stdout` -> passed.
- Initial full-IaC ARM validation/what-if -> blocked by caller lacking `roleAssignments/write`; no deployment attempted.
- Deploy-only validation: `validate-deployment.ps1 -Scope group -ResourceGroup rg-emailmvp-dah -Template .azure/deploy-only.bicep -Parameters .azure/validate.parameters.json` -> OVERALL PASS; 0 create, 0 modify, 0 delete.
- Policy: `policy_assignment_list` at subscription scope -> no assignments.
- Live state: Function App Running; required managed-identity storage data roles verified.
- Editor diagnostics: no errors in touched files.
- Local browser: Drafted shows Open/Remove, Failed shows Remove, Running shows neither; cancel is a no-op; archive/restore updates counts; 390px viewport has no horizontal overflow.

## All validation checks pass
- [x] Core Validation: Azure CLI installed/authenticated; deploy-only Bicep build and ARM validation pass; what-if is 0 create, 0 modify, 0 delete.
- [x] Docker Build: not applicable; this is a Python zip deployment.
- [x] Azure Policy Validation: subscription has no assigned policies; no deployment blocker.
- [x] Resource/RBAC Validation: Function App is Running; managed identity `c2bb2255-9a5c-4362-b6c6-bee8c7dd84a4` has required Blob, Queue, and Table data roles on `azstocp2inqabawqu`.

## Role Assignment Verification
- Status: Verified.
- Identity: user-assigned Function identity from `infra/main.bicep`.
- Storage scope: account-level Blob Data Owner/Contributor, Queue Data Contributor, Table Data Contributor, and Monitoring Metrics Publisher.
- Key Vault scope: Key Vault Secrets Officer for the deployment-managed vault.
- Issue: Blob Data Owner and Blob Data Contributor overlap; existing non-blocking redundancy, unchanged in this code-only release.

## Deployment Steps
1. Verify Function App and Static Web App are running and capture current package/commit rollback identifiers.
2. Verify managed identity retains Blob Data, Queue Data, and Table Data permissions.
3. Zip-deploy `api/` excluding tests, caches, and virtual environments with remote build.
4. Synchronize Function trigger metadata and verify the new job routes are mapped.
5. Deploy the matching `frontend/` directory to the existing production SWA environment.
6. Smoke-test authentication and archive API ownership/status guards.
7. Archive a disposable Drafted test entry, verify it leaves Recent and appears under Archived, restore it, and verify Open still works.
8. Confirm its input/output blobs remain and no Snov.io operation is invoked.

## Rollback
Redeploy the captured previous Function package and matching prior frontend commit. Restore immediately if route indexing, authentication, owner scoping, history counts, or restore behavior fails.
