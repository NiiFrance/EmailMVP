$ErrorActionPreference = "Stop"
$oldSub = "1026bf75-8146-43b4-8f2c-32e69ef52837"
$dahSub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$rg = "DevMachine"

$token = az account get-access-token --query accessToken -o tsv
$headers = @{ Authorization = "Bearer $token"; "Content-Type" = "application/json" }

$ids = az resource list --resource-group $rg --subscription $oldSub --query "[].id" -o json | ConvertFrom-Json
$ids = $ids | ForEach-Object { $_ -replace '/resourceGroups/DEVMACHINE/', '/resourceGroups/DevMachine/' }
Write-Host "Moving $($ids.Count) resources..."

$body = @{
    resources = @($ids)
    targetResourceGroup = "/subscriptions/$dahSub/resourceGroups/$rg"
} | ConvertTo-Json -Depth 5

$uri = "https://management.azure.com/subscriptions/$oldSub/resourceGroups/$rg/moveResources?api-version=2021-04-01"
$resp = Invoke-WebRequest -Uri $uri -Method Post -Headers $headers -Body $body -UseBasicParsing
Write-Host "Initial response: $($resp.StatusCode)"
$pollUrl = $resp.Headers["Location"]
if (-not $pollUrl) { $pollUrl = $resp.Headers["Azure-AsyncOperation"] }
if ($pollUrl -is [array]) { $pollUrl = $pollUrl[0] }
Write-Host "Polling: $pollUrl"

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 20
    try {
        $p = Invoke-WebRequest -Uri $pollUrl -Method Get -Headers @{ Authorization = "Bearer $token" } -UseBasicParsing
        if ($p.StatusCode -eq 204) { Write-Host "[poll $i] 204 No Content -> MOVE SUCCEEDED"; break }
        if ($p.StatusCode -eq 200) {
            $content = $p.Content
            if ($content) {
                Write-Host "[poll $i] 200 with body:"
                Write-Host $content
            } else {
                Write-Host "[poll $i] 200 (empty) -> MOVE SUCCEEDED"
            }
            break
        }
        Write-Host "[poll $i] $($p.StatusCode) - still running"
    } catch {
        $code = $null; try { $code = [int]$_.Exception.Response.StatusCode } catch {}
        Write-Host "[poll $i] ERROR HTTP $code"
        if ($_.ErrorDetails.Message) { Write-Host $_.ErrorDetails.Message }
        break
    }
}
