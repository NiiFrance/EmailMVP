# EmailMVP — Design Plan & Implementation History

> Design decisions, architecture, and implementation history for the EmailMVP email campaign generator. The app supports 9 built-in campaign templates covering renewals, migrations, demand generation, and inbound motions.

---

## 1. Problem Statement

Cloudware is a Microsoft Solutions Partner that helps organizations manage, renew, upgrade, and optimize Microsoft-centric business processes. The marketing team runs multiple outreach campaigns — CSP renewals, EA migrations, marketplace promotions, demand generation, and more — each requiring different email sequences, tone, and personalization strategies.

**The manual process:**
- Sales reps receive lead exports from different sources with inconsistent column names
- Each campaign requires a different messaging strategy and email count
- Reps manually rewrite sequences for each campaign type
- The process is slow, inconsistent, and hard to reuse across new campaigns

**The solution:**
- Upload a CSV or Excel file
- Choose one of 9 purpose-built campaign templates
- Let the backend detect required columns, generate personalized email sequences per lead, and return an enriched CSV with email columns appended

---

## 2. Requirements

### Functional
- Upload CSV or Excel (.xlsx) files containing lead data
- List 9 available campaign templates to the frontend via an API
- Automatically detect required columns via fuzzy matching + LLM fallback
- Generate 2–8 personalized emails per lead depending on the template
- All templates share a unified output format: `[{"subject": ..., "body": ...}]`
- Append generated columns at the end of the original dataset
- Return enriched CSV for download
- Show real-time processing progress (processed X of Y leads)
- Handle files with any number of leads (tested up to 2,038)

### Non-Functional
- Process leads concurrently for speed (100 concurrent per batch)
- Handle API rate limits gracefully (auto-retry on 429, 5000 TPM capacity)
- UTF-8 BOM output that opens correctly in Excel
- Deployed on Azure with proper security (Managed Identity, Key Vault, RBAC)
- Accept arbitrary column ordering — fuzzy column mapper resolves field names

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
| Backend | Azure Functions v4 (Python 3.11, Durable) | Serverless orchestration with template-aware pipeline |
| AI Model | Azure OpenAI GPT 5.3 | Best available model with quota in subscription |
| Storage | Azure Blob Storage | Simple object storage for CSV files |
| Secrets | Azure Key Vault | Industry standard for secret management |
| Auth | Managed Identity + RBAC | Passwordless, no credentials in code |
| Monitoring | Application Insights | Native Azure monitoring, integrated with Functions |
| IaC | Bicep | Azure-native, simpler than ARM templates |

---

## 4. Data Flow

```
1. Frontend loads 10 campaign templates from GET /api/templates.
2. User uploads CSV or Excel (.xlsx) data and selects a template from the grouped dropdown.
3. Static Web App forwards POST /api/upload with prompt_id.
4. upload_csv parses the file, resolves the template, runs column detection against the
   template's required_fields, normalizes Excel to CSV, stores the input blob, and starts
   the orchestration with job_id, column_map, and template_config.
5. Frontend polls GET /api/status/{jobId} every 5 seconds.
6. orchestrate_emails calls extract_leads_activity, batches leads in groups of 100, fans out
   process_lead_activity calls with template_config, updates progress, then calls
   assemble_csv_activity.
7. process_lead_activity builds the system/user prompt pair using the template's prompt
   builder, calls GPT 5.3, and parses the JSON response into email dicts.
8. assemble_csv_activity flattens parsed emails into Subject_TouchN / Body_TouchN columns
   and uploads the final CSV to Blob Storage.
9. Frontend shows progress, then download summary, and downloads the enriched CSV.
```

---

## 5. Template Strategy

### Unified Output Format

All 9 templates produce the same JSON output: an array of `{"subject": ..., "body": ...}` objects. This means:
- One shared parser (parameterized by expected email count)
- One shared flattener (emails → `Subject_TouchN`, `Body_TouchN` columns)
- One shared output header generator
- No per-template parsing or flattening logic

### Prompt Organization

System prompts are stored as individual `.txt` files in `api/prompts/`. Each file contains the full system prompt for one campaign. The registry in `prompt_templates.py` loads them at import time and wires up the appropriate email count, required fields, and user prompt builder.

### Template: `cold_email` (Original)

