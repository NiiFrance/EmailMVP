# EmailMVP Test-Bed Deployment Plan

Status: Validated
Mode: MODIFY / staged rollout
Approved by: User request on 2026-09-05, "begin", following the onboarding and capacity plan.

## Current Pilot Scope
Current outcome: Help-only test-bed pilot deployed and authenticated smoke checks passed; representative-user feedback pending. V2 capacity remains blocked.
User selected "Pilot Help separately; keep V2 disabled" after reviewing the failed capacity gate.
Deploy only to existing test-bed Function azfnocp2inqabawqu and SWA azswaocp2inqabawqu in rg-emailmvp-dah.
Manual tours and Help enabled; automatic invitations initially disabled until authenticated pilot checks pass.
Set GENERATION_SCHEDULER_V2=false and GENERATION_V2_DRAIN_ENABLED=false explicitly. No V2 work exists in Azure.
Keep existing model, Snov.io workflow, identity, pricing/SKU, networking and RBAC unchanged.
No Cloudware/Reliance deployment. No live generation or Snov.io writes are needed for Help smoke checks.
Pilot acceptance requires current build/runtime tests, Azure validation, authenticated state/Help checks and representative-user feedback.
Capacity results below remain blocked and outside this pilot's release claim.

### Help Pilot Validation
- [x] All validation checks pass
	- [x] Core validation: installed CLI, authentication, compile existing-resource Bicep, ARM validate, zero-change what-if.
	- [x] Container build: not applicable (Python code-only package).
	- [x] Azure Policy validation for the existing subscription/resource group.
	- [x] Full backend/browser build checks and runtime-only package inspection.
	- [x] Static role verification for managed identity Table/Blob/Queue operations.
- [x] Record new pilot proof and complete the Azure validation workflow.
- [x] Test-bed deployment and authenticated Help/onboarding smoke tests.
- [ ] Representative-user pilot feedback before any production rollout.

### Section 7: Help Pilot Validation Proof (2026-09-05)
- Azure validate-deployment.ps1 with existing-resource .azure/deploy-only.bicep, group rg-emailmvp-dah, DAH subscription 8538aabe-e5de-4e8c-a29d-2914ecf1e65e: all five checks PASS, what-if Create0/Modify0/Delete0.
- MCP policy_assignment_list at test-bed resource-group scope: no assignments returned.
- api/.venv/Scripts/python -m pytest api/tests -q: 463 passed, including Help-only V2 timer isolation.
- npm --prefix tests/browser test -- --reporter=line: 15 passed, all four walkthrough flows and Help accessibility widths.
- Separate real-SDK Azurite test process: 3 passed, ETags/Blob leases/owner isolation and synthetic OpenAI SDK; no real-service calls.
- Real Azure Functions SDK: 68 functions register; no import/binding errors. Core Tools host integration remains unverified, not replaced by the SDK check.
- PackageOnly ZIP: 28 runtime entries, no settings/tests/venv; SHA256 be87731cc580cd2c17cb7e974df1c5253438f43663aedc0a424dec0e6b592b79.
- Static roles: existing managed identity has storage-account-scoped Table Data Contributor for isolated onboarding writes, Blob/Queue Contributor for unchanged existing workflows. No role definition or scope changes.
- Authenticated predeploy /api/me HTTP200 admin through normal SWA session.
- Current backend rollback deployment d4df8196-d111-4a11-a5e0-780fcef250a2, status4.
- Current frontend captured via normal authenticated fetches in .azure/help-pilot-frontend-rollback.json.gz (45982 bytes).
- User explicitly confirmed existing DAH Subscription / East US 2 test-bed deployment and nonsecret Help/V2-off flags. No production update authorized by this pilot.
- This proof validates a Help-only test-bed pilot, not 100-user capacity or broad production readiness. Automatic invitations remain off until live checks.

### Help Pilot Deployment Outcome
- Backend9ed71419-5481-4b8d-8f97-e2a5e1e1ee4e successful; matching frontend plus locally validated usability fixes deployed.
- Final frontend suite16passed; backend463passed. Recovery search, Escape focus and background-tab lifecycle tests added during live smoke follow-up.
- ONBOARDING_ENABLED/ONBOARDING_AUTO_INVITES true; GENERATION_SCHEDULER_V2/GENERATION_V2_DRAIN_ENABLED false, explicitly verified.
- Normal authenticated onboarding GET200; manual start/pause stored; concurrent starts200/409; lastContext unchanged; live mobile Help axe0critical/serious.
- Visible live auto-invitation observation remains a human pilot check because the integrated browser reports document.hidden=true. Account invitation count remains0 after automated smoke, so the user's first offer is preserved.
- New endpoint initially404afterdeployment; host refresh resolved it. AppLens401notbypassed; ResourceHealthAvailable; storage data roles unchanged. Final trigger sync requested.
- Full evidence, rollback artifact/hash and limitations: docs/ONBOARDING_CAPACITY_IMPLEMENTATION_2026-09-05.md.
- No Cloudware/Reliance changes, paid model calls, Snov publication writes or outreach. No 100-user capacity claim.

