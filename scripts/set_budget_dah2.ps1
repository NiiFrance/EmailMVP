$sub = "8538aabe-e5de-4e8c-a29d-2914ecf1e65e"
$email = "france@cloudware.africa"
$budgetName = "EmailMVP-DAH2-Monthly-1000"

$body = @{
    properties = @{
        category  = "Cost"
        amount    = 1000
        timeGrain = "Monthly"
        timePeriod = @{
            startDate = "2026-06-01T00:00:00Z"
            endDate   = "2030-06-01T00:00:00Z"
        }
        notifications = @{
            Actual_50 = @{
                enabled = $true; operator = "GreaterThanOrEqualTo"; threshold = 50
                contactEmails = @($email); thresholdType = "Actual"
            }
            Actual_80 = @{
                enabled = $true; operator = "GreaterThanOrEqualTo"; threshold = 80
                contactEmails = @($email); thresholdType = "Actual"
            }
            Actual_100 = @{
                enabled = $true; operator = "GreaterThanOrEqualTo"; threshold = 100
                contactEmails = @($email); thresholdType = "Actual"
            }
            Forecasted_100 = @{
                enabled = $true; operator = "GreaterThanOrEqualTo"; threshold = 100
                contactEmails = @($email); thresholdType = "Forecasted"
            }
        }
    }
} | ConvertTo-Json -Depth 8

$tmp = Join-Path $env:TEMP "budget1000_body.json"
$body | Set-Content -Path $tmp -Encoding utf8

$uri = "https://management.azure.com/subscriptions/$sub/providers/Microsoft.Consumption/budgets/$budgetName`?api-version=2023-11-01"
Write-Host "PUT $uri"
az rest --method put --uri $uri --body "@$tmp" -o none

# verify
$b = az rest --method get --uri $uri -o json | ConvertFrom-Json
Write-Host ("Name:   {0}" -f $b.name)
Write-Host ("Amount: `${0} {1}" -f $b.properties.amount, $b.properties.timeGrain)
Write-Host ("Alerts: {0}" -f (($b.properties.notifications.PSObject.Properties.Name) -join ", "))
Write-Host ("Email:  {0}" -f $b.properties.notifications.Actual_50.contactEmails[0])
