# EmailMVP — Email Campaign Generator

A multi-user, template-driven email campaign platform that turns CSV/Excel lead lists into personalized multi-touch email sequences using Azure OpenAI — then pushes them to Snov.io as ready-made drip campaigns. Users sign in with Microsoft Entra ID and get a private workspace (campaign history, resume, saved Snov.io connection); admins manage the campaign library and user roles from an in-app Manage screen.

One codebase powers three branded deployments:

## Live Environments

| Environment | Branch | URL |
|---|---|---|
| **Cloudware (Snov.io flagship)** | `feature/cloudware-snovio-foundation` | https://ashy-ocean-0a8e5f60f.7.azurestaticapps.net |
| **Cloudware** | `multi-prompt-templates-cloudware` | https://mango-bush-067ca3b0f.7.azurestaticapps.net |
| **Reliance Infosystems** | `main` | https://brave-pebble-0633e900f.7.azurestaticapps.net |

All three require Microsoft Entra ID sign-in (single tenant; external staff join as B2B guests). Anonymous visitors land on a branded sign-in page.

## Available Templates

Campaigns are seeded from the code registry into Azure Table Storage on first use and are **admin-editable in-app** (Manage → Campaigns: create, edit prompt/name/description/email count, archive). The built-in seeds share a unified output format: JSON array of `{"subject": ..., "body": ...}` objects, flattened into `Subject_Touch1`, `Body_Touch1`, etc. columns in the output CSV.

| Group | Template | Emails/Lead | Required Fields |
|---|---|---|---|
| **Renewals** | CSP Renewal — With License | 4 | `first_name`, `organization` |
| **Renewals** | CSP Renewal — Without License | 4 | `first_name`, `organization`, `email_address` |
| **Renewals** | Price Change Early Renewal | 4 | `first_name`, `organization` |
| **Migrations** | EA to CSP Migration | 4 | `first_name`, `organization` |
| **Migrations** | E7 Upsell — AI Governance | 5 | `first_name`, `organization`, `email_address` |
| **Demand Gen** | CloudAscent — Solution Focus | 4 | `first_name`, `organization` |
| **Demand Gen** | Marketplace Offers | 4 | `first_name`, `organization` |
| **Demand Gen** | Cold Email — Original | 8 | `first_name`, `last_name`, `organization`, `license_renewal`, `engagement_objectives` |
| **Inbound** | Help & Assistance — Leads | 2 | `first_name` |
| **Compliance** *(Reliance only)* | NRS E-Invoice — Nigeria | 4 | `first_name`, `organization` |

The Reliance deployment (`main`) carries its own fully Reliance-branded prompt set including the NRS E-Invoice campaign; the Cloudware deployments carry Cloudware-branded prompts.

## Architecture

![Architecture Diagram](emailmvp_architecture.png)

```
[Azure Static Web App]  -> vanilla HTML/CSS/JS SPA + branded /login.html
        |   (Entra ID sign-in enforced by SWA; principal forwarded to the API)
        |
        +-> GET  /api/me               (identity, role, resume context)
        +-> GET  /api/campaigns        (table-backed campaign library)
        +-> POST /api/upload           (store file + detect columns — no generation yet)
        +-> POST /api/generate         (confirmed column map -> start orchestration)
        +-> GET  /api/status/{jobId}   (owner-only progress)
        +-> GET  /api/download/{jobId} (owner-only enriched CSV)
        +-> GET  /api/jobs             (my workspace history)
        |
        v
[Azure Functions App]   -> Python 3.11, Durable Functions, EP1
   |
   +-> upload_csv               parse file, detect columns, return mapping for review
   +-> generate_emails          validate ownership + column map, start orchestration
   +-> orchestrate_emails       fan-out/fan-in across leads in batches of 100
   +-> extract_leads_activity   extract lead rows from stored CSV
   +-> process_lead_activity    build prompt pair, call the model, parse + retry
   +-> assemble_csv_activity    flatten emails into CSV columns, upload output

[Azure Blob Storage]    <- csv-input / csv-output / snovio session blobs
[Azure Table Storage]   <- Users / Jobs / SnovioCreds / Campaigns (per-app account)
[Azure OpenAI]          <- shared deployment: gpt-5.4-mini
```

