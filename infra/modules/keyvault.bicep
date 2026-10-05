// Key Vault: RBAC authorisation, purge protection, private endpoint only.
param location string
param namePrefix string
param tags object
param identityPrincipalId string
param vnetId string
param privateEndpointSubnetId string

var vaultName = take('${replace(namePrefix, '-', '')}kv${uniqueString(resourceGroup().id)}', 24)
var keyVaultSecretsUser = '4633458b-17de-408a-b874-0445c86b69e6'

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: vaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

resource secretsUser 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, identityPrincipalId, keyVaultSecretsUser)
  properties: {
    principalId: identityPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyVaultSecretsUser)
  }
}

module dns 'private-dns.bicep' = {
  name: 'dns-keyvault'
  params: { zoneName: 'privatelink.vaultcore.azure.net', vnetId: vnetId, tags: tags }
}

resource endpoint 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: '${vaultName}-pe'
  location: location
  tags: tags
  properties: {
    subnet: { id: privateEndpointSubnetId }
    privateLinkServiceConnections: [
      { name: 'vault', properties: { privateLinkServiceId: vault.id, groupIds: [ 'vault' ] } }
    ]
  }
}

resource dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [ { name: 'vault', properties: { privateDnsZoneId: dns.outputs.id } } ]
  }
}

output name string = vault.name
output uri string = vault.properties.vaultUri
