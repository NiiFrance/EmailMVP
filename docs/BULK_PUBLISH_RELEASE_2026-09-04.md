# Bulk Publication Release Candidate

Historical September 4 snapshot. Superseded by [September 5 validation](BULK_PUBLISH_VALIDATION_2026-09-05.md); the status and blockers below describe the earlier preparation stage, not the current deployment state.

## Implemented

- One queue-backed publication flow for list export, draft creation and Copilot internal bulk actions.
- Twenty-row deliveries, immutable CSV snapshots, account fingerprints, renewed 60-second blob leases, fenced Table updates, and five-minute timer recovery for undelivered/restarted queue work.
- Saved row outcomes and list/campaign IDs. Failed-only retries preserve completed work. Ambiguous mutations stop as `needs_review`; they are not automatically replayed.
- Partial/failed outcomes are distinct from completed. Draft content failures reuse the existing campaign on retry. Campaign content writes are blocked once the campaign leaves draft/new status.
- Recipients must come from the mapped email column. Duplicate rows, missing/incomplete drafts, legacy error placeholders and missing custom fields are blocked.
- Active destination lists are blocked. Unknown active-campaign list associations fail closed. A new dedicated list is the UI default.
- Retry-After is honored; every retry reserves a rate slot. Ambiguous POST failures are not blindly retried. Rate-coordination failures stop requests.
- Company websites are included only when explicitly provided and valid, using a URL. Recipient email domains are no longer invented as company websites.
- Guided sender/timing/draft controls, persistent progress on reopening a job, row errors, failed-only retry and safe API-response parsing.
- Strict generated-email schema/count, immutable template snapshots, separate Generation_Status/Generation_Error columns, and regeneration of failed indices while preserving successful drafts.
- Admin brief, sample preview, optional advanced prompt, unpublished save and publish actions. Preview calls are admin-only and bounded.
- Separate generation/Copilot/builder deployment settings and opt-in stateless Responses API tool loop, retaining reasoning and function-call items and exact-action confirmations.

## Verified Locally

`api/.venv/Scripts/python -m pytest api/tests -q`: **380 passed**.

Coverage includes synthetic 100, 500 and 1001-lead deliveries, interrupted workers, lost leases, stale operation ownership, failed-only retry, incomplete campaign content, duplicate rows, malformed recipients, missing fields, active lists, template snapshots and admin authorization. These are functional/fault simulations, not production throughput measurements.

`node --check frontend/app.js`: passed. Editor diagnostics: no errors. Real Azure Functions SDK import: 62 functions registered, including new worker/timer/retry/regeneration/builder entry points. `git diff --check`: passed.

Integrated browser with intercepted synthetic API responses:
- 1440px desktop and 390px mobile without horizontal overflow.
- Sender form outside Advanced options; progress showed 1001 total, 1000 exported, 1 failed.
- Existing lists do not override the dedicated-list default.
- Reopening a job recovers its saved operation.
- Admin preview appears with the prompt collapsed; changed brief invalidates preview; unpublished save submits the draft state.
- Floating Copilot control hidden while editing templates to avoid covering mobile inputs.

Local preview server: http://127.0.0.1:8791/. This serves static frontend files only; browser test API interception is synthetic and not an operational backend.

## Azure State

Created only the isolated `emailmvp-luna-canary` deployment in existing account `azai-emailmvp-foundry-dah2`, resource group `rg-emailmvp-foundry-eastus2`, DAH Subscription `8538aabe-e5de-4e8c-a29d-2914ecf1e65e`.

- Model: `gpt-5.6-luna`, version `2026-07-09`.
- SKU: DataZoneStandard, capacity 50; creation reported Succeeded.
- Policy: Microsoft.DefaultV2; NoAutoUpgrade.
- Existing `gpt-5.4-mini` deployment preserved. No app settings changed.
- Payload: `infra/luna-canary.json`.

The synthetic inference script is `scripts/evaluate_model_canary.py`. Its first run received unresolved Key Vault references instead of runtime values and failed before inference. The subsequent attempt to resolve existing settings received ForbiddenByRbac. Secret access was not bypassed; no key fallback, alternate identity, role change or secret output occurred. **No valid live mini/Luna comparison, cost measurement, or performance conclusion is available.**

The Foundry prerequisite was resolved using a Microsoft-signed portable azd 1.33.0 in the temporary directory. The required Foundry extensions were installed/updated. No system-wide CLI installer or elevation was used.

## Release Gates Still Open

1. Sign in normally to the test-bed browser. It currently stops at the Microsoft Entra sign-in screen.
2. Complete azure-validate, capture rollback packages, and deploy the candidate to test bed only through azure-deploy. Historical August validation is not evidence for this release.
3. Test authenticated ownership and real storage lease/queue/timer recovery. Simulated tests do not prove the production binding or managed-identity behavior.
4. Run synthetic structured-generation, Responses tool-loop and builder checks through authorized inference access. Benchmark representative prompts, refusals, quality, cost and concurrent throughput before selecting Luna settings.
5. Use a controlled Snov.io account and dedicated inactive lists to verify actual field storage, campaign merge-field rendering, sender/schedule contracts, status/link shape and failure recovery. Never launch outreach as part of the test.
6. Resolve shared-account rate coordination across the three apps before a shared-account concurrent rollout; current rate coordination remains per storage account.
7. Port verified shared changes to Cloudware and Reliance, preserving branding and excluding test-bed dashboard/delegation/learning code. Run each branch's full suite and authenticated pilot before production deployment.

## Operational Limits

- Existing legacy export requests are not automatically replayed by the new worker; review their existing destination first.
- Published CSV snapshots are immutable. Draft edits and regeneration are blocked after an export snapshot is created. Use a new job for a changed batch; completed list-only exports can be extended into a draft without resyncing leads.
- Legacy generation jobs without a template snapshot cannot be regenerated with an assumed current prompt.
- Missing Snov.io custom fields require the documented account setup. No undocumented custom-field creation API was invented.
- `needs_review` requires human reconciliation in Snov.io before a new operation. This is intentionally conservative; automatic resource reconciliation is not yet implemented.
- Changing credentials cannot redirect an in-progress job to a different account. Restore the original account before retrying.
- Generic MCP confirmations retain the existing consume-once semantics; this release routes the internal bulk actions through publication but does not redesign all MCP confirmation persistence.
- Model configuration defaults still preserve the existing app setting. To canary Copilot later, both its deployment setting and `AZURE_OPENAI_COPILOT_USE_RESPONSES=true` must be selected together after live validation.

No application deployments, production worktree edits, commits, real lead uploads, campaign launches, permission changes or production model switches were performed in this implementation session.