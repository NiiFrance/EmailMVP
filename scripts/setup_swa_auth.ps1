param(
    [Parameter(Mandatory = $true)][string]$SwaName,
    [Parameter(Mandatory = $true)][string]$ResourceGroup,
    [Parameter(Mandatory = $true)][string]$RedirectHost,
    [Parameter(Mandatory = $true)][string]$SecretLabel
)
# Adds a redirect URI for a SWA to the shared Entra app registration, mints a NEW
# client secret (append — never resets existing ones), and stores AAD settings on
# the SWA via ARM (body file, so the secret is never on a command line).
$ErrorActionPreference = "Stop"
$sub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"
$appId = "e7bcd28f-bb53-4795-8af5-52ba9ac67f49"

# 1. Add redirect URI (idempotent merge)
$existing = az ad app show --id $appId --query "web.redirectUris" -o json | ConvertFrom-Json
$newUri = "https://$RedirectHost/.auth/login/aad/callback"
if ($existing -notcontains $newUri) {
    $all = @($existing) + $newUri
    $uriArgs = $all | ForEach-Object { $_ }
    az ad app update --id $appId --web-redirect-uris @uriArgs
    Write-Host "redirect URI added: $newUri"
} else {
    Write-Host "redirect URI already present"
}

# 2. Mint an additional client secret (append!)
$appObjectId = az ad app show --id $appId --query "id" -o tsv
$secretBody = Join-Path $env:TEMP "secret_body.json"
@{ passwordCredential = @{ displayName = $SecretLabel; endDateTime = (Get-Date).AddYears(2).ToString("yyyy-MM-ddTHH:mm:ssZ") } } | ConvertTo-Json -Depth 3 | Set-Content $secretBody -Encoding UTF8
$secretResp = az rest --method POST --uri "https://graph.microsoft.com/v1.0/applications/$appObjectId/addPassword" --body "@$secretBody" --headers "Content-Type=application/json" -o json | ConvertFrom-Json
Remove-Item $secretBody -Force
if (-not $secretResp.secretText) { throw "secret creation failed" }
Write-Host "secret minted (label: $SecretLabel)"

# 3. Store SWA app settings via ARM body file
$bodyFile = Join-Path $env:TEMP "swa_auth_settings.json"
@{ properties = @{ AAD_CLIENT_ID = $appId; AAD_CLIENT_SECRET = $secretResp.secretText } } | ConvertTo-Json | Set-Content $bodyFile -Encoding UTF8
$secretResp = $null
az rest --method PUT --uri "https://management.azure.com/subscriptions/$sub/resourceGroups/$ResourceGroup/providers/Microsoft.Web/staticSites/$SwaName/config/appsettings?api-version=2022-03-01" --body "@$bodyFile" --output none
Remove-Item $bodyFile -Force
Write-Host "SWA settings stored on $SwaName"
az staticwebapp appsettings list --name $SwaName --resource-group $ResourceGroup --subscription $sub -o json | ConvertFrom-Json | ForEach-Object { $_.properties.PSObject.Properties.Name }
