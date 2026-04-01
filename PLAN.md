# EmailMVP — Design Plan & Implementation History

> This document captures the original plan, design decisions, and implementation journey for the EmailMVP cold email generation platform built for Reliance Infosystems.

---

## 1. Problem Statement

Reliance Infosystems is a Microsoft Solutions Partner that helps organizations manage, renew, upgrade, and optimize their Microsoft licensing. Their sales team needs to send personalized cold email sequences to leads whose Microsoft licenses are up for renewal.

**The manual process:**
- Sales reps receive a CSV export of leads (from LinkedIn Helper / Microsoft partner data)
- Each lead has demographic data, license info, and engagement objectives
- Sales reps manually write 8-touch email sequences per lead
- This is time-consuming and inconsistent across the team

**The solution:**
- Upload a CSV → AI generates 8 personalized cold emails per lead → Download enriched CSV
- Fully automated, consistent tone, personalized to each lead's context

---

## 2. Requirements

### Functional
- Upload CSV or Excel (.xlsx) files containing lead data
- Automatically detect required columns via fuzzy matching + LLM fallback
- Generate 8 cold emails per lead (Subject + Body for each touch)
- Append 16 output columns at the end of the original data
- Return enriched CSV for download
- Show real-time processing progress (processed X of Y leads)
- Handle files with any number of leads (tested up to 2,038)

### Non-Functional
- Process leads concurrently for speed (100 concurrent per batch)
- Handle API rate limits gracefully (auto-retry on 429, 5000 TPM capacity)
- UTF-8 compatible output that opens correctly in Excel
- No specific license types or seat counts in email copy (privacy concern)
- ASCII-only characters to prevent encoding issues
- Deployed on Azure with proper security (Managed Identity, Key Vault, RBAC)
- Accept arbitrary column ordering (no rigid CSV layout required)

---

## 3. Architecture Design

### Pattern: Serverless Batch Processing

Chose **Azure Durable Functions (fan-out/fan-in)** because:
- No need for always-on compute — pay per execution
- Built-in orchestration for concurrent processing
- Built-in retry policies and error handling
- Native integration with Azure Blob Storage
- 2-hour function timeout on Premium EP1 plan

### Why NOT Microservices / Queue-Based
- Overkill for a single-purpose batch processor
- No need for inter-service communication
- No need for independent scaling of components
- Durable Functions handle concurrency internally

### Component Breakdown

| Component | Technology | Rationale |
|---|---|---|
| Frontend | Azure Static Web App (vanilla HTML/CSS/JS) | No build step, fast to deploy, free tier available |
| Backend | Azure Functions (Python 3.11, Durable) | Serverless, native orchestration, Python for AI SDK |
| AI Model | Azure OpenAI GPT 5.3 | Best available model with quota in subscription |
| Storage | Azure Blob Storage | Simple object storage for CSV files |
| Secrets | Azure Key Vault | Industry standard for secret management |
| Auth | Managed Identity + RBAC | Passwordless, no credentials in code |
| Monitoring | Application Insights | Native Azure monitoring, integrated with Functions |
| IaC | Bicep | Azure-native, simpler than ARM templates |

---

## 4. Data Flow

```
1. User uploads CSV or Excel (.xlsx) via browser
2. Static Web App forwards POST /api/upload to Function App
3. upload_csv function:
   - Parses the file (CSV or Excel via openpyxl)
   - Runs smart column detection (fuzzy match → LLM fallback → reject if unresolved)
   - Converts Excel to CSV if needed
   - Stores CSV in Blob Storage (csv-input container)
   - Passes job_id + column_map to orchestrator
   - Returns job ID to frontend
4. Frontend polls GET /api/status/{jobId} every 5 seconds
5. orchestrate_emails orchestrator:
   a. Calls extract_leads_activity with column_map → parses CSV into lead dictionaries
   b. Batches leads into groups of 100
   c. For each batch: fans out process_lead_activity calls
   d. Updates custom_status with processedLeads/totalLeads after each batch
   e. 2-second delay between batches (rate limit protection)
   f. Collects all results
   g. Calls assemble_csv_activity → merges results into enriched CSV
   h. Uploads enriched CSV to Blob Storage (csv-output container)
6. Frontend shows real-time progress bar ("Processed X of Y leads")
7. User clicks Download → GET /api/download/{jobId} → returns enriched CSV
```

