// User-assigned managed identity used by every container: ACR pull, Key Vault, PostgreSQL (Entra)
// and read-only access to the monitored Azure subscriptions.
param location string
param namePrefix string
param tags object

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-id'
  location: location
  tags: tags
}

output id string = identity.id
output name string = identity.name
output principalId string = identity.properties.principalId
output clientId string = identity.properties.clientId
output tenantId string = identity.properties.tenantId