## Identity, Workspaces & Roles

- **Sign-in**: SWA built-in Entra ID auth (custom single-tenant app registration shared by all three SWAs, one redirect URI + client secret per app). Anonymous requests redirect to `/login.html`.
- **Workspaces**: every job is recorded against the signed-in user; status/download/Snov.io routes enforce ownership (foreign jobs read as 404). The Home dashboard lists the user's history with open-to-resume and a “continue where you left off” banner.
- **Roles**: `ADMIN_EMAILS` app setting bootstraps permanent admins; additional admins are promoted in-app (Manage → Users). Admins manage the campaign library; users cannot.
- **Snov.io credentials**: entered once, validated, then stored encrypted per user — future logins auto-connect. Disconnect forgets them.

## API Surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/me` | `GET` | Signed-in identity, role, and saved resume context |
| `/api/me/context` | `PUT` | Persist the user's resume context |
| `/api/users` | `GET` | Admin: list users and roles |
| `/api/users/{oid}/role` | `PUT` | Admin: promote/demote a user |
| `/api/jobs` | `GET` | The caller's workspace history |
| `/api/campaigns` | `GET` | Campaign library (admins may pass `?full=true`) |
| `/api/campaigns` | `POST` | Admin: create a campaign |
| `/api/campaigns/{id}` | `PUT` / `DELETE` | Admin: edit or archive a campaign |
| `/api/templates` | `GET` | Template metadata for the campaign picker |
| `/api/upload` | `POST` | Accepts `file` + `prompt_id`; stores the file and returns detected columns + mapping for review (does **not** start generation) |
| `/api/generate` | `POST` | Starts generation for an uploaded job with the user-confirmed column map |
| `/api/status/{jobId}` | `GET` | Owner-only orchestration status and progress |
| `/api/download/{jobId}` | `GET` | Owner-only enriched CSV |
| `/api/snovio/status` | `GET` | Returns whether Snov.io credentials are configured and any active session |
| `/api/snovio/session` | `POST` / `DELETE` | Opens or closes a secure server-side session for user-supplied Snov.io API keys |
| `/api/snovio/balance` | `GET` | Returns Snov.io balance preflight data when configured |
| `/api/snovio/options` | `GET` | Lists Snov.io lists, campaigns, sender accounts, schedules, custom fields, and template mappings |
| `/api/snovio/preflight` | `GET` | Estimates credits and request volume before Snov.io actions |
| `/api/jobs/{jobId}/snovio/verify` | `POST` | Starts email verification for generated rows |
| `/api/jobs/{jobId}/snovio/sync` | `POST` | Dry-runs or syncs eligible rows into a Snov.io list |
| `/api/jobs/{jobId}/snovio/journey` | `POST` | Dry-runs or builds a multi-touch draft drip campaign from the generated emails |
| `/api/jobs/{jobId}/snovio/enrich` | `POST` | Dry-runs or starts optional Snov.io enrichment tasks |
| `/api/snovio/analytics` | `GET` | Proxies campaign analytics and progress |
| `/api/snovio/webhook` | `POST` | Receives signed Snov.io webhook events |
| `/api/snovio/suppressions` | `POST` | Adds emails/domains to a Snov.io Do-not-email list |
| `/api/snovio/recipient-status` | `POST` | Pauses, activates, or unsubscribes a campaign recipient |

### Upload Form Fields

- `file`: CSV or Excel (.xlsx) file
- `prompt_id`: any campaign id from `/api/campaigns` (e.g. `cold_email`, `csp_renewal_with_license`, `leads`)

## Column Detection

Required columns are detected automatically using a two-stage resolver:

1. **Fuzzy matching** against template-specific keyword sets (e.g. "company", "firm", "employer" all resolve to `organization`)
2. **Azure OpenAI fallback** for any unresolved fields
3. A combined **"Full Name" column can stand in** for first/last name (split at extraction time)
4. The user then **reviews the mapping in a "Confirm your columns" panel** before generation — each dropdown shows a sample value, so even blank/`Unnamed` headers can be pointed at the right field

