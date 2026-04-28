# Cloudware — Email Campaign Generator

A template-driven email campaign generator that turns CSV/Excel lead lists into personalized multi-touch email sequences using Azure OpenAI. Upload a lead file, pick one of 9 built-in campaign templates, and download an enriched CSV with subject lines and email bodies generated per lead.

## Live Environments

| Environment | URL |
|---|---|
| **Cloudware** | https://zealous-mushroom-0ddbf460f.7.azurestaticapps.net |

## Available Templates

All templates share a unified output format: JSON array of `{"subject": ..., "body": ...}` objects, flattened into `Subject_Touch1`, `Body_Touch1`, etc. columns in the output CSV.

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

## Architecture

![Architecture Diagram](emailmvp_architecture.png)

```
[Azure Static Web App]  -> vanilla HTML/CSS/JS
        |
        +-> GET  /api/templates        (list 9 campaign templates)
        +-> POST /api/upload           (CSV/Excel + template selection)
        +-> GET  /api/status/{jobId}   (real-time progress)
        +-> GET  /api/download/{jobId} (enriched CSV)
        |
        v
[Azure Functions App]   -> Python 3.11, Durable Functions, EP1
   |
   +-> upload_csv               parse file, detect columns, start orchestration
   +-> orchestrate_emails       fan-out/fan-in across leads in batches of 100
   +-> extract_leads_activity   extract lead rows from stored CSV
   +-> process_lead_activity    build prompt pair, call GPT 5.3, parse JSON
   +-> assemble_csv_activity    flatten emails into CSV columns, upload output

[Azure Blob Storage]    <- csv-input / csv-output containers
[Azure OpenAI]          <- deployment: gpt-53-chat (GPT 5.3)
```

## API Surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/templates` | `GET` | Returns all 9 templates with group, description, email count |
| `/api/upload` | `POST` | Accepts `file` + `prompt_id`, starts async generation |
| `/api/status/{jobId}` | `GET` | Returns orchestration status and progress (processed/total) |
| `/api/download/{jobId}` | `GET` | Returns the enriched CSV with generated email columns |

### Upload Form Fields

- `file`: CSV or Excel (.xlsx) file
- `prompt_id`: one of the 9 template IDs (e.g. `cold_email`, `csp_renewal_with_license`, `leads`)

## Column Detection

Required columns are detected automatically using a two-stage resolver:

1. **Fuzzy matching** against template-specific keyword sets (e.g. "company", "firm", "employer" all resolve to `organization`)
2. **Azure OpenAI fallback** for any unresolved fields
3. Upload rejection with a clear error if fields still cannot be resolved

Invalid email addresses (containing patterns like `noemail`, `unknown`, `test@test`) are automatically disqualified during mapping.

All non-required columns are preserved as context and passed to the model for personalization.

## Output Behavior

- Output columns are appended to the end of the uploaded dataset
- Column count varies by template: 4 columns (2-email template) to 16 columns (8-email template)
- Each email produces `Subject_TouchN` + `Body_TouchN` column pair
- Error rows are preserved with `[ERROR: ...]` markers in the generated columns
- Output CSV uses UTF-8 BOM encoding for Excel compatibility

## Frontend

The frontend groups templates by campaign category in an `<optgroup>` dropdown:

- Template selector loaded dynamically from `/api/templates`
- Grouped dropdown: Renewals, Migrations, Demand Generation, Inbound
- Dynamic button text showing email count for selected template
- CSV and Excel upload support
- Real-time progress bar with pulse animation during initial batch
- Job summary (leads, elapsed time, job ID) on the download screen

## Project Structure

