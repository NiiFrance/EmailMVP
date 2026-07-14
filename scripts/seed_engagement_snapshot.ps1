param(
    [string]$Account = "azstocp2inqabawqu",
    [switch]$Cleanup
)
# Seed (or remove) a synthetic engagement snapshot so the learning loop can be E2E tested
# without sending real emails. RowKey uses a clearly-synthetic campaign id.
$ErrorActionPreference = "Stop"
$rk = "e2e-synthetic-0001"
if ($Cleanup) {
    az storage entity delete --table-name EngagementStats --account-name $Account --auth-mode login --partition-key snapshot --row-key $rk | Out-Null
    Write-Host "Deleted synthetic snapshot $rk"
    exit 0
}
$analytics = '{\"sent\": 120, \"delivered\": 118, \"opens\": 64, \"clicks\": 22, \"replies\": 9, \"unsubscribed\": 1, \"interested\": 5, \"maybe\": 2, \"notInterested\": 3}'
az storage entity insert --table-name EngagementStats --account-name $Account --auth-mode login --if-exists replace --entity `
    PartitionKey=snapshot RowKey=$rk `
    name="Cold Email - Original" status="Completed" `
    dateFrom="2026-04-15" dateTo="2026-07-14" `
    analytics=$analytics `
    updatedAt="2026-07-14T00:30:00Z" | Out-Null
Write-Host "Seeded synthetic snapshot $rk (Cold Email - Original, 120 sends)"