Invalid email addresses (containing patterns like `noemail`, `unknown`, `test@test`) are automatically disqualified during mapping.

All non-required columns are preserved as context and passed to the model for personalization.

## Output Behavior

- Output columns are appended to the end of the uploaded dataset
- Column count varies by template: 4 columns (2-email template) to 16 columns (8-email template)
- Each email produces `Subject_TouchN` + `Body_TouchN` column pair
- Error rows are preserved with `[ERROR: ...]` markers in the generated columns
- Output CSV uses UTF-8 BOM encoding for Excel compatibility

## Frontend

A single-page app with a branded public sign-in page and a four-step wizard:

- **/login.html** — designed landing page (hero, product preview, feature strip) with “Sign in with Microsoft”
- **Home** — workspace dashboard: stats, campaign history with open-to-resume, continue-where-you-left-off banner, Snov.io connection status
- **Steps 1–4** — Choose a campaign (grouped cards) → Upload leads (drag-drop, format guidance, detected-columns preview, mapping confirmation) → Review & edit every drafted touch → Send to Snov.io (list sync, drip-campaign creation, verification, suppression — with hover tooltips throughout)
- **Manage** *(admins)* — campaign library editor and user role management
- Sidebar shows the signed-in user chip with role badge and sign-out

## Project Structure

```
EmailMVP/
|- api/
|  |- function_app.py          # HTTP triggers, identity/roles, orchestrator, activities
|  |- data_store.py            # Table Storage layer (Users, Jobs, SnovioCreds, Campaigns)
|  |- prompt_templates.py      # Template registry (table-backed w/ code fallback + seeds)
|  |- csv_processor.py         # CSV/Excel parsing and dynamic CSV assembly
|  |- column_mapper.py         # Fuzzy matching + LLM fallback + full-name splitting
|  |- snovio_client.py         # Snov.io API client (OAuth, throttling)
|  |- snovio_workflows.py      # Verification, sync, prospect payloads, reports
|  |- snovio_campaigns.py      # Drip-campaign (journey) builder
|  |- host.json                # Durable Functions configuration
|  |- requirements.txt         # Python dependencies
|  |- prompts/                 # System prompt text files (one per built-in template)
|  \- tests/
|- frontend/
|  |- login.html               # Public branded sign-in page
|  |- index.html               # SPA (Home, wizard steps 1-4, Manage)
|  |- app.js                   # Views, auth, upload/mapping, review, Snov.io, admin
|  |- styles.css               # Design system, tooltips, admin screens
|  |- assets/                  # Brand logo + fonts
|  \- staticwebapp.config.json # Entra auth provider + route lockdown
|- scripts/                    # Deploy + Azure utility scripts (incl. setup_swa_auth.ps1)
|- infra/
|  \- main.bicep
\- README.md
```

## Tech Stack

| Layer | Technology |
|---|---|
| AI Model | Azure OpenAI (`gpt-5.4-mini`, shared deployment) |
| Backend | Azure Functions v4, Durable Functions, Python 3.11 |
| Frontend | Azure Static Web Apps, vanilla HTML/CSS/JS |
| Identity (users) | Microsoft Entra ID via SWA built-in auth (B2B guests for external staff) |
| File Parsing | pandas + openpyxl |
| Storage | Azure Blob Storage + Azure Table Storage (users/jobs/creds/campaigns) |
| Identity (infra) | Managed Identity + RBAC |
| Secrets | Azure Key Vault + encrypted-at-rest per-user Snov.io credentials |
| Monitoring | Application Insights |
| Outreach Integration | Snov.io verification, sync, drip campaigns, enrichment, analytics, suppression, webhooks |
| IaC | Bicep |

## Local Development

### 1. Create the Python environment

