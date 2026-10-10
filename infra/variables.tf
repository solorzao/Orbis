variable "subscription_id" {
  description = "Azure subscription ID"
  type        = string
}

variable "location" {
  description = "Azure region for all resources"
  type        = string
  default     = "westus2"
}

variable "resource_group_name" {
  description = "Name of the resource group"
  type        = string
  default     = "rg-orbis"
}

variable "pg_sku" {
  description = "SKU name for PostgreSQL Flexible Server"
  type        = string
  default     = "B_Standard_B1ms"
}

variable "pg_storage_mb" {
  description = "Storage size in MB for PostgreSQL Flexible Server"
  type        = number
  default     = 32768
}

variable "api_image" {
  description = "Container image for the API. CI deploys SHA-tagged images after creation, so changes here are ignored."
  type        = string
  default     = "ghcr.io/solorzao/orbis-api:latest"
}

variable "ml_function_max_instances" {
  description = "Upper bound on Flex Consumption instances for the ML function (caps spend)"
  type        = number
  default     = 2
}

variable "agent_enabled" {
  description = "Enable the AI agent chat feature (set to false to disable and stop API costs)"
  type        = string
  default     = "true"
}

variable "environment" {
  description = "Deployment environment (dev or prod)"
  type        = string
  default     = "dev"
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "environment must be 'dev' or 'prod'"
  }
}
