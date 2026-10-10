terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
  required_version = ">= 1.5"

  # Remote state lives in its own resource group so tearing down rg-orbis
  # never loses it. Created once by scripts/bootstrap-tfstate.sh.
  backend "azurerm" {
    resource_group_name  = "rg-orbis-tfstate"
    storage_account_name = "orbistfstate"
    container_name       = "tfstate"
    key                  = "orbis.tfstate"
    use_azuread_auth     = true
  }
}

provider "azurerm" {
  features {}
  subscription_id     = var.subscription_id
  storage_use_azuread = true
}
