targetScope = 'resourceGroup'

param location string = resourceGroup().location
param baseName string = 'cadrenza'
param containerEnvironmentName string
param acrName string
param image string
param serviceBusName string
param generalQueueName string = 'formation-pipeline'
param aiQueueName string = 'formation-ai'
param audioQueueName string = 'formation-audio'
param aiIdentityName string
param audioIdentityName string
param fishAudioVoiceId string = '90a39a3f3c0a45c38502fa1d99dabf96'

@minValue(1)
@maxValue(10)
param aiMaxReplicas int = 3

@minValue(1)
@maxValue(10)
param audioMaxReplicas int = 2

@secure()
@description('Runtime secrets copied from the existing Formation3 App Service settings.')
param workerSecrets object

@description('Resource tags.')
param tags object = {
  workload: 'cadrenza-pipeline'
  managedBy: 'bicep'
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' existing = {
  name: containerEnvironmentName
}

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource serviceBus 'Microsoft.ServiceBus/namespaces@2024-01-01' existing = {
  name: serviceBusName
}

resource aiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: aiIdentityName
}

resource audioIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: audioIdentityName
}

var runtimeSecrets = [
  {
    name: 'database-url'
    value: workerSecrets.databaseUrl
  }
  {
    name: 'deepseek-api-key'
    value: workerSecrets.deepseekApiKey
  }
  {
    name: 'fish-audio-api-key'
    value: workerSecrets.fishAudioApiKey
  }
  {
    name: 'azure-tts-storage'
    value: workerSecrets.azureTtsStorageConnectionString
  }
  {
    name: 'azure-audio-storage'
    value: workerSecrets.azureAudioStorageConnectionString
  }
  {
    name: 'azure-storage'
    value: workerSecrets.azureStorageConnectionString
  }
]

var runtimeSecretEnv = [
  {
    name: 'DATABASE_URL'
    secretRef: 'database-url'
  }
  {
    name: 'DEEPSEEK_API_KEY'
    secretRef: 'deepseek-api-key'
  }
  {
    name: 'FISH_AUDIO_API_KEY'
    secretRef: 'fish-audio-api-key'
  }
  {
    name: 'AZURE_TTS_STORAGE_CONNECTION_STRING'
    secretRef: 'azure-tts-storage'
  }
  {
    name: 'AZURE_AUDIO_STORAGE_CONNECTION_STRING'
    secretRef: 'azure-audio-storage'
  }
  {
    name: 'AZURE_STORAGE_CONNECTION_STRING'
    secretRef: 'azure-storage'
  }
]

