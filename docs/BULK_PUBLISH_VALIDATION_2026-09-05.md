# Bulk Publication Validation - September 5

Status: deployed to all three apps. Volume export completed and independently counted in Snov.io; both production generation-to-draft smoke tests passed on September 5.

## Release Boundaries

User authorized completing all stages, confirmed DAH Subscription / East US 2 / the three existing apps, signed in directly, and explicitly requested maximum Luna capacity. No outreach is launched by these tests. Existing customer jobs/campaigns and infrastructure/RBAC are not modified for testing. Secrets are not copied between apps or exposed.

## Current Candidates

| Worktree | Full Backend Tests | Actual SDK Functions | Browser |
| --- | --- | --- | --- |
| EmailMVP test bed | 411 passed | 62 | live and mocked desktop/mobile |
| EmailMVP-cloudware | 378 passed | 60 | mocked desktop1440/mobile390 and live mobile smoke |
| EmailMVP-main / Reliance | 380 passed | 60 | mocked desktop1440/mobile390 and live mobile smoke |

JavaScript syntax, editor diagnostics and git diff checks pass in all worktrees. Production logos load and no horizontal overflow was found. Test-bed dashboard, learning and delegation remain absent from production. Reliance's existing NRS prompt and unrelated data-store edit are preserved.

All three Azure validation scopes passed CLI/auth/Bicep/ARM/what-if checks with zero infrastructure changes. Target Functions are Running; managed identities retain their existing Blob/Queue/Table data permissions. No applicable policy assignments were returned. This validates deployment scope, not application behavior.

## New Hardening

- Per-app REST budget capped at 20 requests/minute, atomically paced across workers and keyed by client ID rather than rotating secret. Now deployed to all three apps, their combined configured REST budget is 60 requests/minute without granting cross-storage access. This is a conservative static allocation, not dynamic capacity sharing; third-party traffic outside these apps is not coordinated. Large exports still take time: 1000 leads require roughly 100 minutes of request budget in one app before setup, competing requests and retries.
- Every outbound REST attempt, including connection validation, uses the account budget. Async account reads and connection validation run off the event loop. HTTP 429 during connection does not falsely report invalid credentials.
- Explicit reconciliation reads Snov.io and resumes only an exact list, inactive draft, or uniquely confirmed recipient. An absent prospect requires a second explicit confirmation, disables duplicate creation for that row, and verifies membership after the write. Other-list contacts and multiple matches stay blocked. Uncertain list/campaign creates are not automatically repeated.
- Fresh template metadata is read for listing/selection, preventing another worker's cached publication state from hiding a new template or exposing an archived one. Existing jobs retain immutable prompt snapshots.
- Preflight verifies job ownership before reading its CSV.

## Live Test-Bed Evidence

- Authenticated admin, saved Snov.io credentials, valid sender and required custom fields verified through ordinary app APIs.
- Prior two-lead generation-to-Snov.io draft: completed, both content steps written, no launch.
- Prior 21-lead export: completed with 21 actual list members, crossing the 20-row delivery boundary.
- Duplicate submissions for the current 1001-lead export both returned operation `117e18c3f03043b08f5bffb6d94305be` in 1.6 seconds total.
- Worker restart via code deployment preserved completed rows. At 348 processed rows the worker stopped at an uncertain write, exposing a missing absent-prospect recovery path; that path was fixed, regression-tested, deployed, and then verified live. See Volume Export below. The restart was not a seamless automatic recovery and must not be described as one.
- Two concurrent one-lead exports completed independently while the large export ran: jobs `9627519e-4306-49c8-b873-92a4a842f40c` and `b7f6d62d-070d-4eb1-b562-6bb3f78fb4a6`, lists `40956680` and `40956681`.
- Options request took 12.4 seconds under REST throttling while four status requests returned in 0.4-1.9 seconds after the nonblocking handler fix.
- Template lifecycle `qa_lifecycle_c8f93c01`: unpublished save 201; publish 200; all six subsequent requests showed it; archive 200; all six subsequent requests hid it after the new worker was serving. The synthetic template remains archived.
- Failed-lead repair on job `1d6442f7-be19-488d-9f9b-c811a2cadc2a`: exactly one failed lead regenerated; the other lead's parsed CSV values were identical before/after; final failedLeads=0.

### Volume Generation

Job `ba69619e-d1f0-47a8-a46f-5515352cb50b`, Luna, 501 synthetic leads and 1002 emails.

