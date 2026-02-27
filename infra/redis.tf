resource "azurerm_redis_cache" "orbis" {
  name                          = "redis-orbis-${random_string.pg_suffix.result}"
  resource_group_name           = azurerm_resource_group.orbis.name
  location                      = azurerm_resource_group.orbis.location
  capacity                      = 0
  family                        = "C"
  sku_name                      = "Basic"
  non_ssl_port_enabled          = false
  minimum_tls_version           = "1.2"
  public_network_access_enabled = true

  redis_configuration {}

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}