## Active Release: Guided Help and Capacity
- Local implementation evidence: `docs/ONBOARDING_CAPACITY_IMPLEMENTATION_2026-09-05.md`.
- Release blocked: scheduler-only 100x1000 simulation took 84.59 virtual hours at the conservative 5000-token/lead reservation; the agreed several-hour envelope is not met.
- Auto invitations and V2 generation remain off by default. No new release deployed, no paid provider calls, no production ports.
- Final local checks: 462 backend tests, 15 Chromium scenarios, 3 real-SDK Azurite integration tests; scheduler-only simulation passed correctness but failed the several-hour completion envelope. Live release gates remain unchecked.
- [ ] Account-scoped onboarding state: all users, at most two optional invitations, opt-out and manual replay, concurrent-tab protection.
- [ ] Searchable Help and four event-driven walkthroughs: first campaign, Snov.io draft, recovery, admin template.
- [ ] Accessible desktop/mobile behavior, failure-isolated optional modules, no tutorial-triggered writes.
- [ ] Versioned generation admission/fair scheduling and bounded results; legacy operations drain unchanged.
- [ ] Synthetic 100-user x 1000-lead workload, real-service canary capped at USD10, no outreach launches.
- [ ] Full regression and browser/accessibility checks, test-bed pilot, staged production rollout with rollback.

Fair background completion over several hours is acceptable. Mostly separate Snov.io accounts are expected.
No 100-user capacity claim until its workload gates pass. No new resources, RBAC changes or paid capacity changes without approval.
The prior bulk-publication release evidence below is historical, not validation for this release.

## September 4 Approved Scope
- [x] Locally implement and test invalid-recipient, failed-draft, missing-field and destination guards.
- [x] Locally implement UI/Copilot publication through bounded queue deliveries, leased checkpoints and failed-only recovery.
- [x] Locally implement guided draft preparation, reload recovery and progress; no automatic outreach.
- [x] Locally implement brief/preview/publish builder, template snapshots and failed-lead regeneration.
- [x] Add opt-in Responses adapter and create isolated Luna Data Zone canary; all app settings remain on mini.
- [x] Verify synthetic 100/500/1001-lead scenarios, fault injection, ownership and desktop/mobile browser behavior.
- [ ] Live Luna inference, quality/cost comparison and throughput evaluation.
- [ ] Authenticated test-bed deployment validation and real Snov.io draft-only pilot.
- [ ] Validate and pilot test bed before production rollout; preserve brand and test-bed-only features.

## Current Release Evidence
- FINAL September 5: 1001-lead export completed at 11:51:02 UTC with 1001 added/zero failures/duplicates; Snov.io independently confirmed list40956584 contains1001 contacts. Cloudware and Reliance were then deployed sequentially and both passed live generation-to-draft smoke tests with Luna. See the current validation report; blocker and pending-release entries below are historical.
- September 5 latest: authoritative results are in `docs/BULK_PUBLISH_VALIDATION_2026-09-05.md`. Final backend 411 tests pass; test-bed deployment `d4df8196-d111-4a11-a5e0-780fcef250a2` and matching frontend are live. Luna generation/builder/Copilot use the 667-unit canary; mini remains fallback.
- 501-lead generation / 1002 complete emails passed live. The 1001-lead export resumed after explicit absent-prospect reconciliation; final count remains unverified because the integrated browser CDP connection timed out, including after user re-shared a new tab. Production is not deployed. Earlier entries below are historical stages, not the latest state.
- September 5 continuation: user confirmed existing DAH/East US 2 targets and signed in again; both previous pilot operations were rechecked as completed.
- Pending release includes the repaired builder metadata return, account-stable paced 20-request/app budget, and exact-result reconciliation. No new roles or infrastructure are required.
- Full backend suite: 380 passed on 2026-09-04.
- JavaScript syntax and editor diagnostics: passed.
- Actual Azure Functions SDK: 62 registered functions, including queue recovery, retry, regeneration and builder.
- Browser with mocked APIs: 1440px desktop and 390px mobile, no horizontal overflow; partial progress/reopen, dedicated-list default, brief preview invalidation and unpublished save verified.
- Luna canary `emailmvp-luna-canary`: Succeeded, `gpt-5.6-luna` version `2026-07-09`, DataZoneStandard capacity 50, Microsoft.DefaultV2, NoAutoUpgrade.
- Local inference blocked: runtime model settings are Key Vault references; signed-in CLI identity was denied secret read. No keys, alternate identity or role changes used.
- Live test-bed sign-in is now verified as the user's admin account. User authorized continuing validation and the staged test-bed pilot.
- No application package/frontend deployment, production branch port, commit or model-setting switch performed.
- Detailed release notes and remaining gates: `docs/BULK_PUBLISH_RELEASE_2026-09-04.md`.

