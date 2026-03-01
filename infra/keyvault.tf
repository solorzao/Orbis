data "azurerm_client_config" "current" {}

resource "azurerm_user_assigned_identity" "orbis_api" {
  name                = "id-orbis-api"
  resource_group_name = azurerm_resource_group.orbis.name
  location            = azurerm_resource_group.orbis.location

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}

resource "azurerm_key_vault" "orbis" {
  name                       = "kv-orbis-${random_string.pg_suffix.result}"
  resource_group_name        = azurerm_resource_group.orbis.name
  location                   = azurerm_resource_group.orbis.location
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  purge_protection_enabled   = var.environment == "prod" ? true : false
  rbac_authorization_enabled = true

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}

# Grant the deploying user full secret access
resource "azurerm_role_assignment" "deployer_secrets" {
  scope                = azurerm_key_vault.orbis.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

# Grant the Container App managed identity read-only secret access
resource "azurerm_role_assignment" "api_secrets" {
  scope                = azurerm_key_vault.orbis.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.orbis_api.principal_id
}

# --- Secrets ---

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = "postgresql://orbisadmin:${urlencode(var.pg_admin_password)}@${azurerm_postgresql_flexible_server.orbis.fqdn}:5432/orbis?sslmode=require"
  key_vault_id = azurerm_key_vault.orbis.id

  depends_on = [azurerm_role_assignment.deployer_secrets]
}

resource "azurerm_key_vault_secret" "redis_url" {
  name         = "redis-url"
  value        = "rediss://:${azurerm_redis_cache.orbis.primary_access_key}@${azurerm_redis_cache.orbis.hostname}:${azurerm_redis_cache.orbis.ssl_port}"
  key_vault_id = azurerm_key_vault.orbis.id

  depends_on = [azurerm_role_assignment.deployer_secrets]
}

resource "azurerm_key_vault_secret" "anthropic_api_key" {
  name         = "anthropic-api-key"
  value        = var.anthropic_api_key
  key_vault_id = azurerm_key_vault.orbis.id

  depends_on = [azurerm_role_assignment.deployer_secrets]
}

resource "azurerm_key_vault_secret" "openai_api_key" {
  name         = "openai-api-key"
  value        = var.openai_api_key
  key_vault_id = azurerm_key_vault.orbis.id

  depends_on = [azurerm_role_assignment.deployer_secrets]
}
