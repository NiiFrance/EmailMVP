$ErrorActionPreference = "Continue"
$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$regions = @("eastus2", "eastus", "westus", "westus3", "swedencentral", "uksouth", "francecentral", "westeurope", "southcentralus", "northcentralus")
foreach ($r in $regions) {
    $u = az cognitiveservices usage list --location $r --subscription $sub --query "[?contains(name.value, 'gpt-5.5')].{name:name.value,current:currentValue,limit:limit}" -o json 2>$null | ConvertFrom-Json
    $hits = $u | Where-Object { $_.limit -gt 0 }
    if ($hits) {
        Write-Host "=== $r ==="
        $hits | ForEach-Object { Write-Host ("  {0}  limit={1} used={2}" -f $_.name, $_.limit, $_.current) }
    } else {
        Write-Host "$r : no gpt-5.5 quota"
    }
}
