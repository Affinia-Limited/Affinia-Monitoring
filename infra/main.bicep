// Azure Monitoring Platform - production deployment (resource group scope).
//
//   Internet -> Front Door Premium + WAF -> (Private Link) -> Container Apps (internal VNet)
//     web (nginx, React) -> api (FastAPI) -> PostgreSQL Flexible (private) / Redis (private) / Key Vault (private)
//     worker + beat (Celery) and a migration job share the api image configuration.
//
// Two-phase deployment (see infra/README.md): deployApps=false creates the foundation (incl. ACR)
// so images can be pushed; deployApps=true then deploys the container apps and Front Door.

targetScope = 'resourceGroup'

@description('Short prefix for resource names, e.g. amp-prod.')
@minLength(3)
@maxLength(16)
param namePrefix string

param location string = resourceGroup().location

@description('Deploy container apps and Front Door (requires images in ACR).')
param deployApps bool = false

@description('Container image tag to deploy (typically the Git commit SHA).')
param imageTag string = 'latest'

@description('Entra tenant for user sign-in.')
param entraTenantId string

@description('Client id of the API app registration.')
param entraClientId string

@description('Expected token audience, e.g. api://<api-client-id>.')
param entraAudience string

@description('Object id of the Entra group administering PostgreSQL.')
param postgresAdminGroupObjectId string

@description('Display name of that Entra group.')
param postgresAdminGroupName string

@description('Entra object ids granted Super Admin on first sign-in.')
param bootstrapSuperAdminOids array = []

@description('Optional custom domain for Front Door.')
param customDomain string = ''

param tags object = {
  application: 'azure-monitoring-platform'
  managedBy: 'bicep'
}

module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring'
  params: { location: location, namePrefix: namePrefix, tags: tags }
}

module identity 'modules/identity.bicep' = {
  name: 'identity'
  params: { location: location, namePrefix: namePrefix, tags: tags }
}

module network 'modules/network.bicep' = {
  name: 'network'
  params: { location: location, namePrefix: namePrefix, tags: tags }
}

module keyVault 'modules/keyvault.bicep' = {
  name: 'keyvault'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    identityPrincipalId: identity.outputs.principalId
    vnetId: network.outputs.id
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
  }
}

module registry 'modules/acr.bicep' = {
  name: 'acr'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    identityPrincipalId: identity.outputs.principalId
  }
}

module postgres 'modules/postgres.bicep' = {
  name: 'postgres'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    delegatedSubnetId: network.outputs.postgresSubnetId
    vnetId: network.outputs.id
    identityPrincipalId: identity.outputs.principalId
    identityName: identity.outputs.name
    adminGroupObjectId: postgresAdminGroupObjectId
    adminGroupName: postgresAdminGroupName
  }
}

module redis 'modules/redis.bicep' = {
  name: 'redis'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    vnetId: network.outputs.id
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    keyVaultName: keyVault.outputs.name
  }
}

module apps 'modules/containerapps.bicep' = if (deployApps) {
  name: 'containerapps'
  params: {
    location: location
    namePrefix: namePrefix
    tags: tags
    infrastructureSubnetId: network.outputs.appsSubnetId
    logAnalyticsWorkspaceName: monitoring.outputs.workspaceName
    identityId: identity.outputs.id
    identityClientId: identity.outputs.clientId
    registryLoginServer: registry.outputs.loginServer
    imageTag: imageTag
    keyVaultUri: keyVault.outputs.uri
    redisSecretUri: redis.outputs.secretUri
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    postgresFqdn: postgres.outputs.fqdn
    postgresDatabase: postgres.outputs.databaseName
    postgresUser: identity.outputs.name
    entraTenantId: entraTenantId
    entraClientId: entraClientId
    entraAudience: entraAudience
    bootstrapSuperAdminOids: bootstrapSuperAdminOids
    corsOrigins: empty(customDomain) ? [] : [ 'https://${customDomain}' ]
  }
}

module frontDoor 'modules/frontdoor.bicep' = if (deployApps) {
  name: 'frontdoor'
  params: {
    namePrefix: namePrefix
    tags: tags
    location: location
    webFqdn: apps!.outputs.webFqdn
    containerAppsEnvironmentId: apps!.outputs.environmentId
    customDomain: customDomain
  }
}

output registryName string = registry.outputs.name
output registryLoginServer string = registry.outputs.loginServer
output keyVaultName string = keyVault.outputs.name
output identityClientId string = identity.outputs.clientId
output identityPrincipalId string = identity.outputs.principalId
output containerAppsEnvironmentName string = deployApps ? apps!.outputs.environmentName : ''
output apiAppName string = deployApps ? apps!.outputs.apiName : ''
output workerAppName string = deployApps ? apps!.outputs.workerName : ''
output beatAppName string = deployApps ? apps!.outputs.beatName : ''
output webAppName string = deployApps ? apps!.outputs.webName : ''
output migrateJobName string = deployApps ? apps!.outputs.migrateJobName : ''
output frontDoorHostName string = deployApps ? frontDoor!.outputs.hostName : ''
