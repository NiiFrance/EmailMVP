$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$uri = "https://management.azure.com/subscriptions/$sub/providers/Microsoft.Consumption/budgets/EmailMVP-DAH-Monthly-50?api-version=2023-11-01"
$b = az rest --method get --uri $uri -o json | ConvertFrom-Json
Write-Host ("Name:          {0}" -f $b.name)
Write-Host ("Amount:        `${0} {1}" -f $b.properties.amount, $b.properties.timeGrain)
Write-Host ("Current spend: {0} {1}" -f $b.properties.currentSpend.amount, $b.properties.currentSpend.unit)
Write-Host ("Alert rules:   {0}" -f (($b.properties.notifications.PSObject.Properties.Name) -join ", "))
Write-Host ("Alert email:   {0}" -f $b.properties.notifications.Actual_50.contactEmails[0])
