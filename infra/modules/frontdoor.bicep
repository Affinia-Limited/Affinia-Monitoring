// Azure Front Door Premium + WAF in front of the web app, connected over Private Link to the
// internal Container Apps environment. HTTPS only; TLS 1.2 minimum.
param namePrefix string
param tags object
param location string
param webFqdn string
param containerAppsEnvironmentId string
@description('Optional custom domain, e.g. monitoring.contoso.com. Leave empty to use the azurefd.net host.')
param customDomain string = ''

resource waf 'Microsoft.Network/FrontDoorWebApplicationFirewallPolicies@2024-02-01' = {
  name: '${replace(namePrefix, '-', '')}waf'
  location: 'global'
  tags: tags
  sku: {
    name: 'Premium_AzureFrontDoor'
  }
  properties: {
    policySettings: {
      enabledState: 'Enabled'
      mode: 'Prevention'
      requestBodyCheck: 'Enabled'
    }
    managedRules: {
      managedRuleSets: [
        {
          ruleSetType: 'Microsoft_DefaultRuleSet'
          ruleSetVersion: '2.1'
          ruleSetAction: 'Block'
        }
        {
          ruleSetType: 'Microsoft_BotManagerRuleSet'
          ruleSetVersion: '1.1'
        }
      ]
    }
    customRules: {
      rules: [
        {
          name: 'RateLimitPerClient'
          priority: 100
          enabledState: 'Enabled'
          ruleType: 'RateLimitRule'
          rateLimitDurationInMinutes: 1
          rateLimitThreshold: 1200
          action: 'Block'
          matchConditions: [
            {
              matchVariable: 'RequestUri'
              operator: 'RegEx'
              matchValue: [
                '.*'
              ]
            }
          ]
        }
      ]
    }
  }
}

resource profile 'Microsoft.Cdn/profiles@2024-02-01' = {
  name: '${namePrefix}-afd'
  location: 'global'
  tags: tags
  sku: {
    name: 'Premium_AzureFrontDoor'
  }
  properties: {
    originResponseTimeoutSeconds: 120
  }
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2024-02-01' = {
  parent: profile
  name: '${namePrefix}-web'
  location: 'global'
  properties: {
    enabledState: 'Enabled'
  }
}

resource originGroup 'Microsoft.Cdn/profiles/originGroups@2024-02-01' = {
  parent: profile
  name: 'web'
  properties: {
    loadBalancingSettings: {
      sampleSize: 4
      successfulSamplesRequired: 3
      additionalLatencyInMilliseconds: 50
    }
    healthProbeSettings: {
      probePath: '/healthz'
      probeRequestType: 'GET'
      probeProtocol: 'Https'
      probeIntervalInSeconds: 60
    }
  }
}

resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2024-02-01' = {
  parent: originGroup
  name: 'container-app'
  properties: {
    hostName: webFqdn
    originHostHeader: webFqdn
    httpsPort: 443
    httpPort: 80
    priority: 1
    weight: 1000
    enforceCertificateNameCheck: true
    // The private endpoint connection must be approved on the Container Apps environment
    // after the first deployment (see infra/README.md).
    sharedPrivateLinkResource: {
      privateLink: {
        id: containerAppsEnvironmentId
      }
      groupId: 'managedEnvironments'
      privateLinkLocation: location
      requestMessage: 'Front Door private link for ${namePrefix}'
    }
  }
}

resource domain 'Microsoft.Cdn/profiles/customDomains@2024-02-01' = if (!empty(customDomain)) {
  parent: profile
  name: empty(customDomain) ? 'unused' : replace(customDomain, '.', '-')
  properties: {
    hostName: customDomain
    tlsSettings: {
      certificateType: 'ManagedCertificate'
      minimumTlsVersion: 'TLS12'
    }
  }
}

resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-02-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    originGroup: {
      id: originGroup.id
    }
    customDomains: empty(customDomain) ? [] : [
      {
        id: domain.id
      }
    ]
    supportedProtocols: [
      'Http'
      'Https'
    ]
    httpsRedirect: 'Enabled'
    forwardingProtocol: 'HttpsOnly'
    linkToDefaultDomain: 'Enabled'
    patternsToMatch: [
      '/*'
    ]
  }
  dependsOn: [
    origin
  ]
}

resource securityPolicy 'Microsoft.Cdn/profiles/securityPolicies@2024-02-01' = {
  parent: profile
  name: 'waf'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: {
        id: waf.id
      }
      associations: [
        {
          domains: concat([
            {
              id: endpoint.id
            }
          ], empty(customDomain) ? [] : [
            {
              id: domain.id
            }
          ])
          patternsToMatch: [
            '/*'
          ]
        }
      ]
    }
  }
}

output hostName string = endpoint.properties.hostName
output profileName string = profile.name
