$j = curl.exe -s "https://wonderful-bush-0798ba40f.7.azurestaticapps.net/api/templates" | ConvertFrom-Json
Write-Host ("Third-app templates: " + (($j.templates | ForEach-Object { $_.id }) -join ", "))
Write-Host ("Count: " + $j.templates.Count)
