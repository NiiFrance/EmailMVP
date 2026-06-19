# EmailMVP Azure Teardown Report

**Date:** May 29, 2026
**Subscription:** EnochFrance Sponsorship (`1026bf75-8146-43b4-8f2c-32e69ef52837`)
**Tenant/Directory:** Cloudware Limited (cloudware.africa)
**Reason:** Azure subscription scheduled for termination — decommission all EmailMVP infrastructure.
**Action taken:** Full teardown of all 4 EmailMVP resource groups + purge of associated Key Vaults.

---

## 1. Summary

| Item | Result |
|---|---|
| Resource groups deleted | 4 (+1 managed RG auto-removed) |
| Resources destroyed | ~33 |
| Key Vaults purged (permanent) | 3 |
| Resource locks encountered | 0 |
| Source code lost | None (all in GitHub `NiiFrance/EmailMVP`) |
| Non-EmailMVP resources touched | None |

---

## 2. Pre-flight checks

- **Resource locks:** Checked subscription-wide via `az lock list` — none found (no `CanNotDelete` or `ReadOnly` locks).
- **Deletion method:** `az group delete --yes --no-wait` issued in parallel for all 4 groups, then polled via `az group exists` until each returned `false`.

---

## 3. Resource groups deleted

| Resource Group | Environment | Status |
|---|---|---|
| `rg-emailmvp-eastus2` | Original / main | Deleted |
| `rg-emailmvp-stg-eastus2` | Staging | Deleted |
| `rg-emailmvp-cloudware-eastus2` | Cloudware | Deleted |
| `rg-emailmvp-cloudware-snovio-eastus2` | Snov.io test (latest deploy) | Deleted |
| `ai_appi-emailmvp-stg_b0a0b1ad-...-managed` | Auto-managed (staging App Insights workspace) | Auto-removed with staging App Insights |

---

## 4. Resources destroyed (≈33)

Across the four resource groups:

- **5 Static Web Apps:** `azswa4homfpggr6476`, `azswa-emailmvp-stg-6476`, `azswazcn6oizgufwbo`, `azswa53x2buxkbqbqa`
- **4 Function Apps:** `azfn4homfpggr6476`, `azfnemailmvpstg6476`, `azfnzcn6oizgufwbo`, `azfn53x2buxkbqbqa`
- **5 App Service Plans (serverFarms):** `azplan4homfpggr6476`, `azplan-emailmvp-stg`, `azplanzcn6oizgufwbo`, `azplan53x2buxkbqbqa`
- **5 Storage accounts:** `azst4homfpggr6476`, `azstemailmvpstg6476`, `azstzcn6oizgufwbo`, `azst53x2buxkbqbqa`
- **3 Key Vaults:** `azkv4homfpggr6476`, `azkvzcn6oizgufwbo`, `azkv53x2buxkbqbqa` (soft-deleted then purged — see §5)
- **4 Application Insights components:** `azai4homfpggr6476`, `appi-emailmvp-stg`, `azaizcn6oizgufwbo`, `azai53x2buxkbqbqa`
- **4 Log Analytics workspaces:** `azla4homfpggr6476`, `managed-appi-emailmvp-stg-ws`, `azlazcn6oizgufwbo`, `azla53x2buxkbqbqa`
- **3 User-assigned Managed Identities:** `azid4homfpggr6476`, `azidzcn6oizgufwbo`, `azid53x2buxkbqbqa`
- **1 Smart Detection action group:** `Application Insights Smart Detection`

---

## 5. Key Vault purge (permanent)

Key Vaults have a 90-day soft-delete by default. After resource-group deletion they remained recoverable; all 3 EmailMVP vaults were then **permanently purged** via `az keyvault purge`.

| Vault | Soft-deleted | Purged |
|---|---|---|
| `azkv4homfpggr6476` | 2026-05-29 | Purged (permanent) |
| `azkvzcn6oizgufwbo` | 2026-05-29 | Purged (permanent) |
| `azkv53x2buxkbqbqa` | 2026-05-29 | Purged (permanent) |

Verified absent from `az keyvault list-deleted` after purge.

> Two older soft-deleted vaults remain and are **unrelated** to EmailMVP:
> `kv-enoch422919971385626` (purge ~2026-07-03), `azkv6zxsyskrr4wku` (purge ~2026-06-07). Left untouched.

---

## 6. Resources left untouched (not EmailMVP)

| Resource Group | What it is | Action |
|---|---|---|
| `NetworkWatcherRG` | Azure auto-managed networking (NetworkWatcher_eastus / _eastus2) | Left in place |
| `TestFoundary` | `EnochClaude` Cognitive Services account + `proj-claude` project | Left in place |
| `rg-tenant-id-finder` | `tenant-id-finder-app` web app + plan | Left in place |
| `rg-project-x1-dev` | Empty resource group | Left in place |

---

## 7. Post-teardown state

Remaining resource groups in the subscription after teardown:

- `NetworkWatcherRG`
- `TestFoundary`
- `rg-project-x1-dev`
- `rg-tenant-id-finder`

All EmailMVP infrastructure (compute, storage, secrets, monitoring) has been fully removed and is non-recoverable.

---

## 8. Notes & recovery

- **Source code:** Safe in GitHub — repo `NiiFrance/EmailMVP`. Infrastructure can be redeployed from IaC/scripts if ever needed.
- **Recoverability:** Resource groups and purged Key Vaults are **not** recoverable. Redeploy from source if the project resumes.
- **Cost impact:** All billable EmailMVP compute, storage, and monitoring resources are gone; no further charges from these resources.

---

*Report generated as part of the subscription decommissioning effort.*