```
EmailMVP/
|- api/
|  |- function_app.py          # HTTP triggers, orchestrator, activities
|  |- prompt_templates.py      # 9-template registry with shared helpers
|  |- csv_processor.py         # CSV/Excel parsing and dynamic CSV assembly
|  |- column_mapper.py         # Fuzzy matching + LLM fallback for required fields
|  |- host.json                # Durable Functions configuration
|  |- requirements.txt         # Python dependencies
|  |- prompts/                 # System prompt text files (one per template)
|  |  |- cold_email.txt
|  |  |- csp_renewal_with_license.txt
|  |  |- csp_renewal_without_license.txt
|  |  |- e7_upsell.txt
|  |  |- ea_to_csp.txt
|  |  |- leads.txt
|  |  |- marketplace.txt
|  |  |- price_change.txt
|  |  \- cloud_ascent.txt
|  \- tests/
|     |- test_column_mapper.py
|     |- test_csv_processor.py
|     |- test_function_app.py
|     \- test_prompt_templates.py
|- frontend/
|  |- index.html               # Upload UI with grouped template selector
|  |- app.js                   # Upload, polling, download, template loading
|  |- styles.css               # UI styling and progress animation
|  \- staticwebapp.config.json
|- infra/
|  \- main.bicep
\- README.md
```

## Tech Stack

| Layer | Technology |
|---|---|
| AI Model | Azure OpenAI GPT 5.3 (`gpt-53-chat`) |
| Backend | Azure Functions v4, Durable Functions, Python 3.11 |
| Frontend | Azure Static Web Apps, vanilla HTML/CSS/JS |
| File Parsing | pandas + openpyxl |
| Storage | Azure Blob Storage |
| Identity | Managed Identity + RBAC |
| Secrets | Azure Key Vault |
| Monitoring | Application Insights |
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
    "AZURE_OPENAI_DEPLOYMENT": "gpt-53-chat",
    "CSV_INPUT_CONTAINER": "csv-input",
    "CSV_OUTPUT_CONTAINER": "csv-output",
    "BATCH_SIZE": "100"
  }
}
```

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

Current status: **151 passed**

## Deployment

### Backend — Function App (ZIP deploy with remote build)

```powershell
# Create zip from api/ excluding dev files
cd api
$items = Get-ChildItem -Path . -Exclude tests,__pycache__,.pytest_cache,.venv,.funcignore,local.settings.json
Compress-Archive -Path ($items | ForEach-Object { $_.FullName }) -DestinationPath ..\deploy.zip -Force

# Deploy with Oryx build (required for pip install)
az functionapp deployment source config-zip `
  --resource-group rg-emailmvp-stg-eastus2 `
  --name azfnemailmvpstg6476 `
  --src ..\deploy.zip `
  --build-remote true
```

**Important:** `SCM_DO_BUILD_DURING_DEPLOYMENT` must be `true` in app settings, otherwise `requirements.txt` dependencies won't be installed.

### Frontend — Static Web App

```powershell
npx @azure/static-web-apps-cli deploy ./frontend `
  --deployment-token <token> `
  --env production
```

### Cloudware Environment

| Resource | Name |
|---|---|
| Resource Group | `rg-emailmvp-cloudware-eastus2` |
| Function App | `azfnzcn6oizgufwbo` |
| Static Web App | `azswazcn6oizgufwbo` |
| Storage Account | `azstzcn6oizgufwbo` |
| App Insights | `azaizcn6oizgufwbo` |

The SWA has the Function App linked as a backend, so `/api/*` routes are proxied automatically.

## Key Design Decisions

- **9-template registry** with prompts loaded from individual `.txt` files for easy editing
- **Unified output schema** — all templates produce `[{"subject": ..., "body": ...}]`, eliminating per-template parsers and flatteners
- **Shared generic helpers** — factory functions for parsing, headers, and flattening parameterized by email count
- **Grouped dropdown UI** — templates organized by campaign category (Renewals, Migrations, Demand Gen, Inbound)
- **No custom prompt mode** — removed in favor of purpose-built templates vetted by the marketing team
- **Excel normalization** — `.xlsx` uploads are converted to CSV at upload time so the downstream pipeline stays consistent
- **Durable fan-out/fan-in** — batch size 100, 2-second inter-batch delay, 2-hour timeout on EP1
- The cold-email template remains backward compatible through `SYSTEM_PROMPT` and `build_user_prompt` aliases

See `PLAN.md` for the implementation history and the design changes that took the app from a single-purpose cold-email generator to a multi-template branch.