var commonEnv = [
  {
    name: 'DATABASE_BACKEND'
    value: 'postgres'
  }
  {
    name: 'PIPELINE_DATABASE_BACKEND'
    value: 'postgres'
  }
  {
    name: 'PIPELINE_POSTGRES_MIRROR'
    value: '0'
  }
  {
    name: 'PIPELINE_QUEUE_BACKEND'
    value: 'service_bus'
  }
  {
    name: 'PIPELINE_SERVICE_BUS_QUEUE'
    value: generalQueueName
  }
  {
    name: 'PIPELINE_SERVICE_BUS_AI_QUEUE'
    value: aiQueueName
  }
  {
    name: 'PIPELINE_SERVICE_BUS_AUDIO_QUEUE'
    value: audioQueueName
  }
  {
    name: 'AZURE_SERVICE_BUS_NAMESPACE'
    value: serviceBus.name
  }
  {
    name: 'PIPELINE_WORK_LEASE_SECONDS'
    value: '300'
  }
  {
    name: 'PIPELINE_WORK_HEARTBEAT_SECONDS'
    value: '60'
  }
  {
    name: 'PIPELINE_WORKER_POLL_SECONDS'
    value: '1'
  }
  {
    name: 'PIPELINE_OUTBOX_BATCH_SIZE'
    value: '20'
  }
  {
    name: 'PIPELINE_SERVICE_BUS_LOCK_RENEWAL_SECONDS'
    value: '21600'
  }
  {
    name: 'POSTGRES_POOL_MIN_SIZE'
    value: '1'
  }
  {
    name: 'POSTGRES_POOL_MAX_SIZE'
    value: '6'
  }
  {
    name: 'POSTGRES_POOL_TIMEOUT_SECONDS'
    value: '30'
  }
  {
    name: 'POSTGRES_POOL_MAX_LIFETIME_SECONDS'
    value: '1800'
  }
  {
    name: 'POSTGRES_POOL_MAX_IDLE_SECONDS'
    value: '300'
  }
  {
    name: 'POSTGRES_CONNECT_TIMEOUT_SECONDS'
    value: '20'
  }
  {
    name: 'POSTGRES_POOL_RECONNECT_TIMEOUT_SECONDS'
    value: '60'
  }
  {
    name: 'POSTGRES_FORCE_IPV4'
    value: '0'
  }
  {
    name: 'POSTGRES_TIMEZONE'
    value: 'Europe/Paris'
  }
  {
    name: 'FORMATION_LLM_PROVIDER'
    value: 'deepseek'
  }
  {
    name: 'FORMATION_LLM_MODEL'
    value: 'deepseek-v4-flash'
  }
  {
    name: 'DEEPSEEK_ANTHROPIC_BASE_URL'
    value: 'https://api.deepseek.com/anthropic'
  }
  {
    name: 'FORMATION_CONTENT_DAY_WORKERS'
    value: '3'
  }
  {
    name: 'FORMATION_CONTENT_DAY_WORKERS_MAX'
    value: '8'
  }
  {
    name: 'FORMATION_STRUCTURED_COURSE_WORKERS'
    value: '7'
  }
  {
    name: 'FORMATION_TTS_WORDS_PER_MINUTE'
    value: '165.7'
  }
  {
    name: 'BASIC_TTS_SPEED'
    value: '1.15'
  }
  {
    name: 'FISH_AUDIO_VOICE_ID'
    value: fishAudioVoiceId
  }
  {
    name: 'TEACHER_ASSET_GENERATOR_VERSION'
    value: 'pipeline-v1'
  }
  {
    name: 'ALLOW_LEGACY_BULK_AUDIO'
    value: '0'
  }
  {
    name: 'AZURE_TTS_DOCUMENT_CONTAINER'
    value: 'documenttts'
  }
  {
    name: 'AZURE_TTS_AUDIO_CONTAINER'
    value: 'audiostts'
  }
  {
    name: 'AZURE_PIPELINE_ARTIFACT_CONTAINER'
    value: 'pipeline-artifacts'
  }
  {
    name: 'PIPELINE_ARTIFACTS_REQUIRED'
    value: '1'
  }
  {
    name: 'PYTHONUNBUFFERED'
    value: '1'
  }
]

resource aiApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: '${baseName}-ai-worker'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${aiIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 3
      registries: [
        {
          server: registry.properties.loginServer
          identity: aiIdentity.id
        }
      ]
      secrets: runtimeSecrets
    }
    template: {
      containers: [
        {
          name: 'ai-worker'
          image: image
          command: [
            'python'
            '-m'
            'workers.ai_worker'
          ]
          env: concat(
            commonEnv,
            runtimeSecretEnv,
            [
              {
                name: 'PIPELINE_WORKER_KIND'
                value: 'ai'
              }
              {
                name: 'AZURE_CLIENT_ID'
                value: aiIdentity.properties.clientId
              }
            ]
          )
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: aiMaxReplicas
        rules: [
          {
            name: 'ai-service-bus'
            custom: any({
              type: 'azure-servicebus'
              identity: aiIdentity.id
              metadata: {
                namespace: serviceBus.name
                queueName: aiQueueName
                messageCount: '1'
              }
            })
          }
        ]
      }
    }
  }
}

resource audioApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: '${baseName}-audio-worker'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${audioIdentity.id}': {}
    }
  }
  properties: {
    environmentId: containerEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      maxInactiveRevisions: 3
      registries: [
        {
          server: registry.properties.loginServer
          identity: audioIdentity.id
        }
      ]
      secrets: runtimeSecrets
    }
    template: {
      containers: [
        {
          name: 'audio-worker'
          image: image
          command: [
            'python'
            '-m'
            'workers.audio_worker'
          ]
          env: concat(
            commonEnv,
            runtimeSecretEnv,
            [
              {
                name: 'PIPELINE_WORKER_KIND'
                value: 'audio'
              }
              {
                name: 'AZURE_CLIENT_ID'
                value: audioIdentity.properties.clientId
              }
            ]
          )
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
        }
      ]
      scale: {
        minReplicas: 0
        maxReplicas: audioMaxReplicas
        rules: [
          {
            name: 'audio-service-bus'
            custom: any({
              type: 'azure-servicebus'
              identity: audioIdentity.id
              metadata: {
                namespace: serviceBus.name
                queueName: audioQueueName
                messageCount: '1'
              }
            })
          }
        ]
      }
    }
  }
}

output aiContainerAppName string = aiApp.name
output audioContainerAppName string = audioApp.name
