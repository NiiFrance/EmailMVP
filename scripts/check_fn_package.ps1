param(
	[string]$Subscription = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e",
	[string]$ResourceGroup = "rg-emailmvp-dah",
	[string]$FunctionApp = "azfnocp2inqabawqu"
)

# Check what package the function app is actually running.
$ErrorActionPreference = "Stop"

$creds = az functionapp deployment list-publishing-credentials --name $FunctionApp --resource-group $ResourceGroup --subscription $Subscription --query "{u:publishingUserName, p:publishingPassword}" -o json | ConvertFrom-Json
$pair = "$($creds.u):$($creds.p)"
$auth = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))

Write-Host "=== SitePackages directory ==="
$pkgs = Invoke-RestMethod -Uri "https://$FunctionApp.scm.azurewebsites.net/api/vfs/data/SitePackages/" -Headers @{ Authorization = $auth }
$pkgs | Sort-Object mtime -Descending | Select-Object -First 5 name, mtime | Format-Table

Write-Host "=== packagename.txt (active package) ==="
Invoke-RestMethod -Uri "https://$FunctionApp.scm.azurewebsites.net/api/vfs/data/SitePackages/packagename.txt" -Headers @{ Authorization = $auth }

Write-Host "=== WEBSITE_RUN_FROM_PACKAGE setting ==="
az functionapp config appsettings list --name $FunctionApp --resource-group $ResourceGroup --subscription $Subscription --query "[?name=='WEBSITE_RUN_FROM_PACKAGE'].value" -o tsv
