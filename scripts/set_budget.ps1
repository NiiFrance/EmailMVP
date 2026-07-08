$sub = "147c97bd-bed0-4b4c-b031-fc5a6e9a4cd6"
$email = "enoch@cloudware.africa"
$budgetName = "EmailMVP-DAH-Monthly-50"

$body = @{
    properties = @{
        category  = "Cost"
        amount    = 50
        timeGrain = "Monthly"
        timePeriod = @{
            startDate = "2026-06-01T00:00:00Z"
            endDate   = "2030-06-01T00:00:00Z"
        }
        notifications = @{
            Actual_50 = @{
                enabled       = $true
                operator      = "GreaterThanOrEqualTo"
                threshold     = 50
                contactEmails = @($email)
                thresholdType = "Actual"
            }
            Actual_80 = @{
                enabled       = $true
                operator      = "GreaterThanOrEqualTo"
                threshold     = 80
                contactEmails = @($email)
                thresholdType = "Actual"
            }
            Actual_100 = @{
                enabled       = $true
                operator      = "GreaterThanOrEqualTo"
                threshold     = 100
                contactEmails = @($email)
                thresholdType = "Actual"
            }
            Forecasted_100 = @{
                enabled       = $true
                operator      = "GreaterThanOrEqualTo"
                threshold     = 100
                contactEmails = @($email)
                thresholdType = "Forecasted"
            }
        }
    }
} | ConvertTo-Json -Depth 8

$tmp = Join-Path $env:TEMP "budget_body.json"
$body | Set-Content -Path $tmp -Encoding utf8

$uri = "https://management.azure.com/subscriptions/$sub/providers/Microsoft.Consumption/budgets/$budgetName`?api-version=2023-11-01"
Write-Host "PUT $uri"
az rest --method put --uri $uri --body "@$tmp" --query "{name:name,amount:properties.amount,grain:properties.timeGrain}" -o json
