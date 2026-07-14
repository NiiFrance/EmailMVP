# Check what package the function app is actually running and force a sync
$ErrorActionPreference = "Stop"
$sub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"
$rg = "rg-emailmvp-dah"
$fn = "azfnocp2inqabawqu"

$creds = az functionapp deployment list-publishing-credentials --name $fn --resource-group $rg --subscription $sub --query "{u:publishingUserName, p:publishingPassword}" -o json | ConvertFrom-Json
$pair = "$($creds.u):$($creds.p)"
$auth = "Basic " + [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($pair))

Write-Host "=== SitePackages directory ==="
$pkgs = Invoke-RestMethod -Uri "https://$fn.scm.azurewebsites.net/api/vfs/data/SitePackages/" -Headers @{ Authorization = $auth }
$pkgs | Sort-Object mtime -Descending | Select-Object -First 5 name, mtime | Format-Table

Write-Host "=== packagename.txt (active package) ==="
Invoke-RestMethod -Uri "https://$fn.scm.azurewebsites.net/api/vfs/data/SitePackages/packagename.txt" -Headers @{ Authorization = $auth }

Write-Host "=== WEBSITE_RUN_FROM_PACKAGE setting ==="
az functionapp config appsettings list --name $fn --resource-group $rg --subscription $sub --query "[?name=='WEBSITE_RUN_FROM_PACKAGE'].value" -o tsv
