resource "random_string" "pg_suffix" {
  length  = 6
  special = false
  upper   = false
}

resource "random_password" "pg_admin" {
  length  = 32
  special = false
}

resource "azurerm_postgresql_flexible_server" "orbis" {
  name                          = "orbis-pg-server-${random_string.pg_suffix.result}"
  resource_group_name           = azurerm_resource_group.orbis.name
  location                      = azurerm_resource_group.orbis.location
  version                       = "16"
  administrator_login           = "orbisadmin"
  administrator_password        = random_password.pg_admin.result
  sku_name                      = var.pg_sku
  storage_mb                    = var.pg_storage_mb
  backup_retention_days         = 7
  geo_redundant_backup_enabled  = false
  public_network_access_enabled = true
  zone                          = "1"

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}

resource "azurerm_postgresql_flexible_server_database" "orbis" {
  name      = "orbis"
  server_id = azurerm_postgresql_flexible_server.orbis.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.orbis.id
  value     = "POSTGIS,UUID-OSSP,VECTOR"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_azure_services" {
  name             = "AllowAzureServices"
  server_id        = azurerm_postgresql_flexible_server.orbis.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "0.0.0.0"
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allow_dev" {
  count            = var.environment == "dev" ? 1 : 0
  name             = "AllowAllForDevelopment"
  server_id        = azurerm_postgresql_flexible_server.orbis.id
  start_ip_address = "0.0.0.0"
  end_ip_address   = "255.255.255.255"
}
