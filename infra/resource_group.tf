resource "azurerm_resource_group" "orbis" {
  name     = var.resource_group_name
  location = var.location

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}
