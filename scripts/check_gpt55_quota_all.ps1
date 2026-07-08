$ErrorActionPreference = "Continue"
$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
# All regions where gpt-5.5 model is offered
$regions = @(
    "eastus2","eastus","westus","westus2","westus3","centralus","southcentralus","northcentralus","westcentralus",
    "canadaeast","canadacentral","brazilsouth",
    "swedencentral","norwayeast","polandcentral","switzerlandnorth","germanywestcentral",
    "uksouth","francecentral","westeurope","spaincentral","italynorth",
    "australiaeast","japaneast","koreacentral","southindia","southeastasia",
    "eastus2euap"
)
$found = $false
foreach ($r in $regions) {
    $u = az cognitiveservices usage list --location $r --subscription $sub --query "[?contains(name.value, 'gpt-5.5')].{name:name.value,current:currentValue,limit:limit}" -o json 2>$null | ConvertFrom-Json
    $hits = $u | Where-Object { $_.limit -gt 0 }
    if ($hits) {
        $found = $true
        Write-Host "=== $r ==="
        $hits | ForEach-Object { Write-Host ("  {0}  limit={1} used={2}" -f $_.name, $_.limit, $_.current) }
    }
}
if (-not $found) { Write-Host "NO gpt-5.5 quota in any region." }