---

## 5. Email Generation Strategy

### 8-Touch Sequence

| Touch | Purpose | Strategy |
|---|---|---|
| 1. Introduction | First contact | Warm, non-pushy, positions Reliance as licensing advisor |
| 2. Diagnostic | Spark reflection | Asks about renewal pain points (compliance, over-licensing) |
| 3. Benefit | Show value | Cost savings, compliance, streamlined procurement |
| 4. Social Proof | Build trust | Anonymized success stories from similar orgs |
| 5. Authority | Establish credibility | Microsoft competencies, certifications, expertise |
| 6. Promo Canvas | Create opportunity | Microsoft promotions, incentives, programs |
| 7. Risk Reversal | Remove objections | No-obligation audit, seamless migration, SLAs |
| 8. Danger/Close | Create urgency | Renewal deadlines, compliance risk, soft CTA |

### Prompt Engineering Constraints
- Max 7-word subject lines
- 200-260 word bodies
- Plain ASCII only (no em dashes, curly quotes)
- No URLs, links, or signature blocks
- No specific license types or seat counts (privacy)
- Address recipient by first name
- At least 3 paragraphs per body
- Output: pure JSON array, no markdown fences

---

## 6. Implementation History

### Phase 1: Initial Build
- Created all 11 project files (api/, frontend/, infra/)
- Built with Anthropic SDK targeting Claude Opus 4.6
- Wrote 40 unit tests across 3 test files
- Deployed Azure infrastructure via Bicep IaC

### Phase 2: Claude Model — Blocked
- Attempted to deploy Claude Opus 4.6 on Azure AI Services
- Discovered `modelProviderData` field requirement (industry, organizationName, countryCode)
- Solved API version issue: `2026-01-15-preview` accepts the fields
- **BLOCKED:** All Claude models have 0 quota in the subscription
- Verified 6 Claude models available in East US 2 but none deployable:
  - claude-opus-4-6, claude-sonnet-4-6, claude-opus-4-5
  - claude-sonnet-4-5, claude-opus-4-1, claude-haiku-4-5

### Phase 3: Model Switch to GPT 5.3
- Migrated from Anthropic SDK to OpenAI `AzureOpenAI` SDK
- Deployed `gpt-53-chat` (model: gpt-5.3-chat, version 2026-03-03, GlobalStandard)
- Three compatibility fixes required:
  1. `max_tokens` → `max_completion_tokens` (GPT 5.3 requirement)
  2. Added `--build-remote true` flag for ZIP deploy (dependency installation)
  3. Removed `temperature=0.7` (GPT 5.3 only supports default temperature)

### Phase 4: First Successful Run
- Processed FranceGame.csv end-to-end (17 leads)
- All leads generated successfully, CSV assembled (~283KB)

### Phase 5: Encoding Fix
- Problem: Garbled characters in output CSV (e.g., `I'm` instead of `I'm`)
- Root cause: UTF-8 without BOM + em dashes/curly quotes from model
- Fix 1: Changed `df.to_csv()` to use `encoding="utf-8-sig"` (BOM for Excel)
- Fix 2: Added ASCII-only constraint to system prompt
- Verified: 40/40 tests passing, redeployed, second run clean