- Started 2026-09-05 04:41:12 UTC; completed 04:51:28 UTC, about 10 minutes 16 seconds.
- 501 successful leads, zero failed leads.
- Downloaded CSV parsed with the application's own parser: 501 data rows, two touch pairs, 1002 complete emails, zero invalid/placeholder rows, 501 completed markers.
- Actual Review UI rendered 501 lead entries and 1002 emails, with no failed-generation repair action.

### Volume Export (Passed)

Job `0459526b-ffa7-4b53-8e15-498b2fb156da`, operation `117e18c3f03043b08f5bffb6d94305be`, dedicated list `40956584`, 1001 fictional recipients, started 04:23:14 UTC. Uses deterministic two-touch drafts so transport reliability is measured separately from generation.

One transient failed lookup/request was recorded at zero-based row 245. The controlled restart later left the operation in needs_review at 348 processed rows. Snov.io reported no prospect for zero-based row 348 (display row 349), so the original conservative reconciliation correctly refused to replay it.

The absent-prospect path was then implemented and deployed as `d4df8196-d111-4a11-a5e0-780fcef250a2`. A read-only check returned 409 with `missing_recipient_confirmation`; explicit confirmation returned 202 under the original operation. The recovered write used `createDuplicates=false`, and target-list membership was verified. The operation subsequently reported 352 successful rows, zero failures, including recovery of the earlier transient row; the last direct report showed 355 successful rows and no failures. Previously completed rows and the original list were retained.

Browser automation interruptions delayed observation, but no replacement job was started. On September 5 at 11:51:02 UTC, the original operation reported **completed, 1001 processed, 1001 added, zero failed, zero blocked and zero duplicates**. A separate Snov.io options read confirmed **1001 contacts in list 40956584**. The long elapsed wall time includes deliberate restart testing, a paused uncertain-write investigation and browser interruptions; it is not a steady-state throughput benchmark.

### Production Smoke Tests (Passed)

| App | Generation Job | Operation | Snov.io List | Snov.io Draft |
| --- | --- | --- | --- | --- |
| Cloudware | 25385aed-ef5e-47d3-b4a5-2fbef1d08d60 | c7597eeeb49f42aaa3139beb7ddf8adf | 40962164 | 3135482 |
| Reliance | 4388ded7-4663-4652-9a97-4c2ac2b086f3 | 61798ec2574046bc810302251a0bc46e | 40962177 | 3135484 |

Each app: authenticated admin 200; unknown-job status 404; live builder returned two valid emails with `gpt-5.6-luna-2026-07-09`; Responses Copilot called list_templates successfully without writes; one synthetic lead generated two emails with zero failed leads; publication completed with one added prospect and both content steps written. Both actual Snov.io lists independently returned one contact. Review rendered both emails and one lead. Live mobile layouts retained branding and no horizontal overflow; test-bed-only dashboard/learning/delegation remained absent.

The first options requests during each code/settings worker refresh returned a transient empty 500 response. Subsequent requests succeeded, no application exceptions were returned by the bounded post-deployment queries, and completed smoke tests used the refreshed Luna-serving workers. The initial pre-refresh mini response was not counted as evidence of Luna routing. Function metadata can lag serving routes during refresh; runtime behavior was checked directly.

No campaign was launched. Synthetic draft/list artifacts are intentionally retained for audit, not destructively cleaned up.

Independent campaign-state follow-up: Cloudware's campaign list returned draft3135482 as `Draft`. Reliance's legacy campaign-list response did not include new draft3135484 during the immediate follow-up checks, although its list count was correct. The completed REST worker had fetched that campaign directly and required `new`/`draft` before writing each email step.

Reliance OAuth follow-up on September 5: after the user connected Snov.io Copilot, `/api/snovio/mcp/status` returned HTTP 200 with `connected=true`. A live `/api/copilot/chat` read-only test returned HTTP 200 in 8.62 seconds with `snovioConnected=true`. The trace completed `app__search_snovio_tools`, `app__get_snovio_tool_schema`, and `app__execute_snovio_tool`; no confirmation actions were returned. Copilot retrieved campaign **3135484**, title **QA Reliance draft 4388ded7**, status **new**, prospect list **40962177**, and **two email steps**. These values match the previously completed REST publication. The earlier OAuth/direct-campaign-lookup blocker is resolved. This verifies that read-only workflow, not every MCP capability or the legacy campaign-list visibility behavior. No campaign changes or outreach were requested or performed.

