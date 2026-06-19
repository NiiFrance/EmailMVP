param(
    [Parameter(Mandatory=$true)][string]$FrontendPath,
    [Parameter(Mandatory=$true)][string]$SwaName,
    [Parameter(Mandatory=$true)][string]$ResourceGroup,
    [string]$Subscription = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
)
$ErrorActionPreference = "Stop"
Write-Host "=== Fetching SWA deploy token for $SwaName ==="
$token = az staticwebapp secrets list --name $SwaName --resource-group $ResourceGroup --subscription $Subscription --query "properties.apiKey" -o tsv
if (-not $token) { Write-Host "Failed to get deploy token"; exit 1 }
Write-Host "Token length: $($token.Length)"
Write-Host "=== Deploying frontend ==="
npx @azure/static-web-apps-cli deploy $FrontendPath --deployment-token $token --env production