| Touch | Purpose | Strategy |
|---|---|---|
| 1. Introduction | First contact | Warm, non-pushy, positions Cloudware as licensing advisor |
| 2. Diagnostic | Spark reflection | Asks about renewal pain points (compliance, over-licensing) |
| 3. Benefit | Show value | Cost savings, compliance, streamlined procurement |
| 4. Social Proof | Build trust | Anonymized success stories from similar orgs |
| 5. Authority | Establish credibility | Microsoft competencies, certifications, expertise |
| 6. Promo Canvas | Create opportunity | Microsoft promotions, incentives, programs |
| 7. Risk Reversal | Remove objections | No-obligation audit, seamless migration, SLAs |
| 8. Danger/Close | Create urgency | Renewal deadlines, compliance risk, soft CTA |

Constraints: max 7-word subjects, 200–260 word bodies, plain ASCII only, no URLs/signatures, address by first name, at least 3 paragraphs per body, no specific license types or seat counts.

### All Templates — Shared Constraints

- Output must be a pure JSON array of `{"subject": ..., "body": ...}` objects
- No markdown fences in output
- Max 7-word subject lines
- Plain ASCII only (no em dashes, curly quotes)
- No URLs, links, or signature blocks

### Template Registry Summary

| ID | Group | Emails | User Prompt | Required Fields |
|---|---|---|---|---|
| `csp_renewal_with_license` | Renewals | 4 | Generic | `first_name`, `organization` |
| `csp_renewal_without_license` | Renewals | 4 | Generic | `first_name`, `organization`, `email_address` |
| `price_change` | Renewals | 4 | Generic | `first_name`, `organization` |
| `ea_to_csp` | Migrations | 4 | Generic | `first_name`, `organization` |
| `e7_upsell` | Migrations | 5 | Generic | `first_name`, `organization`, `email_address` |
| `cloud_ascent` | Demand Gen | 4 | Generic | `first_name`, `organization` |
| `marketplace` | Demand Gen | 4 | Generic | `first_name`, `organization` |
| `cold_email` | Demand Gen | 8 | Custom (5 fields) | `first_name`, `last_name`, `organization`, `license_renewal`, `engagement_objectives` |
| `leads` | Inbound | 2 | Generic | `first_name` |

The "Generic" user prompt builder dumps all non-empty lead columns. The `cold_email` template uses a custom builder that formats the 5 primary fields explicitly plus remaining columns as context.

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

### Phase 8: Multi-Template Support (3 templates)
- Refactored `prompt_templates.py` into a template registry
- Added built-in `cold_email` and `e_invoice` templates plus runtime `custom` templates
- Added `GET /api/templates` for frontend template discovery
- Updated `function_app.py` to pass `template_config` through the pipeline
- Updated `column_mapper.py` to accept template-specific required fields
- Updated `csv_processor.py` for dynamic output columns
- Updated the frontend for template selection and custom prompt input
- Expanded test coverage to 125 passing tests

### Phase 9: 9-Template Registry (current)
- Marketing team provided 9 Word doc prompts for real campaign motions
- Key discovery: ALL templates share the same `[{"subject": ..., "body": ...}]` output format
- Rewrote `prompt_templates.py` — replaced per-template parsers/flatteners with shared factory functions
- Created 9 `.txt` prompt files in `api/prompts/` (one per template)
- Removed `e_invoice` complex schema (persona/channel metadata) — replaced with simpler 4-email version
- Removed `custom` prompt mode entirely — all templates are now purpose-built
- Removed custom prompt textarea from the frontend
- Added grouped `<optgroup>` dropdown organized by campaign category
- Added email_address disqualification patterns to `column_mapper.py`
- Simplified `csv_processor.py` (removed static constants, legacy branches)
- Simplified `function_app.py` (removed custom prompt handling)
- Rewrote all test files — **151 tests passing**
- Committed as `dae6f55` on `feature/multi-prompt-templates`

### Phase 10: Staging Deployment
- Created isolated staging environment: `rg-emailmvp-stg-eastus2`

  - Function App: `azfnemailmvpstg6476` (EP1)
  - SWA: `azswa-emailmvp-stg-6476` (linked backend)
  - Storage: `azstemailmvpstg6476`
  - App Insights: `appi-emailmvp-stg`
- Deployment debugging:
  - EasyAuth was enabled blocking all requests (401) — disabled
  - `SCM_DO_BUILD_DURING_DEPLOYMENT` was `false` — Oryx never ran `pip install`
  - Container restart loop caused by stale `ContainerTimeout` — fixed with stop/start
