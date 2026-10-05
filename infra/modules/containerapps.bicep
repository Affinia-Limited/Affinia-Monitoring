// Container Apps environment (internal, VNet-integrated) with api, worker, beat, web and a migration job.
param location string
param namePrefix string
param tags object
param infrastructureSubnetId string
param logAnalyticsWorkspaceName string
param identityId string
param identityClientId string
param registryLoginServer string
param imageTag string
param keyVaultUri string
param redisSecretUri string
param appInsightsConnectionString string
param postgresFqdn string
param postgresDatabase string
param postgresUser string
param entraTenantId string
param entraClientId string
param entraAudience string
param bootstrapSuperAdminOids array = []
param corsOrigins array = []
param syncIntervalMinutes int = 15

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' existing = {
  name: logAnalyticsWorkspaceName
}

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-cae'
  location: location
  tags: tags
  properties: {
    vnetConfiguration: {
      internal: true
      infrastructureSubnetId: infrastructureSubnetId
    }
    workloadProfiles: [
      {
        name: 'Consumption'
        workloadProfileType: 'Consumption'
      }
    ]
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: workspace.properties.customerId
        sharedKey: workspace.listKeys().primarySharedKey
      }
    }
    zoneRedundant: false
  }
}

var backendImage = '${registryLoginServer}/monitoring-backend:${imageTag}'
var workerImage = '${registryLoginServer}/monitoring-worker:${imageTag}'
var webImage = '${registryLoginServer}/monitoring-frontend:${imageTag}'
var apiName = '${namePrefix}-api'

var identityBlock = {
  type: 'UserAssigned'
  userAssignedIdentities: {
    '${identityId}': {}
  }
}
var registries = [
  {
    server: registryLoginServer
    identity: identityId
  }
]
// Key Vault reference: the value is resolved by the platform with the managed identity.
var secrets = [
  {
    name: 'redis-url'
    keyVaultUrl: redisSecretUri
    identity: identityId
  }
]

// Non-secret configuration shared by api, worker, beat and the migration job.
// PostgreSQL uses Entra authentication (no password): the app identity requests an access token.
var sharedEnv = [
  { name: 'ENVIRONMENT', value: 'production' }
  { name: 'LOG_LEVEL', value: 'INFO' }
  { name: 'AUTH_MODE', value: 'entra' }
  { name: 'AZURE_PROVIDER', value: 'azure' }
  { name: 'TASK_BACKEND', value: 'celery' }
  { name: 'DATABASE_URL', value: 'postgresql+asyncpg://${postgresUser}@${postgresFqdn}:5432/${postgresDatabase}?ssl=require' }
  { name: 'DATABASE_AUTH', value: 'entra' }
  { name: 'REDIS_URL', secretRef: 'redis-url' }
  { name: 'ENTRA_TENANT_ID', value: entraTenantId }
  { name: 'ENTRA_CLIENT_ID', value: entraClientId }
  { name: 'ENTRA_AUDIENCE', value: entraAudience }
  { name: 'AZURE_TENANT_ID', value: tenant().tenantId }
  { name: 'AZURE_CLIENT_ID', value: identityClientId }
  { name: 'KEY_VAULT_URL', value: keyVaultUri }
  { name: 'BOOTSTRAP_SUPER_ADMIN_OIDS', value: join(bootstrapSuperAdminOids, ',') }
  { name: 'CORS_ORIGINS', value: join(corsOrigins, ',') }
  { name: 'TRUSTED_PROXY_COUNT', value: '2' }
  { name: 'SYNC_INTERVAL_MINUTES', value: string(syncIntervalMinutes) }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
]

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: apiName
  location: location
  tags: tags
  identity: identityBlock
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: registries
      secrets: secrets
      ingress: {
        // Reachable only from inside the environment (the web app proxies /api to it).
        external: false
        targetPort: 8000
        transport: 'http'
        allowInsecure: true
      }
    }
    template: {
      containers: [
        {
          name: 'api'
          image: backendImage
          env: sharedEnv
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/live'
                port: 8000
              }
              periodSeconds: 30
            }
            {
              type: 'Readiness'
              httpGet: {
                path: '/ready'
                port: 8000
              }
              periodSeconds: 15
            }
          ]
        }
      ]
      scale: {
        minReplicas: 2
        maxReplicas: 6
        rules: [
          {
            name: 'http'
            http: {
              metadata: {
                concurrentRequests: '50'
              }
            }
          }
        ]
      }
    }
  }
}

resource worker 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-worker'
  location: location
  tags: tags
  identity: identityBlock
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: registries
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'worker'
          image: workerImage
          env: sharedEnv
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 3
      }
    }
  }
}

resource beat 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-beat'
  location: location
  tags: tags
  identity: identityBlock
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: registries
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'beat'
          image: workerImage
          command: [
            'celery'
          ]
          args: [
            '-A'
            'app.workers.celery_app'
            'beat'
            '--loglevel=INFO'
            '--schedule'
            '/tmp/celerybeat-schedule'
          ]
          env: sharedEnv
          resources: {
            cpu: json('0.25')
            memory: '0.5Gi'
          }
        }
      ]
      // Exactly one scheduler, otherwise periodic jobs would be enqueued twice.
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
}

resource web 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-web'
  location: location
  tags: tags
  identity: identityBlock
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      activeRevisionsMode: 'Single'
      registries: registries
      ingress: {
        // "External" inside an internal environment = reachable from the VNet / Front Door Private Link only.
        external: true
        targetPort: 8080
        transport: 'http'
        allowInsecure: false
      }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webImage
          env: [
            {
              name: 'BACKEND_UPSTREAM'
              value: 'http://${apiName}'
            }
          ]
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          probes: [
            {
              type: 'Liveness'
              httpGet: {
                path: '/healthz'
                port: 8080
              }
              periodSeconds: 30
            }
          ]
        }
      ]
      scale: {
        minReplicas: 2
        maxReplicas: 4
      }
    }
  }
  dependsOn: [
    api
  ]
}

resource migrate 'Microsoft.App/jobs@2024-03-01' = {
  name: '${namePrefix}-migrate'
  location: location
  tags: tags
  identity: identityBlock
  properties: {
    environmentId: environment.id
    workloadProfileName: 'Consumption'
    configuration: {
      triggerType: 'Manual'
      replicaTimeout: 1800
      replicaRetryLimit: 0
      manualTriggerConfig: {
        parallelism: 1
        replicaCompletionCount: 1
      }
      registries: registries
      secrets: secrets
    }
    template: {
      containers: [
        {
          name: 'migrate'
          image: backendImage
          command: [
            'alembic'
          ]
          args: [
            'upgrade'
            'head'
          ]
          env: sharedEnv
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
        }
      ]
    }
  }
}

output environmentId string = environment.id
output environmentName string = environment.name
output webFqdn string = web.properties.configuration.ingress.fqdn
output apiName string = api.name
output workerName string = worker.name
output beatName string = beat.name
output webName string = web.name
output migrateJobName string = migrate.name
