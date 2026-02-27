output "resource_group_name" {
  description = "Name of the resource group"
  value       = azurerm_resource_group.orbis.name
}

output "postgres_fqdn" {
  description = "Fully qualified domain name of the PostgreSQL Flexible Server"
  value       = azurerm_postgresql_flexible_server.orbis.fqdn
}

output "postgres_connection_string" {
  description = "Full PostgreSQL connection string"
  value       = "postgresql://orbisadmin:${var.pg_admin_password}@${azurerm_postgresql_flexible_server.orbis.fqdn}:5432/orbis?sslmode=require"
  sensitive   = true
}

output "redis_hostname" {
  description = "Azure Cache for Redis hostname"
  value       = azurerm_redis_cache.orbis.hostname
}

output "redis_connection_string" {
  description = "Redis connection string (SSL)"
  value       = "rediss://:${azurerm_redis_cache.orbis.primary_access_key}@${azurerm_redis_cache.orbis.hostname}:${azurerm_redis_cache.orbis.ssl_port}"
  sensitive   = true
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