### Phase 6: Prompt Fine-Tuning
- Problem: Emails mentioned specific license types (e.g., "Office 365 E3") and seat counts (e.g., "941 seats"), making recipients feel surveilled
- Fix: Added hard constraint forbidding specific SKU names and quantities
- Updated Touch 6 to reference "common enterprise licensing scenarios" instead of "lead's license type"
- Redeployed and verified with 17-lead run — zero errors

### Phase 7: Documentation & Architecture Diagram
- Generated architecture diagram using Python `diagrams` library with Azure icons
- Updated README.md with current architecture (GPT 5.3, not Claude)
- Created this PLAN.md for future reference

---

## 7. GPT 5.3 Known Constraints

| Constraint | Detail |
|---|---|
| `max_tokens` | Not supported. Use `max_completion_tokens` instead |
| `temperature` | Only default (1.0) supported. Custom values cause errors |
| API version | `2024-12-01-preview` |
| Rate limits | 5,000 TPM capacity (GlobalStandard, scaled from initial 10) |
| Deployment name | `gpt-53-chat` |
| Content filter | Custom `EmailMVP-Relaxed` policy (blocks HIGH severity only) |

---

## 8. Durable Functions Configuration

```json
{
  "maxConcurrentActivityFunctions": 100,
  "maxConcurrentOrchestratorFunctions": 5,
  "functionTimeout": "02:00:00"
}
```

- **Batch size:** 100 leads per batch (env var `BATCH_SIZE`)
- **Inter-batch delay:** 2 seconds
- **Max timeout:** 2 hours
- **Storage provider:** Azure Storage (default Durable task hub)

### Performance Benchmarks

| Leads | Batch Size | Concurrent | Capacity (TPM) | Time | Errors |
|---|---|---|---|---|---|
| 17 | 100 | 100 | 5,000 | ~2 min | 0 |
| 2,038 | 15 | 15 | 5,000 | ~4h 12m | 0 |
| 2,038 | 100 | 100 | 5,000 | **~55 min** | 0 |

The batch 15→100 upgrade achieved a **4.6x speedup** for 2,038 leads.

---

## 9. Security Model

| Layer | Mechanism |
|---|---|
| API Key storage | Azure Key Vault (secrets: `AzureOpenAIEndpoint`, `AzureOpenAIApiKey`) |
| Blob Storage auth | Managed Identity + RBAC (Storage Blob Data Contributor) |
| Key Vault auth | Managed Identity + RBAC (Key Vault Secrets User) |
| Function App identity | User-assigned Managed Identity (`azid4homfpggr6476`) |
| Network | No VNet integration (MVP scope) |
| Frontend | Azure Static Web App (no user auth — internal tool) |

---

## 10. Change Log

### March 29, 2026 — Excel Support & Smart Column Detection

