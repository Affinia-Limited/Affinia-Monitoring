// Azure Communication Services Email for alert notifications.
// An Email Communication Service with an Azure-managed domain (sender DoNotReply@<guid>.azurecomm.net),
// linked to a Communication Services resource the app sends through with its managed identity.
// No keys or connection strings are used or exported.
//
// To send from your own domain, add a customer-managed domain to the email service, verify its DNS
// records, link it instead, and set EMAIL_SENDER_ADDRESS accordingly (see docs/monitoring.md).
param namePrefix string
param tags object
@description('Where the email data is stored at rest, e.g. UK, Europe, United States.')
param dataLocation string = 'UK'
@description('Principal ID of the managed identity that sends email (api and worker).')
param senderPrincipalId string

resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: '${namePrefix}-email'
  location: 'global'
  tags: tags
  properties: {
    dataLocation: dataLocation
  }
}

resource managedDomain 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: emailService
  name: 'AzureManagedDomain'
  location: 'global'
  tags: tags
  properties: {
    domainManagement: 'AzureManaged'
    userEngagementTracking: 'Disabled'
  }
}

resource communication 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: '${namePrefix}-acs-${uniqueString(resourceGroup().id)}'
  location: 'global'
  tags: tags
  properties: {
    dataLocation: dataLocation
    linkedDomains: [
      managedDomain.id
    ]
  }
}

// Sending email with Microsoft Entra authentication requires the identity to hold a role on the
// Communication Services resource that includes Microsoft.Communication/CommunicationServices/Write.
// Contributor, scoped to this one resource only, is the role Microsoft documents; a custom role with
// just the Communication Services read/write actions can replace it (see docs/monitoring.md).
var contributorRoleId = 'b24988ac-6181-4c3c-b0b2-ca2ea0e6d3a7'

resource sendRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(communication.id, senderPrincipalId, contributorRoleId)
  scope: communication
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRoleId)
    principalId: senderPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output endpoint string = 'https://${communication.properties.hostName}'
output senderAddress string = 'DoNotReply@${managedDomain.properties.mailFromSenderDomain}'
