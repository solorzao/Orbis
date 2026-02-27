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

  secret {
    name  = "database-url"
    value = "postgresql://orbisadmin:${var.pg_admin_password}@${azurerm_postgresql_flexible_server.orbis.fqdn}:5432/orbis?sslmode=require"
  }

  secret {
    name  = "redis-url"
    value = "rediss://:${azurerm_redis_cache.orbis.primary_access_key}@${azurerm_redis_cache.orbis.hostname}:${azurerm_redis_cache.orbis.ssl_port}"
  }

  secret {
    name  = "anthropic-api-key"
    value = var.anthropic_api_key
  }

  secret {
    name  = "openai-api-key"
    value = var.openai_api_key
  }

  secret {
    name  = "ghcr-password"
    value = var.ghcr_password
  }

  registry {
    server               = "ghcr.io"
    username             = var.ghcr_username
    password_secret_name = "ghcr-password"
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
    min_replicas = 0
    max_replicas = 3

    container {
      name   = "orbis-api"
      image  = "ghcr.io/solorzao/orbis-api:latest"
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
    }
  }

  depends_on = [
    azurerm_postgresql_flexible_server.orbis,
    azurerm_postgresql_flexible_server_database.orbis,
    azurerm_postgresql_flexible_server_configuration.extensions,
    azurerm_redis_cache.orbis,
  ]
}
