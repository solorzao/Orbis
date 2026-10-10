resource "azurerm_log_analytics_workspace" "orbis" {
  name                = "log-orbis"
  resource_group_name = azurerm_resource_group.orbis.name
  location            = azurerm_resource_group.orbis.location
  sku                 = "PerGB2018"
  retention_in_days   = 30

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}

resource "azurerm_container_app_environment" "orbis" {
  name                       = "cae-orbis"
  resource_group_name        = azurerm_resource_group.orbis.name
  location                   = azurerm_resource_group.orbis.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.orbis.id

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}

resource "azurerm_container_app" "api" {
  name                         = "orbis-api"
  resource_group_name          = azurerm_resource_group.orbis.name
  container_app_environment_id = azurerm_container_app_environment.orbis.id
  revision_mode                = "Single"

  tags = {
    project     = "orbis"
    environment = "dev"
  }

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.orbis_api.id]
  }

  # Secrets sourced from Key Vault via managed identity
  secret {
    name                = "database-url"
    key_vault_secret_id = azurerm_key_vault_secret.database_url.versionless_id
    identity            = azurerm_user_assigned_identity.orbis_api.id
  }

  secret {
    name                = "orbis-api-key"
    key_vault_secret_id = azurerm_key_vault_secret.orbis_api_key.versionless_id
    identity            = azurerm_user_assigned_identity.orbis_api.id
  }

  secret {
    name                = "ml-functions-key"
    key_vault_secret_id = azurerm_key_vault_secret.ml_functions_key.versionless_id
    identity            = azurerm_user_assigned_identity.orbis_api.id
  }

  # Versionless so values set later with `az keyvault secret set` are picked
  # up on the next revision restart.
  dynamic "secret" {
    for_each = azurerm_key_vault_secret.external
    content {
      name                = secret.value.name
      key_vault_secret_id = secret.value.versionless_id
      identity            = azurerm_user_assigned_identity.orbis_api.id
    }
  }

  ingress {
    external_enabled = true
    target_port      = 8000

    traffic_weight {
      percentage      = 100
      latest_revision = true
    }
  }

  template {
    # Exactly one replica: GDELT ingestion runs on an in-process scheduler,
    # so extra replicas would duplicate ingestion work.
    min_replicas = 1
    max_replicas = 1

    container {
      name   = "orbis-api"
      image  = var.api_image
      cpu    = 0.25
      memory = "0.5Gi"

      env {
        name        = "DATABASE_URL"
        secret_name = "database-url"
      }

      env {
        name        = "REDIS_URL"
        secret_name = "redis-url"
      }

      env {
        name        = "ANTHROPIC_API_KEY"
        secret_name = "anthropic-api-key"
      }

      env {
        name        = "OPENAI_API_KEY"
        secret_name = "openai-api-key"
      }

      env {
        name        = "ORBIS_API_KEY"
        secret_name = "orbis-api-key"
      }

      env {
        name  = "AGENT_ENABLED"
        value = var.agent_enabled
      }

      env {
        name  = "ML_FUNCTIONS_URL"
        value = "https://${azurerm_function_app_flex_consumption.ml.default_hostname}/api"
      }

      env {
        name        = "ML_FUNCTIONS_KEY"
        secret_name = "ml-functions-key"
      }
    }
  }

  lifecycle {
    # CI deploys SHA-tagged images; don't roll them back on apply.
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [
    azurerm_postgresql_flexible_server.orbis,
    azurerm_postgresql_flexible_server_database.orbis,
    azurerm_postgresql_flexible_server_configuration.extensions,
    azurerm_role_assignment.api_secrets,
  ]
}
