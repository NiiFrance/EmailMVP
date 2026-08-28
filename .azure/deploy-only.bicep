targetScope = 'resourceGroup'

param functionAppName string
param staticWebAppName string

resource functionApp 'Microsoft.Web/sites@2023-12-01' existing = {
  name: functionAppName
}

resource staticWebApp 'Microsoft.Web/staticSites@2023-12-01' existing = {
  name: staticWebAppName
}

output functionAppId string = functionApp.id
output staticWebAppId string = staticWebApp.id
