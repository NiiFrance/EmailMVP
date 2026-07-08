# Azure Final Teardown Report — Remaining Resource Groups

**Date:** May 29, 2026
**Subscription:** EnochFrance Sponsorship (`1026bf75-8146-43b4-8f2c-32e69ef52837`)
**Tenant/Directory:** Cloudware Limited (cloudware.africa)
**Reason:** Subscription scheduled for termination — remove all remaining (non-EmailMVP) resource groups for a fully empty subscription.
**Scope:** This report covers the teardown of the resource groups that remained after the EmailMVP teardown (see `AZURE_TEARDOWN_REPORT_2026-05-29.md`).

---

## 1. Summary

| Item | Result |
|---|---|
| Resource groups deleted | 3 |
| Resource groups already gone | 1 (`rg-project-x1-dev`, empty — auto-removed earlier) |
| Resources destroyed | ~5 |
| Cognitive Services accounts purged (permanent) | 1 (`EnochClaude`) |
| Resource locks encountered | 0 |
| Resource groups remaining in subscription | 0 (fully empty) |

---

## 2. Pre-flight checks

- **Resource locks:** Checked via `az lock list` — none found.
- **Deletion method:** `az group delete --yes --no-wait` issued in parallel, then polled via `az group exists` until each returned `false`.

---

## 3. Resource groups deleted

| Resource Group | Contents | Status |
|---|---|---|
| `NetworkWatcherRG` | `NetworkWatcher_eastus`, `NetworkWatcher_eastus2` (Azure auto-managed network watchers) | Deleted |
| `rg-tenant-id-finder` | `tenant-id-finder-app` (Web App) + `plan-tenant-id-finder` (App Service Plan) | Deleted |
| `TestFoundary` | `EnochClaude` Cognitive Services account + `proj-claude` project | Deleted |
| `rg-project-x1-dev` | Empty (no resources) | Already removed prior to this step |

---

## 4. Resources destroyed (≈5)

- **1 Cognitive Services account:** `EnochClaude` (+ child project `proj-claude`) — soft-deleted then purged (see §5)
- **1 Web App:** `tenant-id-finder-app`
- **1 App Service Plan:** `plan-tenant-id-finder`
- **2 Network Watchers:** `NetworkWatcher_eastus`, `NetworkWatcher_eastus2`

---

## 5. Cognitive Services purge (permanent)

Cognitive Services accounts have soft-delete protection. After deleting `TestFoundary`, the `EnochClaude` account remained recoverable and was **permanently purged** via:

```
az cognitiveservices account purge --name EnochClaude --resource-group TestFoundary --location eastus2
```

Verified absent from `az cognitiveservices account list-deleted` after purge.

---

## 6. Post-teardown state

- **Resource groups in subscription:** 0 — the subscription is completely empty.
- **Soft-deleted Key Vaults remaining (unrelated, not EmailMVP):**
  - `kv-enoch422919971385626` (scheduled purge ~2026-07-03)
  - `azkv6zxsyskrr4wku` (scheduled purge ~2026-06-07)

  These predate this effort and are unrelated to EmailMVP. They will be removed automatically when the subscription terminates, or can be purged on request.

---

## 7. Notes

- **NetworkWatcherRG** is normally auto-recreated by Azure when Network Watcher is enabled in a region; since the subscription is being terminated, no recreation is expected.
- **Recoverability:** Deleted resource groups and the purged Cognitive Services account are **not** recoverable.
- Combined with the EmailMVP teardown, the subscription now holds **no active resources**, ready for termination.

---

*Report generated as part of the subscription decommissioning effort.*
