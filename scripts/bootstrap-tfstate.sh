#!/usr/bin/env bash
# One-time creation of the Terraform remote-state storage used by infra/.
# Kept outside rg-orbis so destroying the app never destroys its state.
set -euo pipefail

RG=rg-orbis-tfstate
SA=orbistfstate
LOCATION=westus2

az group create -n "$RG" -l "$LOCATION" -o none
az storage account create -n "$SA" -g "$RG" -l "$LOCATION" \
  --sku Standard_LRS --min-tls-version TLS1_2 \
  --allow-blob-public-access false --allow-shared-key-access false -o none

# Terraform authenticates with Entra ID (use_azuread_auth), so the caller
# needs data-plane access to the state container.
az role assignment create \
  --assignee "$(az ad signed-in-user show --query id -o tsv)" \
  --role "Storage Blob Data Contributor" \
  --scope "$(az storage account show -n "$SA" -g "$RG" --query id -o tsv)" -o none

# Role assignments take a minute or two to propagate.
for i in $(seq 1 12); do
  az storage container create -n tfstate --account-name "$SA" --auth-mode login -o none 2>/dev/null && break
  echo "Waiting for role propagation ($i)..."; sleep 10
done

echo "State storage ready: $SA/tfstate"