```powershell
cd api
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure `api/local.settings.json`

```json
{
  "IsEncrypted": false,
  "Values": {
    "AzureWebJobsStorage": "UseDevelopmentStorage=true",
    "FUNCTIONS_WORKER_RUNTIME": "python",
    "AZURE_OPENAI_ENDPOINT": "https://<your-resource>.openai.azure.com/",
    "AZURE_OPENAI_API_KEY": "<api-key>",
    "AZURE_OPENAI_DEPLOYMENT": "gpt-5.4-mini",
    "CSV_INPUT_CONTAINER": "csv-input",
    "CSV_OUTPUT_CONTAINER": "csv-output",
    "BATCH_SIZE": "100",
    "SNOVIO_CLIENT_ID": "<snovio-client-id>",
    "SNOVIO_CLIENT_SECRET": "<snovio-client-secret>",
    "SNOVIO_API_BASE_URL": "https://api.snov.io",
    "SNOVIO_REQUESTS_PER_MINUTE": "60",
    "SNOVIO_WEBHOOK_SECRET": "<shared-webhook-secret>",
    "SNOVIO_TEMPLATE_MAPPINGS": "{}",
    "SNOVIO_ALLOW_UNKNOWN_VERIFICATION": "false",
    "SNOVIO_LOW_CREDIT_THRESHOLD": "0",
    "SNOVIO_SESSION_TTL_SECONDS": "3600",
    "SNOVIO_SESSION_ENCRYPTION_KEY": "<optional-fernet-key>",
    "SNOVIO_DEFAULT_DELAY_DAYS": "3",
    "SNOVIO_CAMPAIGN_TIMEZONE": "",
    "SNOVIO_CAMPAIGN_ARCHIVE_MONTHS": "3",
    "ADMIN_EMAILS": "you@yourtenant.com"
  }
}
```

Snov.io settings are optional. If they are absent, `/api/snovio/status` reports the integration as disabled and the generation/download workflow continues unchanged.

Snov.io sync is explicitly user-triggered after generation. Dry-run mode is available from the UI and backend, active campaign sync requires `confirmActiveCampaign=true`, and recipient verification is required by default before live sync.

The app campaign template selected before generation controls the emails GPT creates. The Snov.io campaign selected after generation is optional outreach context. When a Snov.io campaign is selected and its API payload includes `list_id`, sync uses that campaign list automatically. If no list is selected or inferred, the UI can request `autoCreateList=true`; dry-run reports the planned list name, while live sync creates a Snov.io prospect list with `POST /v1/lists` before adding prospects.

### Bring-your-own Snov.io credentials

Credentials are resolved per request. A server-side default can be supplied through Key Vault (`SNOVIO_CLIENT_ID` / `SNOVIO_CLIENT_SECRET`), and a user can additionally connect their own keys from the UI:

1. The browser sends the `client_id` / `client_secret` to `POST /api/snovio/session` over HTTPS.
2. The backend validates them against Snov.io, then stores them server-side under an opaque session id (encrypted at rest — app-level Fernet encryption when `SNOVIO_SESSION_ENCRYPTION_KEY` is set, otherwise storage encryption only).
3. The browser keeps only the opaque session id (in `sessionStorage`) and sends it back via the `X-Snovio-Session` header. The secret is never returned to the browser, never written to `localStorage`, and never logged.
4. `DELETE /api/snovio/session` closes the session and deletes the stored credentials. Sessions also expire after `SNOVIO_SESSION_TTL_SECONDS`.

### Customer journey (drip campaign)

`POST /api/jobs/{jobId}/snovio/journey` turns the drafted, per-lead emails into one multi-touch Snov.io drip campaign:

- The touch count is derived from the generated `Subject_Touch{n}` / `Body_Touch{n}` columns.
- Each lead's drafted emails are synced as prospect **custom fields**, and every campaign email step references them through merge variables (`{{Subject_Touch1}}`, `{{Body_Touch1}}`, …) — so every recipient receives their own AI-drafted content for each touch.
- The campaign is created in **draft** state only (this endpoint never starts a campaign). A human reviews and launches it in Snov.io.
- **Prerequisites:** at least one connected sender email account, and the `Subject_Touch{n}` / `Body_Touch{n}` custom fields must already exist in the Snov.io account (Prospects → custom fields). If they are missing, the journey returns `422` listing the exact field names to create. `delayDays`, tracking, and campaign title are configurable from the UI; `dryRun` previews the full plan without creating anything.


For isolated test environments that should reuse an existing Azure OpenAI deployment, set `existingAzureOpenAiKeyVaultName` during Bicep deployment. The Function App reads `AzureOpenAIEndpoint` and `AzureOpenAIApiKey` from that vault instead of copying the secrets into the new environment vault. Grant the Function App managed identity `Key Vault Secrets User` on the existing vault when the vault is outside the deployment resource group.

Template mappings can be provided with `SNOVIO_TEMPLATE_MAPPINGS` as JSON, for example:

```json
{
  "cold_email": { "listId": "1234567", "campaignId": "237945" }
}
```

Generated `Subject_TouchN` and `Body_TouchN` values are sent as Snov.io custom fields only when matching custom field labels exist in the Snov.io account.

### 3. Start local storage

```powershell
azurite --silent --location .azurite --debug .azurite/debug.log
az storage container create -n csv-input --connection-string "UseDevelopmentStorage=true"
az storage container create -n csv-output --connection-string "UseDevelopmentStorage=true"
```

### 4. Run the backend and frontend

```powershell
cd api
func start
```

```powershell
cd frontend
python -m http.server 4280
```

Open `http://localhost:4280` in your browser.

