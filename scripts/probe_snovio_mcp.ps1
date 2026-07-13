# Discovery probe: register an OAuth client with Snov.io MCP and probe the MCP endpoint
$ErrorActionPreference = "Stop"
$regBody = @{
    client_name   = "Cloudware Email Campaign Generator (test)"
    redirect_uris = @("https://ashy-ocean-0a8e5f60f.7.azurestaticapps.net/api/snovio/mcp/callback")
    grant_types   = @("authorization_code", "refresh_token")
    response_types = @("code")
    token_endpoint_auth_method = "none"
    scope = "mcp"
} | ConvertTo-Json
$reg = Invoke-RestMethod -Uri "https://app.snov.io/back/mcp/oauth/register" -Method Post -Body $regBody -ContentType "application/json"
Write-Host "REGISTERED client_id: $($reg.client_id)"
$reg | ConvertTo-Json -Depth 4

# Probe MCP endpoint unauthenticated (expect 401)
try {
    $init = @{ jsonrpc = "2.0"; id = 1; method = "initialize"; params = @{ protocolVersion = "2025-03-26"; capabilities = @{}; clientInfo = @{ name = "probe"; version = "0.1" } } } | ConvertTo-Json -Depth 5
    Invoke-RestMethod -Uri "https://mcp.snov.io/mcp" -Method Post -Body $init -ContentType "application/json" -Headers @{ Accept = "application/json, text/event-stream" }
} catch {
    Write-Host "MCP unauthenticated: HTTP $($_.Exception.Response.StatusCode.value__)"
}
