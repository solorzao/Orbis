output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.orbis.name
}

output "postgres_fqdn" {
  description = "Fully qualified domain name of the PostgreSQL Flexible Server"
  value       = azurerm_postgresql_flexible_server.orbis.fqdn
}

output "redis_hostname" {
  description = "Azure Cache for Redis hostname"
  value       = azurerm_redis_cache.orbis.hostname
}

output "key_vault_name" {
  description = "Azure Key Vault name"
  value       = azurerm_key_vault.orbis.name
}

output "key_vault_uri" {
  description = "Azure Key Vault URI"
  value       = azurerm_key_vault.orbis.vault_uri
}

output "container_app_url" {
  description = "FQDN of the deployed Container App API"
  value       = azurerm_container_app.api.ingress[0].fqdn
}

output "container_app_name" {
  description = "Name of the Container App"
  value       = azurerm_container_app.api.name
}

output "container_apps_environment_name" {
  description = "Name of the Container Apps Environment"
  value       = azurerm_container_app_environment.orbis.name
}

output "managed_identity_client_id" {
  description = "Client ID of the API managed identity"
  value       = azurerm_user_assigned_identity.orbis_api.client_id
}
