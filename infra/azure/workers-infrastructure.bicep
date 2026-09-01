targetScope = 'resourceGroup'

@description('Prefix used for the worker infrastructure resources.')
param baseName string = 'cadrenza'

@description('Azure region. Keep it close to App Service and PostgreSQL.')
param location string = resourceGroup().location

@description('System-assigned principal ID of the existing API App Service.')
param appServicePrincipalId string

@description('Resource tags.')
param tags object = {
  workload: 'cadrenza-pipeline'
  managedBy: 'bicep'
}

var suffix = uniqueString(resourceGroup().id)
var acrName = toLower('cadrenzaw${suffix}')
var serviceBusName = toLower('${baseName}-pipeline-${suffix}')
var environmentName = '${baseName}-workers-env'
var logAnalyticsName = '${baseName}-workers-logs'
var aiIdentityName = '${baseName}-ai-worker-id'
var audioIdentityName = '${baseName}-audio-worker-id'
var generalQueueName = 'formation-pipeline'
var aiQueueName = 'formation-ai'
var audioQueueName = 'formation-audio'

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
var serviceBusDataReceiverRoleId = '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
var serviceBusDataSenderRoleId = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsName
  location: location
  tags: tags
  properties: {
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    sku: {
      name: 'PerGB2018'
    }
  }
}

resource containerEnvironment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: environmentName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource serviceBus 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: serviceBusName
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: 'Enabled'
    zoneRedundant: false
  }
}

resource generalQueue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  parent: serviceBus
  name: generalQueueName
  properties: {
    lockDuration: 'PT5M'
    maxDeliveryCount: 10
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    defaultMessageTimeToLive: 'P14D'
    deadLetteringOnMessageExpiration: true
  }
}

resource aiQueue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  parent: serviceBus
  name: aiQueueName
  properties: {
    lockDuration: 'PT5M'
    maxDeliveryCount: 10
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    defaultMessageTimeToLive: 'P14D'
    deadLetteringOnMessageExpiration: true
  }
}

resource audioQueue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = {
  parent: serviceBus
  name: audioQueueName
  properties: {
    lockDuration: 'PT5M'
    maxDeliveryCount: 10
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
    defaultMessageTimeToLive: 'P14D'
    deadLetteringOnMessageExpiration: true
  }
}

resource aiIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: aiIdentityName
  location: location
  tags: tags
}

resource audioIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: audioIdentityName
  location: location
  tags: tags
}

resource aiAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, aiIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: aiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      acrPullRoleId
    )
  }
}

resource audioAcrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(registry.id, audioIdentity.id, acrPullRoleId)
  scope: registry
  properties: {
    principalId: audioIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      acrPullRoleId
    )
  }
}

resource aiServiceBusSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBus.id, aiIdentity.id, serviceBusDataSenderRoleId)
  scope: serviceBus
  properties: {
    principalId: aiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      serviceBusDataSenderRoleId
    )
  }
}

resource audioServiceBusSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBus.id, audioIdentity.id, serviceBusDataSenderRoleId)
  scope: serviceBus
  properties: {
    principalId: audioIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      serviceBusDataSenderRoleId
    )
  }
}

resource aiServiceBusReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(aiQueue.id, aiIdentity.id, serviceBusDataReceiverRoleId)
  scope: aiQueue
  properties: {
    principalId: aiIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      serviceBusDataReceiverRoleId
    )
  }
}

resource audioServiceBusReceiver 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(audioQueue.id, audioIdentity.id, serviceBusDataReceiverRoleId)
  scope: audioQueue
  properties: {
    principalId: audioIdentity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      serviceBusDataReceiverRoleId
    )
  }
}

resource apiServiceBusSender 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(serviceBus.id, appServicePrincipalId, serviceBusDataSenderRoleId)
  scope: serviceBus
  properties: {
    principalId: appServicePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      serviceBusDataSenderRoleId
    )
  }
}

output acrName string = registry.name
output acrLoginServer string = registry.properties.loginServer
output containerEnvironmentName string = containerEnvironment.name
output serviceBusName string = serviceBus.name
output generalQueueName string = generalQueue.name
output aiQueueName string = aiQueue.name
output audioQueueName string = audioQueue.name
output aiIdentityName string = aiIdentity.name
output aiIdentityClientId string = aiIdentity.properties.clientId
output audioIdentityName string = audioIdentity.name
output audioIdentityClientId string = audioIdentity.properties.clientId