Previous validation below applies only to the August archive release, not this change.
No live outreach, credential exposure, role changes, resource deletion, or global-residency change is authorized.

## Goal
Deploy the September 4 bulk-publication candidate to the existing test bed only, then validate authenticated generation, builder and draft-only publication. Preserve all production apps and their mini model settings until the pilot and remaining rollout gates pass.

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
- Deploy the current `api/` package with checkpointed publication, timer recovery, failed-lead repair, structured generation and the admin builder.
- Deploy the matching `frontend/` with guided draft preparation, recoverable progress and the brief/preview/publish builder.
- Synchronize Function trigger metadata.
- Test only synthetic jobs and dedicated Snov.io draft destinations. Never launch outreach or edit existing customer jobs/campaigns.
- Preserve production, identity, SKU, networking and RBAC. Do not read or expose model secrets through alternative access paths.

## Validation Proof
- September 5 restart-recovery correction: 411 tests pass; all frontend syntax checks pass. Confirmed absent-recipient retry disables duplicates, verifies target-list membership, and blocks other-list contacts. Existing deployment scope and permissions unchanged.
- September 5 follow-up: 405 tests pass; nonblocking account reads and forced template metadata refresh validated; editor diagnostics clear. Infrastructure, identity, package boundary and target unchanged from the completed current Azure validation.
- Controlled test-bed deployment while the synthetic 1001-lead job runs is part of restart/reconciliation validation. No production operation is targeted.
- September 5: 396 backend tests pass; final usage-estimate slice 18 passed; JavaScript syntax and actual SDK registration (62 functions) pass.
- September 5: code-only validate-deployment script passes all five checks, what-if 0 create/modify/delete; current policy list empty; Function Running; managed identity retains Blob/Queue/Table data roles.
- September 5: runtime ZIP inspected, 25 entries, no local settings/tests/virtual environments; rollback backend `c63b3d4f-d739-4473-aead-4640c3fe1c7b` captured.
- Current release: 2026-09-04, DAH Subscription / rg-emailmvp-dah / eastus2, explicitly confirmed by user.
- `python -m pytest api/tests -q`: 380 passed.
- `node --check frontend/app.js`: passed; actual Function SDK registered 62 functions.
- `scripts/redeploy_api.ps1 -PackageOnly`: runtime-only ZIP verified, 25 entries, new modules present, local settings/tests excluded.
- `validate-deployment.ps1 -Scope group -ResourceGroup rg-emailmvp-dah -Template .azure/deploy-only.bicep -Parameters .azure/validate.parameters.json -Subscription 8538aabe-e5de-4e8c-a29d-2914ecf1e65e`: all five checks PASS; what-if 0 create/modify/delete. This validates deployment scope, not application behavior.
- Current policy query: no applicable subscription assignments returned.
- Current Function state: Running. Existing user-assigned identity has Blob/Queue/Table data roles. No RBAC changes required or performed.
- Authenticated live baseline: /api/me 200 admin; saved Snov.io account configured; valid sender and Subject/Body_Touch1..8 fields available.
- Rollback Function deployment: `761ddfa7-30ae-43cd-adc4-6bc8fba5c704`. Frontend rollback ZIP: `.azure/testbed-frontend-rollback.zip`, base `f65dd3524f5908fa639a5250c9aa1732cb6098ec`.

### Historical August Proof
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
- [x] Core Validation: CLI, auth, compile, ARM validate and what-if passed on September 5.
- [x] Docker Build: not applicable; runtime package and SDK registration verified.
- [x] Azure Policy Validation: current assignment query returned no policies.
- [x] Resource/RBAC Validation: Function Running and existing managed-identity data roles verified.
- [x] Current application checks: backend tests, JavaScript syntax, runtime registration and package inspection passed.

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
6. Smoke-test authentication, owner scoping, builder preview and structured generation using synthetic inputs.
7. Verify dedicated draft-only publication, real queue/timer/checkpoint behavior, custom field content, retry and reload recovery.
8. Keep production rollout and model switching gated on successful pilot and model evaluation. Record remaining blockers explicitly.

## Rollback
Redeploy the captured previous Function package and matching prior frontend commit. Restore immediately if route indexing, authentication, owner scoping, history counts, or restore behavior fails.