## Running Tests

```powershell
cd api
python -m pytest tests -q
```

Current status: **201+ passing** (203 on `main`, which carries extra Reliance template tests)

## Deployment

### Backend — Function App (ZIP deploy with remote build)

```powershell
# Preferred: use the helper script (zips api/, deploys with remote build, restarts)
.\scripts\redeploy_api.ps1

# Or manually:
cd api
$items = Get-ChildItem -Path . -Exclude tests,__pycache__,.pytest_cache,.venv,.funcignore,local.settings.json
Compress-Archive -Path ($items | ForEach-Object { $_.FullName }) -DestinationPath ..\deploy.zip -Force
az functionapp deployment source config-zip `
  --resource-group <resource-group> `
  --name <function-app> `
  --src ..\deploy.zip `
  --build-remote true
az functionapp restart --resource-group <resource-group> --name <function-app>
```

**Important:** `SCM_DO_BUILD_DURING_DEPLOYMENT` must be `true` in app settings, otherwise `requirements.txt` dependencies won't be installed. A restart after deploy is required for the new package to load. If Oryx serves a cached build, bump the `# cache-bust` comment in `api/requirements.txt`.

### Frontend — Static Web App

```powershell
# Preferred: helper script (fetches the deployment token and runs the SWA CLI)
.\scripts\deploy_frontend.ps1

# Or manually:
npx @azure/static-web-apps-cli deploy ./frontend `
  --deployment-token <token> `
  --env production
```

### Entra ID auth for a new SWA

`scripts/setup_swa_auth.ps1` wires a Static Web App to the shared Entra app registration: it appends the SWA's `/.auth/login/aad/callback` redirect URI, mints a dedicated client secret (append — never reset), and sets `AAD_CLIENT_ID` / `AAD_CLIENT_SECRET` on the SWA.

### Environments

Each deployment has its own resource group, Function App, Static Web App, and storage account (see Live Environments above). Every SWA has its Function App linked as a backend, so `/api/*` routes are proxied automatically.

## Key Design Decisions

- **Table-backed campaign registry** — campaigns live in Azure Table Storage (seeded from code `.txt` prompts on first use) so admins can create/edit/archive them in-app without a deploy
- **Unified output schema** — all templates produce `[{"subject": ..., "body": ...}]`, eliminating per-template parsers and flatteners
- **Two-phase upload** — upload detects and proposes a column mapping the user confirms before generation, instead of rejecting ambiguous files
- **Per-user workspaces** — jobs, resume context, and encrypted Snov.io credentials are keyed by the Entra object id; ownership is enforced server-side (foreign jobs return 404)
- **Shared generic helpers** — factory functions for parsing, headers, and flattening parameterized by email count
- **No custom prompt mode** — removed in favor of purpose-built templates vetted by the marketing team
- **Excel normalization** — `.xlsx` uploads are converted to CSV at upload time so the downstream pipeline stays consistent
- **Durable fan-out/fan-in** — batch size 100, 2-second inter-batch delay, 2-hour timeout on EP1

See `PLAN.md` for the implementation history and the design changes that took the app from a single-purpose cold-email generator to a multi-template branch.
