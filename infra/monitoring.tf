# Database alerts, emailed to the owner (Phase 4 risk list).
#
# The B1ms server's limits are its disk (P4: ~25 MB/s, 120 IOPS) and its
# burstable CPU credits. Story threads (Phase 4) add work to every ingestion
# cycle, so these warn before either runs out. Spikes are expected: the cache
# warm after each cycle reads at the disk's cap for some seconds, and about
# once an hour for a minute or so more, when it refreshes the 7-day globe
# (~25 s) and links (12-30 s), each a read of the week's stories. So each
# alert looks at a 15-minute average.
#
# The address is not committed: pass it when applying,
#   export TF_VAR_alert_email="you@example.com"

variable "alert_email" {
  description = "Where database alerts are emailed"
  type        = string
}

resource "azurerm_monitor_action_group" "db_alerts" {
  name                = "ag-orbis-db"
  resource_group_name = azurerm_resource_group.orbis.name
  short_name          = "orbisdb"

  email_receiver {
    name                    = "owner"
    email_address           = var.alert_email
    use_common_alert_schema = true
  }

  tags = {
    project     = "orbis"
    environment = var.environment
  }
}

locals {
  # metric => (aggregation, operator, threshold, what it means)
  pg_alerts = {
    disk_bandwidth_consumed_percentage = ["Average", "GreaterThan", 80, "Disk throughput above 80% of the P4 cap for 15 minutes"]
    disk_iops_consumed_percentage      = ["Average", "GreaterThan", 80, "Disk IOPS above 80% of the P4 cap for 15 minutes"]
    cpu_credits_remaining              = ["Minimum", "LessThan", 60, "Burstable CPU credits below 60 (of 288)"]
  }
}

resource "azurerm_monitor_metric_alert" "pg" {
  for_each = local.pg_alerts

  name                = "orbis-pg-${replace(each.key, "_", "-")}"
  resource_group_name = azurerm_resource_group.orbis.name
  scopes              = [azurerm_postgresql_flexible_server.orbis.id]
  description         = each.value[3]
  severity            = 2
  frequency           = "PT5M"
  window_size         = "PT15M"

  criteria {
    metric_namespace = "Microsoft.DBforPostgreSQL/flexibleServers"
    metric_name      = each.key
    aggregation      = each.value[0]
    operator         = each.value[1]
    threshold        = each.value[2]
  }

  action {
    action_group_id = azurerm_monitor_action_group.db_alerts.id
  }

  tags = {
    project     = "orbis"
    environment = var.environment
  }
}
