// PostgreSQL Flexible Server: private access only (delegated subnet), Entra authentication only.
param location string
param namePrefix string
param tags object
param delegatedSubnetId string
param vnetId string
param identityPrincipalId string
param identityName string
@description('Object id of the Entra group that administers the server (break-glass / DBA access).')
param adminGroupObjectId string
param adminGroupName string
param skuName string = 'Standard_D2ds_v5'
param skuTier string = 'GeneralPurpose'
param storageSizeGB int = 64
param databaseName string = 'monitoring'

var serverName = '${namePrefix}-pg-${uniqueString(resourceGroup().id)}'

module dns 'private-dns.bicep' = {
  name: 'dns-postgres'
  params: { zoneName: '${serverName}.private.postgres.database.azure.com', vnetId: vnetId, tags: tags }
}

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  tags: tags
  sku: { name: skuName, tier: skuTier }
  properties: {
    version: '16'
    storage: { storageSizeGB: storageSizeGB, autoGrow: 'Enabled' }
    backup: { backupRetentionDays: 14, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: {
      delegatedSubnetResourceId: delegatedSubnetId
      privateDnsZoneArmResourceId: dns.outputs.id
      publicNetworkAccess: 'Disabled'
    }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: subscription().tenantId
    }
  }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: databaseName
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
}

resource requireTls 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'require_secure_transport'
  properties: { value: 'on', source: 'user-override' }
}

resource adminGroup 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = {
  parent: server
  name: adminGroupObjectId
  properties: {
    principalType: 'Group'
    principalName: adminGroupName
    tenantId: subscription().tenantId
  }
  dependsOn: [ database, requireTls ]
}

// The application identity is an Entra administrator so migrations can manage the schema.
// Tighten to a dedicated role with schema-owner rights once the schema is established.
resource appAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = {
  parent: server
  name: identityPrincipalId
  properties: {
    principalType: 'ServicePrincipal'
    principalName: identityName
    tenantId: subscription().tenantId
  }
  dependsOn: [ adminGroup ]
}

output fqdn string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
