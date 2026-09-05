param(
    [Parameter(Mandatory=$true)][string]$ApiPath,
    [Parameter(Mandatory=$true)][string]$FunctionApp,
    [Parameter(Mandatory=$true)][string]$ResourceGroup,
    [string]$Subscription = "1026bf75-8146-43b4-8f2c-32e69ef52837",
    [switch]$PackageOnly
)
$ErrorActionPreference = "Stop"
$sub = $Subscription

$staging = Join-Path $env:TEMP ("deploy_" + $FunctionApp)
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }
New-Item -ItemType Directory -Path $staging | Out-Null

# Copy api contents excluding tests, __pycache__, .venv
Get-ChildItem -Path $ApiPath -Force | Where-Object {
    $_.Extension -eq ".py" -or $_.Name -in @("host.json", "requirements.txt", "prompts")
} | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $staging -Recurse -Force
}

# Remove any nested __pycache__
Get-ChildItem -Path $staging -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

$zip = Join-Path $env:TEMP ($FunctionApp + ".zip")
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zip -Force
Write-Host "Zip created: $zip ($((Get-Item $zip).Length) bytes)"
if ($PackageOnly) { return }

Write-Host "Deploying to $FunctionApp ..."
az functionapp deployment source config-zip `
    --name $FunctionApp `
    --resource-group $ResourceGroup `
    --subscription $sub `
    --src $zip `
    --build-remote true `
    --timeout 600
Write-Host "Deploy command returned exit code $LASTEXITCODE"
if ($LASTEXITCODE -ne 0) { throw "Deployment failed for $FunctionApp." }
