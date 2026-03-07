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

variable "pg_admin_password" {
  description = "Administrator password for PostgreSQL Flexible Server"
  type        = string
  sensitive   = true
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

variable "ghcr_username" {
  description = "GitHub username for container registry (ghcr.io)"
  type        = string
}

variable "ghcr_password" {
  description = "GitHub Personal Access Token for container registry (ghcr.io)"
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key for Claude"
  type        = string
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key"
  type        = string
  sensitive   = true
}

variable "orbis_api_key" {
  description = "Shared API key for frontend-to-backend auth (X-API-Key header)"
  type        = string
  sensitive   = true
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
