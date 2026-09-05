# Onboarding and Capacity: Local Implementation Status

Status: **Help-only test-bed pilot deployed. Capacity acceptance gate failed.**

User approved the separate pilot and confirmed the existing DAH Subscription /
East US 2 target. Only the test bed was updated. Neither production worktree was
ported or deployed for this release. Existing release changes were preserved.
No paid model calls, Snov.io publication writes or outreach launches were made in
this implementation/pilot. Real-service test spend is USD0 against the approved
USD10 allowance.

## Source Control Checkpoint (2026-09-05)

- Branch: `checkpoint/help-pilot-2026-09-05`, based on test-bed commit `f65dd35`.
- Runtime/source commit: `3a836fe`. Earlier bulk-publication fixes, Help and the
  disabled V2 scheduler share runtime files and are preserved as one buildable
  checkpoint. Release evidence is recorded in a separate documentation commit.
- Fresh checkpoint validation: 463 backend tests and 16 browser scenarios passed;
  staged Gitleaks 8.30.1 scan found no leaks. The scanner archive was checked
  against the official release SHA256. These checks do not prove zero bugs.
- The fictional Help CSV is included in Git. Local settings, chat history,
  rollback archives, pilot screenshots, dependencies and generated test output
  remain excluded. They were not deleted from the workstation.
- No GitHub Actions configuration exists in the three deployment branches at
  this checkpoint. External webhook configuration could not be inspected through
  the unsigned-in GitHub CLI. The checkpoint uses its own branch; no deployment
  branch is updated, no merge is performed, and no deployment command is run.
- This is a preservation/review checkpoint, not production-release approval.
  The representative-user Help pilot and capacity gates below remain outstanding.

## Live Pilot (2026-09-05)

- URL: https://ashy-ocean-0a8e5f60f.7.azurestaticapps.net/
- Backend deployment: `9ed71419-5481-4b8d-8f97-e2a5e1e1ee4e`, status4, remote
  build complete; matching frontend deployed including the search, Escape and
  background-tab invitation fixes.
- Live flags: `ONBOARDING_ENABLED=true`, `ONBOARDING_AUTO_INVITES=true`,
  `GENERATION_SCHEDULER_V2=false`, `GENERATION_V2_DRAIN_ENABLED=false`.
- Fresh Azure validation: all five CLI/auth/build/validate/what-if checks pass,
  zero create/modify/delete, no applicable policy assignments returned. Existing
  identity and storage-scoped Table/Blob/Queue roles verified; no RBAC changes.
- Normal authenticated SWA session: onboarding GET200, all four admin guides,
  manual start/pause persisted, two concurrent start attempts returned200/409,
  campaign resume context unchanged. No customer job content was changed.
- Live Help search matches OAuth and recovery; Escape closes search and restores
  focus. Tested mobile dialog fits; logo loaded; axe found no critical/serious
  violations in that dialog. Screenshot: `.azure/help-pilot-mobile.png`.
- Invitation flag confirmed true via both Azure settings and live API. The editor
  browser reports `document.hidden=true` during automation, so a natural visible
  live invitation/dismiss/refresh cycle was not observed. Hidden tabs do not
  consume invitations. The visible-tab lifecycle is covered by local browser
  tests; representative pilot users must confirm it in normal use.
- Deployment initially served the old host index and returned404 on the new
  route. Host restart resolved the live route; another restart applied the
  invitation flag. Trigger synchronization requested after activation. Azure's
  function-list API still returned the old count during verification; the real
  SDK registers68 locally and the deployed onboarding route was tested directly.
  Resource Health reports Available. AppLens returned401; no permissions changed.
- Rollback backend: `d4df8196-d111-4a11-a5e0-780fcef250a2`. Previous frontend:
  `.azure/help-pilot-frontend-rollback.json.gz`, SHA256
  `e7c3bfb3f21acc39261419f2732b3462bd00f3823d8ee348d7aafa2a0936126b`.
- Next gate: 5-10 representative users including an administrator and mobile
  users, with one business day of feedback before considering production rollout.

## Implemented

- Account-scoped onboarding in a separate Azure Table record, with ETag updates,
  two optional invitation visits, inactivity windows, opt-out, replay, ordered
  progress, active-tab leases, and server-side admin authorization.
- Permanent local searchable Help, fictional sample CSV, and four guides:
  first campaign, Snov.io draft preparation, recovery, and admin template builder.
- Driver.js 1.3.6 is self-hosted with its MIT license. Guide navigation never
  performs generation, connection, export or launch calls. Success events come
  from existing application workflows; long-running steps save and pause.
- Keyboard-accessible template/navigation selection, template publication badges,
  single-flight generation polling, and reopening running jobs from history.
- Experimental V2 generation: one outstanding job per owner, 100-job admission
  ceiling, immutable config references, fair reservations, rolling RPM/TPM limits,
  durable throttling timers, per-row leased checkpoints, periodic continue-as-new,
  streamed CSV output, repair preservation, and dispatch recovery.

## Flags and Rollback

