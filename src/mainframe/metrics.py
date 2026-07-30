from prometheus_client import Counter, Gauge

packages_ingested = Counter("packages_ingested", "Total number of packages ingested")

packages_in_queue = Gauge(
    "packages_in_queue",
    "Packages that are currently waiting to be scanned. Includes queued and pending packages.",
)

packages_queue = Gauge(
    "packages_queue",
    "Database-reconciled package queue size by state.",
    ["state"],
)
packages_queue_oldest_age_seconds = Gauge(
    "packages_queue_oldest_age_seconds",
    "Age of the oldest package waiting or eligible for retry.",
)
packages_queue_snapshot_timestamp_seconds = Gauge(
    "packages_queue_snapshot_timestamp_seconds",
    "Unix timestamp of the latest successful database queue snapshot.",
)
packages_queue_refresh_failures = Counter(
    "packages_queue_refresh_failures",
    "Number of failed database queue snapshot refreshes.",
)

rule_hits = Gauge(
    "rule_hits",
    "Database-reconciled number of successful scans that matched a rule.",
    ["rule"],
)
packages_scanned = Gauge(
    "packages_scanned",
    "Database-reconciled number of successfully completed package scans.",
)
packages_scan_outcomes = Gauge(
    "packages_scan_outcomes",
    "Database-reconciled package scan totals by terminal outcome.",
    ["outcome"],
)
packages_above_production_threshold = Gauge(
    "packages_above_production_threshold",
    "Database-reconciled number of successful scans at or above the production score threshold.",
)
packages_reported_snapshot = Gauge(
    "packages_reported_snapshot",
    "Latest database-reconciled number of packages reported.",
)
production_score_threshold = Gauge(
    "production_score_threshold",
    "Current persisted production score threshold.",
)
performance_snapshot_timestamp_seconds = Gauge(
    "performance_snapshot_timestamp_seconds",
    "Unix timestamp of the latest successful database performance snapshot.",
)
performance_refresh_failures = Counter(
    "performance_refresh_failures",
    "Number of failed database performance snapshot refreshes.",
)
performance_projection_complete = Gauge(
    "performance_projection_complete",
    "Whether the initial bounded projection of historical performance data is complete.",
)
performance_projection_processed = Counter(
    "performance_projection_processed",
    "Number of source records incorporated into durable performance rollups.",
    ["kind"],
)
performance_projection_failures = Counter(
    "performance_projection_failures",
    "Number of failed bounded performance projection batches.",
)

packages_success = Counter("packages_success", "Number of packages scanned successfully")
packages_fail = Counter("packages_fail", "Number of packages that failed scanning")
packages_dead_lettered = Counter(
    "packages_dead_lettered",
    "Number of package scans dead-lettered after exhausting worker attempts.",
)
