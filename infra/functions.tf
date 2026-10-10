# ML topic/sentiment classification (functions/ml-classify) on Flex Consumption.
# Scales to zero between ingestion runs; the API calls it via ML_FUNCTIONS_URL.

resource "azurerm_storage_account" "ml" {
  name                            = "storbisml${random_string.pg_suffix.result}"
  resource_group_name             = azurerm_resource_group.orbis.name
  location                        = azurerm_resource_group.orbis.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  allow_nested_items_to_be_public = false

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}

resource "azurerm_storage_container" "ml_package" {
  name                  = "app-package"
  storage_account_id    = azurerm_storage_account.ml.id
  container_access_type = "private"
}

resource "azurerm_application_insights" "ml" {
  name                = "appi-orbis-ml"
  resource_group_name = azurerm_resource_group.orbis.name
  location            = azurerm_resource_group.orbis.location
  workspace_id        = azurerm_log_analytics_workspace.orbis.id
  application_type    = "web"

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}

resource "azurerm_service_plan" "ml" {
  name                = "asp-orbis-ml"
  resource_group_name = azurerm_resource_group.orbis.name
  location            = azurerm_resource_group.orbis.location
  os_type             = "Linux"
  sku_name            = "FC1"

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}

resource "azurerm_function_app_flex_consumption" "ml" {
  name                = "orbis-ml-classify"
  resource_group_name = azurerm_resource_group.orbis.name
  location            = azurerm_resource_group.orbis.location
  service_plan_id     = azurerm_service_plan.ml.id

  storage_container_type      = "blobContainer"
  storage_container_endpoint  = "${azurerm_storage_account.ml.primary_blob_endpoint}${azurerm_storage_container.ml_package.name}"
  storage_authentication_type = "StorageAccountConnectionString"
  storage_access_key          = azurerm_storage_account.ml.primary_access_key

  runtime_name           = "python"
  runtime_version        = "3.12"
  instance_memory_in_mb  = 2048 # torch + two transformer models
  maximum_instance_count = var.ml_function_max_instances
  https_only             = true

  app_settings = {
    # Hugging Face model cache must be on a writable path
    HF_HOME = "/tmp/huggingface"
  }

  site_config {
    application_insights_connection_string = azurerm_application_insights.ml.connection_string
  }

  tags = {
    project     = "orbis"
    environment = "dev"
  }
}
