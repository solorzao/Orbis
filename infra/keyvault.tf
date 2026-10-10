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

# --- Generated secrets (values owned by Terraform) ---

resource "random_password" "orbis_api_key" {
  length  = 40
  special = false
}

resource "random_password" "ml_functions_key" {
  length  = 48
  special = false
}

resource "azurerm_key_vault_secret" "database_url" {
  name         = "database-url"
  value        = "postgresql://orbisadmin:${random_password.pg_admin.result}@${azurerm_postgresql_flexible_server.orbis.fqdn}:5432/orbis?sslmode=require"
  key_vault_id = azurerm_key_vault.orbis.id

  depends_on = [azurerm_role_assignment.deployer_secrets]
}

resource "azurerm_key_vault_secret" "orbis_api_key" {
  name         = "orbis-api-key"
  value        = random_password.orbis_api_key.result
  key_vault_id = azurerm_key_vault.orbis.id

  depends_on = [azurerm_role_assignment.deployer_secrets]
}

# Pushed to the Function App as a host key by the deploy workflow.
resource "azurerm_key_vault_secret" "ml_functions_key" {
  name         = "ml-functions-key"
  value        = random_password.ml_functions_key.result
  key_vault_id = azurerm_key_vault.orbis.id

  depends_on = [azurerm_role_assignment.deployer_secrets]
}

# --- External secrets (values set out-of-band) ---
#
# Terraform creates these with a placeholder so the Container App can
# reference them, then never touches the value again. Set the real values
# with `az keyvault secret set` (see terraform.tfvars.example), then restart
# the Container App revision.

locals {
  external_secrets = {
    redis_url         = "redis-url" # Upstash rediss:// URL
    anthropic_api_key = "anthropic-api-key"
    openai_api_key    = "openai-api-key"
  }
}

resource "azurerm_key_vault_secret" "external" {
  for_each     = local.external_secrets
  name         = each.value
  value        = "unset"
  key_vault_id = azurerm_key_vault.orbis.id

  lifecycle {
    ignore_changes = [value]
  }

  depends_on = [azurerm_role_assignment.deployer_secrets]
}
