# Reliance Infosystems - Template-Driven Outreach Generator

This branch turns EmailMVP into a template-driven lead enrichment app. Users can upload CSV or Excel (.xlsx) files, choose a generation template, and receive an enriched CSV with template-specific output columns appended to the original data.

The current production URL still represents the cold-email-only deployment:

- Production URL: https://blue-mud-0ae74790f.4.azurestaticapps.net

This feature branch is ahead of production. It adds built-in multi-template support, custom system prompts, dynamic CSV output schemas, and a new templates API used by the frontend.

## What This Branch Adds

- Multiple system prompts via a template registry in `api/prompt_templates.py`
- Built-in `cold_email` and `e_invoice` generation modes
- User-supplied `custom` prompt mode with dynamic JSON flattening
- `GET /api/templates` so the frontend can populate the template selector
- Template-specific required-field detection during upload
- Dynamic output columns based on the selected template

## Available Templates

| Template ID | Purpose | Required Fields | Output Shape |
|---|---|---|---|
| `cold_email` | Generate 8 Microsoft licensing cold emails per lead | `first_name`, `last_name`, `organization`, `license_renewal`, `engagement_objectives` | 16 columns: `Subject_Touch1` to `Body_Touch8` |
| `e_invoice` | Generate 5 outreach scripts for e-invoicing and finance modernization | `first_name`, `last_name`, `organisation_name`, `email_address` | Persona/channel metadata plus 5 touch blocks |
| `custom` | Run an arbitrary system prompt against all lead columns | None enforced | Columns discovered dynamically from the first valid JSON response |

## Architecture

![Architecture Diagram](emailmvp_architecture.png)

```
[Azure Static Web App]  -> vanilla HTML/CSS/JS
        |
        +-> GET  /api/templates
        +-> POST /api/upload
        +-> GET  /api/status/{jobId}
        +-> GET  /api/download/{jobId}
        |
        v
[Azure Functions App]   -> Python 3.11, Durable Functions, Premium EP1
   |
   +-> upload_csv
   |     - accepts .csv and .xlsx
   |     - resolves template from prompt_id/custom_prompt
   |     - runs template-specific column detection when required
   |     - stores normalized CSV in Blob Storage
   |
   +-> orchestrate_emails
   |     - extracts leads
   |     - fans out GPT requests in batches of 100
   |     - updates real-time progress
   |     - assembles template-specific output columns
   |
   +-> process_lead_activity
   |     - builds the selected system/user prompt pair
   |     - calls Azure OpenAI GPT 5.3
   |     - parses template-specific JSON
   |
   +-> assemble_csv_activity
         - flattens parsed output into CSV columns

[Azure Blob Storage]    <- csv-input / csv-output containers
[Azure OpenAI]          <- deployment: gpt-53-chat
```

## API Surface

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/templates` | `GET` | Returns built-in templates for the frontend selector |
| `/api/upload` | `POST` | Accepts file upload plus `prompt_id` and optional `custom_prompt` |
| `/api/status/{jobId}` | `GET` | Returns Durable Function job status and progress |
| `/api/download/{jobId}` | `GET` | Returns the enriched CSV output |

### Upload Form Fields

- `file`: CSV or Excel file
- `prompt_id`: one of `cold_email`, `e_invoice`, or `custom`
- `custom_prompt`: required only when `prompt_id=custom`

## Column Detection

For built-in templates, required columns are detected automatically using a two-stage resolver:

1. Fuzzy matching against template-specific keyword sets
2. Azure OpenAI fallback for unresolved fields
3. Upload rejection if required fields still cannot be resolved

All non-primary columns are preserved as context and passed into the prompt builder for personalization.

Custom prompts skip required-field detection entirely and receive all lead columns as context.

## Output Behavior

- Output columns are always appended to the end of the uploaded dataset
- Cold email output is fixed-width: 16 appended columns
- E-invoice output includes persona metadata plus 5 touch blocks
- Custom output is flattened dynamically from the first valid JSON object or array the model returns
- Error rows are preserved in the CSV with `[ERROR: ...]` markers in the generated columns

## Frontend Behavior

The frontend now includes:

- Template selector loaded from `/api/templates`
- Custom prompt textarea with 10,000 character limit
- CSV and Excel upload support
- Real-time progress with pulse animation before the first batch completes
- Job summary retained on the download screen

## Project Structure

```
EmailMVP/
|- api/
|  |- function_app.py          # HTTP triggers, orchestrator, activities
|  |- prompt_templates.py      # Template registry, parsers, output flatteners
|  |- csv_processor.py         # CSV/Excel parsing and dynamic CSV assembly
|  |- column_mapper.py         # Fuzzy matching + LLM fallback for required fields
|  |- host.json                # Durable Functions configuration
|  |- requirements.txt         # Python dependencies
|  |- local.settings.json      # Local development settings
|  \- tests/
|     |- test_column_mapper.py
|     |- test_csv_processor.py
|     |- test_function_app.py
|     \- test_prompt_templates.py
|- frontend/
|  |- index.html               # Upload UI with template selector
|  |- app.js                   # Upload, polling, download, template loading
|  |- styles.css               # UI styling and progress animation
|  \- staticwebapp.config.json
|- infra/
|  \- main.bicep
|- architecture_diagram.py
|- emailmvp_architecture.png
|- PLAN.md
\- README.md
```

## Tech Stack

| Layer | Technology |
|---|---|
| AI model | Azure OpenAI GPT 5.3 (`gpt-53-chat`) |
| Backend | Azure Functions, Durable Functions, Python 3.11 |
| Frontend | Azure Static Web Apps, vanilla HTML/CSS/JS |
| File parsing | pandas + openpyxl |
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

Run the full backend suite from `api/`:

```powershell
python -m pytest tests -q
```

Current branch status: `125 passed`

## Deployment Notes

### Backend ZIP deploy

```powershell
Compress-Archive -Path api\* -DestinationPath deploy.zip -Force
az functionapp deployment source config-zip `
  --resource-group <resource-group> `
  --name <function-app-name> `
  --src deploy.zip `
  --build-remote true
```

`--build-remote true` is required so Azure installs dependencies from `requirements.txt`.

### Recommended pre-production topology

Because this branch is ahead of production, test it in a separate environment rather than against the live app:

- separate Static Web App
- separate Function App
- separate Storage account
- separate Application Insights resource

That isolates template changes, custom prompts, and generated test data from the production cold-email workflow.

## Key Design Decisions

- Template registry instead of a single hard-coded system prompt
- Built-in templates keep strict schemas and required-field detection
- Custom prompts trade schema rigidity for flexibility by requiring JSON output and flattening it dynamically
- Excel uploads are normalized to CSV immediately so the downstream pipeline stays consistent
- Durable fan-out/fan-in remains the concurrency model, with batch size controlled by `BATCH_SIZE`
- Output assembly is template-aware and appends columns instead of relying on a fixed Excel position
- The cold-email template remains backward compatible through `SYSTEM_PROMPT` and `build_user_prompt` aliases

See `PLAN.md` for the implementation history and the design changes that took the app from a single-purpose cold-email generator to a multi-template branch.
