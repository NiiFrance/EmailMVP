param(
    [ValidateSet("settings", "api", "registration", "frontend", "all")][string]$Stage = "all"
)
# Option B rollout: multi-tenant sign-in + server-side domain allowlist.
# Order matters: API allowlist first (safe while single-tenant), then flip the
# registration, then switch the SWA issuers via frontend redeploys.
$ErrorActionPreference = "Stop"
$sub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"   # DAH Subscription
$appId = "e7bcd28f-bb53-4795-8af5-52ba9ac67f49" # shared Entra app registration
$domains = "relianceinfosystems.com,cloudware.africa"
$scripts = $PSScriptRoot

$apps = @(
    @{ Name = "third";     Src = "C:\Users\EnochDevBox\Desktop\EmailMVP";           Fn = "azfnocp2inqabawqu"; Swa = "azswaocp2inqabawqu"; Rg = "rg-emailmvp-dah" },
    @{ Name = "reliance";  Src = "C:\Users\EnochDevBox\Desktop\EmailMVP-main";      Fn = "azfny76j3nkoga2rw"; Swa = "azsway76j3nkoga2rw"; Rg = "rg-emailmvp-eastus2" },
    @{ Name = "cloudware"; Src = "C:\Users\EnochDevBox\Desktop\EmailMVP-cloudware"; Fn = "azfnkhj2hcaa7fpcm"; Swa = "azswakhj2hcaa7fpcm"; Rg = "rg-emailmvp-cloudware-eastus2" }
)

if ($Stage -in @("settings", "all")) {
    foreach ($app in $apps) {
        Write-Host "=== [$($app.Name)] Setting ALLOWED_EMAIL_DOMAINS on $($app.Fn) ==="
        az functionapp config appsettings set --name $app.Fn --resource-group $app.Rg --subscription $sub `
            --settings "ALLOWED_EMAIL_DOMAINS=$domains" -o none
        Write-Host "done"
    }
}

if ($Stage -in @("api", "all")) {
    foreach ($app in $apps) {
        Write-Host "=== [$($app.Name)] Deploying API to $($app.Fn) ==="
        & "$scripts\redeploy_api.ps1" -ApiPath "$($app.Src)\api" -FunctionApp $app.Fn -ResourceGroup $app.Rg -Subscription $sub
    }
}

if ($Stage -in @("registration", "all")) {
    Write-Host "=== Flipping app registration $appId to multi-tenant ==="
    az ad app update --id $appId --sign-in-audience AzureADMultipleOrgs
    az ad app show --id $appId --query "signInAudience" -o tsv
}

if ($Stage -in @("frontend", "all")) {
    foreach ($app in $apps) {
        Write-Host "=== [$($app.Name)] Deploying frontend to $($app.Swa) ==="
        & "$scripts\deploy_frontend.ps1" -FrontendPath "$($app.Src)\frontend" -SwaName $app.Swa -ResourceGroup $app.Rg -Subscription $sub
    }
}

Write-Host ""
Write-Host "Reliance admin-consent URL (send to a Reliance admin if user self-consent is blocked):"
Write-Host "https://login.microsoftonline.com/0b60fed4-5fc9-409d-95f2-271114f4c86f/adminconsent?client_id=$appId"