## Luna Evaluation

Existing account `azai-emailmvp-foundry-dah2`, DataZoneStandard, `gpt-5.6-luna` version `2026-07-09`, Microsoft.DefaultV2, NoAutoUpgrade. User-requested maximum capacity **667**, verified by Azure as **667 RPM and 667000 TPM**, shared across the apps. Original mini deployment remains available for rollback. All three apps now use Luna for generation/builder/Copilot and Responses API for Copilot; the general mapping/default setting remains mini. `BATCH_SIZE=10` and the per-app REST budget are retained.

| Live Check | Result | Wall Time | Tokens In / Out |
| --- | --- | --- | --- |
| Mini two-touch admin brief | valid | 3.54 s | 244 / 135 |
| Luna same two-touch brief | valid | 5.10 s | 244 / 170 |
| Luna four-touch English brief | valid | 4.28 s | 250 / 344 |
| Luna eight-touch French brief | valid | 7.25 s | 245 / 615 |
| Luna Responses list_templates tool | correct count, no writes | 5.03 s | not measured |
| Luna 3 templates x 2 leads | all completed, zero failures | 6-8 s per job | not measured |

Sample review found the requested language/count and no invented prices, discounts or guaranteed savings in those examples. This is not a guarantee of all marketing claims or send-readiness; human review remains required.

Official Azure pricing retrieved September 5: short-context Data Zone Luna $0.22 input / $1.32 output per million tokens; mini $0.83 / $4.95. The measured two-touch calls estimate about $0.000278 Luna vs $0.000871 mini before taxes/contract pricing. This is a small-sample comparison, not a monthly bill forecast.

Source: https://azure.microsoft.com/en-us/pricing/details/azure-openai/

## Deployment Records

- Test-bed initial September 5 hardening: `97ae2b96-984c-4799-8dfe-3d9c1403ef6b`.
- Test-bed async reads/template freshness: `cd42f86c-5c7d-4b61-a8d2-ad3f1d0e88f4`; host started 05:06:14 UTC.
- Final test-bed connection budget and absent-prospect recovery: `d4df8196-d111-4a11-a5e0-780fcef250a2`, deployed 09:56:42 UTC; matching frontend deployed. Rechecked as the active backend around 11:05 UTC.
- Cloudware rollback: `ed4f1c1e-459c-4a7e-80b3-68c3b4d1b25f`.
- Reliance rollback: `d64fe513-f522-4e66-bcd1-7842c9e0512f`.
- Production frontend rollback archives: `.azure/pre-bulk-frontend-rollback.zip` in each worktree.
- Cloudware final backend: `7b98e0fb-365f-44e5-9ab1-ad75481a2695`, deployed 11:53:02 UTC; matching frontend deployed.
- Reliance final backend: `e684516e-ef58-4f89-8783-38cafcba2ba8`, deployed 11:59:24 UTC; matching frontend deployed.
- Both production Function Apps rechecked Running with the final active deployment IDs and required storage roles intact.
- All three apps have generation/builder/Copilot routed to `emailmvp-luna-canary`, `AZURE_OPENAI_COPILOT_USE_RESPONSES=true`, and `AZURE_OPENAI_DEPLOYMENT=gpt-5.4-mini` retained for mapping/default compatibility. Per-feature rollback is to point the three deployment overrides back to mini and disable Responses if restoring the previous code.

Final recovery-corrected production package hashes (deployed runtime content verified byte-for-byte before rollout):
- Cloudware: 570B895703591285715AAE20B67FDD4838EB0E442743912AB3A80FD974FA0760
- Reliance: 46CC1E44DC7BD28F5F76DCD23DAE0B3B42D52E56F6EEC2FDEF70238D2E87F87C

All earlier candidate package hashes are superseded. Production deployment was sequential: Cloudware's completed live draft smoke test preceded Reliance deployment. Worktree ports remain uncommitted, with the unrelated Reliance data-store change preserved. No new branches, identity/permission changes or infrastructure replacements were made.

## Operational Caveats

The agreed release gates have passed. These tests do not establish zero defects or unlimited concurrency. Snov.io's account request limit still governs throughput; the fix is resumability and truthful progress, not bypassing that limit. Multiple/missing uncertain list or campaign matches still require human review. Actual sending, mailbox deliverability and campaign launch were intentionally not tested. Users should review generated claims and drafts before launching in Snov.io. Monitor subsequent real-user traffic against the saved rollback versions.