**New Features:**
- **Excel (.xlsx) file upload** — Users can now upload `.xlsx` files alongside `.csv`. Excel files are parsed via `openpyxl` and converted to CSV at upload time.
- **Smart column detection** — A hybrid fuzzy matching + LLM fallback system (`column_mapper.py`) automatically identifies the 5 required columns regardless of naming or position:
  - Fuzzy matching uses keyword patterns (e.g., "first name", "firstname", "fname", "given name" all match `first_name`)
  - Disqualification rules prevent false positives (e.g., "organization_domain_1" won't match `organization`)
  - If fuzzy matching fails, GPT 5.3 resolves remaining fields
  - Files are rejected with a clear error if required columns can't be detected
- **Dynamic output positioning** — Output columns (Subject_Touch1 through Body_Touch8) are now appended at the end of the original data instead of hardcoded to column BW (index 74)
- **Column map passed through orchestrator** — The `column_map` dict flows from upload → orchestrator → extract_leads_activity, ensuring correct field extraction

**Files Changed:**
- `api/column_mapper.py` — NEW: Fuzzy matching + LLM fallback column detection
- `api/csv_processor.py` — Added `parse_excel()`, `parse_file()`, `dataframe_to_csv_bytes()`. Refactored `extract_lead_data()` and `extract_all_leads()` to accept optional `column_map`. Dynamic output positioning.
- `api/function_app.py` — Accept `.xlsx`, resolve columns at upload, convert Excel to CSV, pass `column_map` through orchestrator
- `api/requirements.txt` — Added `openpyxl`
- `frontend/index.html` — Accept `.csv,.xlsx`, updated descriptions
- `frontend/app.js` — Allow `.xlsx` in file validation
- `api/tests/test_column_mapper.py` — NEW: 23 tests for column detection
- `api/tests/test_csv_processor.py` — Updated for new signatures, added Excel and dynamic positioning tests

**Test Results:** 69/69 passed (31 csv_processor + 23 column_mapper + 15 prompt_templates)

**Verified:** End-to-end test with `FranceGame.xlsx` (17 leads, 74 columns) — all fuzzy-matched correctly, 0 errors, emails personalized.

### March 29, 2026 — UX Fixes

- **Double-dialog bug fix** — Clicking "Browse Files" opened the file picker twice because the click event bubbled from the `<label>` to the drop-zone's click handler. Fixed by checking `e.target.closest("label")` before calling `fileInput.click()`.
- **Pulse animation on progress bar** — While `processedLeads == 0` and the job is running, the progress bar shows a shimmer/pulse animation with "Preparing leads..." text so users know the system is working during the first batch.
- **Job summary on download screen** — The download section now displays total leads, elapsed time, and job ID instead of hiding them when processing completes.
- **Footer text** — Shortened from "Powered by Azure Foundry & Claude Opus 4.6 — Reliance Infosystems" to just "Reliance Infosystems".

### March 27-28, 2026 — Performance Optimization & Progress Bar

- **Batch size 15 → 100** and **concurrent activities 15 → 100** — 4.6x speedup (2,038 leads: 4h12m → 55 min)
- **Model capacity 10 → 5,000** — Eliminated 429 rate limit errors
- **Custom content filter** — `EmailMVP-Relaxed` policy (blocks HIGH only) eliminated content filter blocks
- **Real-time progress bar** — Orchestrator uses `context.set_custom_status()` to report `processedLeads/totalLeads/phase`, exposed in status API, displayed as accurate progress bar in frontend

---

## 11. Future Enhancements (Not Implemented)

These were discussed but intentionally deferred for the MVP:

- **User authentication** — Azure AD / Entra ID login for sales reps
- **Job history** — Store past runs in Cosmos DB or Table Storage
- **Claude model** — Switch to Claude Opus 4.6 if/when quota becomes available
- **GPT 5.4** — Only `gpt-5.4-mini` and `gpt-5.4-nano` available currently (no full 5.4)
- **RAG** — Retrieve past successful emails as few-shot examples
- **A/B testing** — Compare email variants across models
- **Webhook notifications** — Notify sales reps when processing completes
- **VNet integration** — Private endpoints for storage and Key Vault
- **CI/CD pipeline** — GitHub Actions for automated testing and deployment

---

## 12. Troubleshooting Reference

| Issue | Solution |
|---|---|
| `AnthropicFoundry` import error | Switched to `from openai import AzureOpenAI` |
| `max_tokens` error on GPT 5.3 | Use `max_completion_tokens` instead |
| `temperature` error on GPT 5.3 | Remove `temperature` param entirely |
| Missing dependencies after deploy | Add `--build-remote true` to ZIP deploy |
| Garbled characters (curly quotes) | Use `utf-8-sig` encoding + ASCII-only prompt |
| Claude 0 quota | No fix — switched to GPT 5.3 |
| `func` CLI ENOENT | Use `az functionapp deployment source config-zip` instead |
| 429 rate limit | SDK auto-retries; 2s delay between batches helps |
| Managed Identity auth failure | Set `managed_identity_client_id` explicitly |

---

*Document created: March 25, 2026*
*Last updated: March 29, 2026*