| Setting | Default | Behavior |
| --- | --- | --- |
| `ONBOARDING_ENABLED` | `true` | Enable persisted manual tours; Help remains local if disabled/unavailable. |
| `ONBOARDING_AUTO_INVITES` | `false` | Automatic invitations remain off pending release gates. |
| `GENERATION_SCHEDULER_V2` | `false` | Existing generation is unchanged until explicitly enabled. |
| `GENERATION_V2_DRAIN_ENABLED` | `false` | Run V2 recovery after disabling new V2 admissions. Leave false for a Help-only pilot with no V2 work. |
| `GENERATION_ADMISSIONS_PAUSED` | `false` | Stop new generation/repair from UI and Copilot; accepted jobs still drain. |

Never remove V2 handlers or its recovery timer while V2 jobs exist. During a
scheduler rollback, pause admissions first and retain the V2 worker package until
accepted jobs reach terminal states; enable `GENERATION_V2_DRAIN_ENABLED` before
disabling V2 admissions. Simply disabling V2 sends new work through
the legacy path and does not itself pause generation.

V2 currently supports up to 10 MB normalized input and 10,000 leads per job.
Allocation is 180 RPM / 180,000 TPM per app, conservatively reserving the full
requested output budget plus a UTF-8 prompt upper bound. Across three apps that
leaves 127 RPM / 127,000 TPM of the previously verified shared model quota.
Interactive calls do not yet have an enforced shared allocation. These settings
are an experimental safety envelope, not a throughput commitment.

## Verified Locally

- Final full backend regression: **463 tests passed**, including the
  admission-pause and Help-only timer-isolation guards.
- Browser: **16 Chromium scenarios passed** with pinned Playwright 1.58.2 and
  axe-core 4.11.1. Includes all four tours, normal write confirmations, no
  unintended business requests, failures, missing anchors, explicit generation,
  running-job recovery, unpublished status, background-to-visible invitations,
  recovery keyword search, Escape dismissal, and Help widths 320/390/768/1440.
- No critical/serious axe findings in the tested Help dialog and mobile spotlight.
  Mobile screenshots inspected. This is not a screen-reader or all-browser claim.
- Real Azure SDK: 68 functions registered, including the five V2 functions.
- Separate Azurite integration: 3 tests passed using real Table ETags, Blob
  leases, Azure HttpRequest, and the OpenAI SDK against a loopback synthetic
  provider. Verified account isolation, unchanged campaign resume context,
  idempotent admission, streamed output, and one model call for repeated activity.
- Scheduler-only accelerated simulation: 100 accounts x 1,000 leads, 100,000
  unique completions, no loss/duplicates, maximum lead-count gap 2, first turn
  within 259 virtual seconds, and preserved rolling quota ceilings through an
  injected one-hour shared cooldown. Runtime 72.36 seconds.

The simulation did **not** generate 400,000 email bodies, execute Durable workers,
load the public APIs, or simulate Snov.io exports. Four touches would correspond
to 400,000 emails; that arithmetic is not an output validation.

## Blocking Capacity Result

With an assumed 5,000-token reservation per lead in one app, the simulation took
**84.59 virtual hours**, not several hours. The token-budget lower bound at the
current per-app allocation is about 46.3 hours, before scheduling overhead,
provider latency, retries, or interactive work. Even the entire previously
verified 667,000 TPM shared deployment would need about 12.5 hours for that same
reservation assumption.

Actual prompts, output caps, Azure token-estimation behavior and quality must be
measured before choosing a less conservative budget. Queue-aware backoff reduced
excessive reservation traffic but still adds scheduling delay. More work is
needed before offering any 100-user completion-time promise. Increasing paid
capacity or changing the approved latency envelope requires a separate decision.

## Unverified Gates

- Full local Durable host/queue execution: installed Core Tools 4.13.0 reports its
  version but `func host start --help` and `func start --help` fail with
  "Exception has been thrown by the target of an invocation." Real-SDK tests do
  not replace a running Functions host.
- Realistic 10/25/50/100-user API ramp and 30-minute soak, complete 100x1000
  synthetic provider output run, large-body/12-touch and 2,000-lead worker cases,
  Snov.io account scenarios, worker restart and network-fault injection.
- Additional real Entra/SWA identities beyond the authenticated admin smoke,
  pilot with 5-10 representative users, capacity canary within USD10, exact
  token/quality calibration, and production telemetry.
- Browser cross-tab persistence uses real backend concurrency tests and mocked
  browser state separately; full multi-device, role-downgrade, screen-reader,
  zoom/virtual-keyboard, and cross-browser checks remain.
- Cloudware/Reliance ports and their fresh Azure validation/rollback packages,
  representative pilot feedback, and staged production rollout. Test-bed
  deployment is complete as recorded above.

## Local Commands

Run backend and real-SDK integration tests in **separate Python processes** because
the backend unit suite injects Azure module stubs.

```powershell
api\.venv\Scripts\python -m pytest api\tests -q
npm --prefix tests\browser ci
npm --prefix tests\browser test -- --reporter=line
azurite --location tests\integration\.azurite --blobHost 127.0.0.1 --queueHost 127.0.0.1 --tableHost 127.0.0.1 --silent --disableTelemetry --skipApiVersionCheck
api\.venv\Scripts\python -m pytest tests\integration\test_local_storage.py -q
api\.venv\Scripts\python -m pytest tests\integration\test_capacity_simulation.py -q -s
```

The Azurite tests use the emulator's public development configuration, never
production credentials. Browser fixtures intercept app APIs with fictional data;
they are not authenticated live tests.