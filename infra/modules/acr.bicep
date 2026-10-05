// Container registry. Admin user disabled; the managed identity pulls with AcrPull.
param location string
param namePrefix string
param tags object
param identityPrincipalId string

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: take('${replace(namePrefix, '-', '')}acr${uniqueString(resourceGroup().id)}', 50)
  location: location
  tags: tags
  sku: { name: 'Standard' }
  properties: {
    adminUserEnabled: false
  }
}

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, identityPrincipalId, acrPull)
  properties: {
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}

output name string = registry.name
output loginServer string = registry.properties.loginServer
