$dahSub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$oldSub = "1026bf75-8146-43b4-8f2c-32e69ef52837"
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 30
    $r = az resource list --resource-group DevMachine --subscription $dahSub --query "length(@)" -o tsv
    $o = az resource list --resource-group DevMachine --subscription $oldSub --query "length(@)" -o tsv 2>$null
    if (-not $o) { $o = 0 }
    Write-Host ("[poll {0}] DAH={1} old={2}" -f $i, $r, $o)
    if ([int]$r -ge 6 -and [int]$o -eq 0) { Write-Host "MOVE FINISHED"; break }
}
Write-Host "=== Final: DAH/DevMachine ==="
az resource list --resource-group DevMachine --subscription $dahSub --query "[].name" -o tsv
