// Azure Cache for Redis: TLS 1.2 only, no public network access, private endpoint.
// The connection URL is written to Key Vault and referenced by the container apps; it never
// appears in source control, pipeline logs or the database.
param location string
param namePrefix string
param tags object
param vnetId string
param privateEndpointSubnetId string
param keyVaultName string

resource redis 'Microsoft.Cache/redis@2024-03-01' = {
  name: '${namePrefix}-redis-${uniqueString(resourceGroup().id)}'
  location: location
  tags: tags
  properties: {
    sku: { name: 'Standard', family: 'C', capacity: 1 }
    enableNonSslPort: false
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Disabled'
    redisVersion: '6'
  }
}

module dns 'private-dns.bicep' = {
  name: 'dns-redis'
  params: { zoneName: 'privatelink.redis.cache.windows.net', vnetId: vnetId, tags: tags }
}

resource endpoint 'Microsoft.Network/privateEndpoints@2024-01-01' = {
  name: '${redis.name}-pe'
  location: location
  tags: tags
  properties: {
    subnet: { id: privateEndpointSubnetId }
    privateLinkServiceConnections: [
      { name: 'redis', properties: { privateLinkServiceId: redis.id, groupIds: [ 'redisCache' ] } }
    ]
  }
}

resource dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-01-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [ { name: 'redis', properties: { privateDnsZoneId: dns.outputs.id } } ]
  }
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource redisUrl 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'redis-url'
  properties: {
    value: 'rediss://:${redis.listKeys().primaryKey}@${redis.properties.hostName}:${redis.properties.sslPort}/0'
    contentType: 'text/plain'
  }
}

output hostName string = redis.properties.hostName
output secretUri string = redisUrl.properties.secretUri