- Successfully deployed backend with `--build-remote true`
- Deployed frontend via SWA CLI
- All 9 templates verified working through the SWA proxy
- Pushed to GitHub: `feature/multi-prompt-templates` branch

### Phase 11: Marketing Prompt Refresh
- Marketing team provided updated system prompts for 2 Cloudware templates: EA to CSP and E7 Upsell
- Replaced both prompt files in `api/prompts/` with marketing's versions
- EA to CSP: CTAs on emails 1-3, greeting/closing requirements, body tightened to 140-220 words
- E7 Upsell: New "Foundational Understanding" section defining E7 pillars (Agent 365, Entra Suite, Work IQ, Copilot, E5 Security), "AI Operating System" positioning anchor
- Quality issues discovered during testing:
  - Paragraph count: Model merged greeting into first paragraph (4 paragraphs instead of 2-3)
  - Non-ASCII: Unicode non-breaking hyphens (U+2011) in output
- Fixes applied to all 3 prompts:
  - Paragraph instruction: greeting goes on its own line, does not count as a body paragraph
  - ASCII-only punctuation constraints retained for both prompts
  - Removed duplicate content from both prompt files (copy-paste artifact)
- 151 tests passing, deployed and validated on staging
- Committed as `e7e210c` on `feature/multi-prompt-templates`

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

These benchmark numbers come from the cold-email template. Other templates may vary depending on prompt length and output size.

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

### April 8, 2026 — Marketing Prompt Refresh (EA to CSP, E7 Upsell)

**Updated prompts:**
- Replaced 2 system prompts with marketing team's updated versions
- EA to CSP: CTAs on emails 1-3, greeting/closing requirements, body range tightened to 140-220 words, ASCII-only constraint
- E7 Upsell: New Foundational Understanding section (E7 = E5 + Copilot + Agent 365 + Entra Suite + Work IQ), "AI Operating System" positioning, no em dashes, ASCII-only

**Quality fixes:**
- Paragraph constraint rewritten: greeting on its own line, not counted as body paragraph (was merging greeting into first paragraph producing unnatural email formatting)
- Removed duplicate content from both prompt files

**Validation:**
- No code changes — only prompt text files updated
- 151 tests passing
- Deployed to staging (`azfnemailmvpstg6476`)

**Files changed:**
- `api/prompts/ea_to_csp.txt`
- `api/prompts/e7_upsell.txt`

### April 4, 2026 — 9-Template Registry & Staging Deployment

**New capabilities:**
- 9 purpose-built campaign templates replacing the old 3-template system (cold_email, e_invoice, custom)
- All templates share unified `[{"subject", "body"}]` output format
- System prompts stored as individual `.txt` files in `api/prompts/`
- Shared factory functions for parsing, headers, and flattening (parameterized by email count)
- Grouped `<optgroup>` dropdown in the frontend (Renewals, Migrations, Demand Gen, Inbound)
- Email address disqualification patterns in column mapper

**Removed:**
- `e_invoice` complex schema (persona/channel metadata)
- `custom` prompt mode and textarea
- Per-template parsers and output flatteners

**Deployment:**
- Full staging environment deployed and verified
- Backend: `azfnemailmvpstg6476` in `rg-emailmvp-stg-eastus2`
- Frontend: `azswa-emailmvp-stg-6476` → https://calm-smoke-02e96b50f.6.azurestaticapps.net
- 151 tests passing

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
- **Footer text** — Shortened from "Powered by Azure Foundry & Claude Opus 4.6 — Cloudware" to just "Cloudware".

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
| Missing dependencies after deploy | Set `SCM_DO_BUILD_DURING_DEPLOYMENT=true` and use `--build-remote true` |
| Garbled characters (curly quotes) | Use `utf-8-sig` encoding + ASCII-only prompt |
| Claude 0 quota | No fix — switched to GPT 5.3 |
| `func` CLI ENOENT | Use `az functionapp deployment source config-zip` instead |
| 429 rate limit | SDK auto-retries; 2s delay between batches helps |
| Managed Identity auth failure | Set `managed_identity_client_id` explicitly |
| Container restart loop (stale timeout) | `az functionapp stop` then `az functionapp start` |
| EasyAuth blocking anonymous requests | `az webapp auth update --enabled false` |
| 409 conflict on zip deploy | Clear `WEBSITE_RUN_FROM_PACKAGE`, set `SCM_DO_BUILD_DURING_DEPLOYMENT=true` |

---

*Document created: March 25, 2026*
*Last updated: April 4, 2026*
