$ErrorActionPreference = "Stop"
$srcSub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$dstSub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"
$rg = "DevMachine"

Write-Host "=== Ensuring target RG exists ==="
az group create --name $rg --location westeurope --subscription $dstSub --query "properties.provisioningState" -o tsv

Write-Host "=== Disassociating + deleting public IP (cannot move cross-sub) ==="
az network nic ip-config update --nic-name enochdevmachine419_z3 --name ipconfig1 --resource-group $rg --subscription $srcSub --remove publicIpAddress -o none
az network public-ip delete --name EnochDevMachine-ip --resource-group $rg --subscription $srcSub
Write-Host "Public IP removed."

Write-Host "=== Collecting remaining resource IDs ==="
$ids = az resource list --resource-group $rg --subscription $srcSub --query "[].id" -o json | ConvertFrom-Json
$ids = $ids | ForEach-Object { $_ -replace '/resourceGroups/DEVMACHINE/', '/resourceGroups/DevMachine/' }
Write-Host "Moving $($ids.Count) resources:"
$ids | ForEach-Object { Write-Host "  $_" }

$token = az account get-access-token --subscription $srcSub --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }
$body = @{
    resources = @($ids)
    targetResourceGroup = "/subscriptions/$dstSub/resourceGroups/$rg"
} | ConvertTo-Json -Depth 5

$uri = "https://management.azure.com/subscriptions/$srcSub/resourceGroups/$rg/moveResources?api-version=2021-04-01"
$resp = Invoke-WebRequest -Uri $uri -Method Post -Headers $headers -Body $body -UseBasicParsing
Write-Host "Initial response: $($resp.StatusCode)"
$pollUrl = $resp.Headers["Location"]
if ($pollUrl -is [array]) { $pollUrl = $pollUrl[0] }

for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 20
    try {
        $p = Invoke-WebRequest -Uri $pollUrl -Method Get -Headers @{ Authorization = "Bearer $token" } -UseBasicParsing
        if ($p.StatusCode -eq 204 -or ($p.StatusCode -eq 200 -and -not $p.Content)) { Write-Host "[poll $i] MOVE SUCCEEDED"; break }
        if ($p.StatusCode -eq 200) { Write-Host "[poll $i] 200: $($p.Content)"; break }
        Write-Host "[poll $i] $($p.StatusCode) - running"
    } catch {
        $code = $null; try { $code = [int]$_.Exception.Response.StatusCode } catch {}
        Write-Host "[poll $i] HTTP $code"
        if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
        break
    }
}

Write-Host "=== Target DevMachine resources ==="
az resource list --resource-group $rg --subscription $dstSub --query "[].name" -o tsv
Write-Host "=== Source remaining ==="
$left = az resource list --resource-group $rg --subscription $srcSub --query "[].name" -o tsv 2>$null
if ($left) { Write-Host $left } else { Write-Host "(empty)" }
