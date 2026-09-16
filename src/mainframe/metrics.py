from typing import Literal

from prometheus_client import Counter, Gauge

from mainframe.models.schemas import ScannerReuseMetrics

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

packages_success = Counter("packages_success", "Number of packages scanned successfully")
packages_fail = Counter("packages_fail", "Number of packages that failed scanning")
packages_dead_lettered = Counter(
    "packages_dead_lettered",
    "Number of package scans dead-lettered after exhausting worker attempts.",
)


REUSE_FIELDS = (
    "lookups",
    "candidate_files",
    "reused_files",
    "reused_bytes",
    "inserted_files",
    "evicted_files",
    "errors",
    "validated_files",
    "mismatched_files",
    "engine_files",
    "engine_bytes",
)
scanner_reuse_counters = {
    name: Counter(f"scanner_reuse_{name}", f"Worker-reported {name} from accepted scan results.", ["scanner", "mode"])
    for name in REUSE_FIELDS
}
scanner_reuse_reports = Counter(
    "scanner_reuse_reports", "Accepted worker reuse telemetry reports.", ["scanner", "mode"]
)
scanner_reuse_engine_seconds = Counter(
    "scanner_reuse_engine_seconds", "Measured engine wall seconds from accepted results.", ["scanner", "mode"]
)
scanner_reuse_overhead_seconds = Counter(
    "scanner_reuse_overhead_seconds", "Measured cache overhead wall seconds from accepted results.", ["scanner", "mode"]
)
scanner_reuse_last_report = Gauge(
    "scanner_reuse_last_report_timestamp_seconds", "Latest accepted reuse telemetry timestamp.", ["scanner", "mode"]
)
# Keep label cardinality fixed and establish zero series before the first report.
for _scanner in ("yara", "opengrep"):
    for _mode in ("off", "observe", "reuse"):
        for _counter in (
            *scanner_reuse_counters.values(),
            scanner_reuse_reports,
            scanner_reuse_engine_seconds,
            scanner_reuse_overhead_seconds,
        ):
            _counter.labels(_scanner, _mode).inc(0)
        scanner_reuse_last_report.labels(_scanner, _mode).set(0)


def record_scanner_reuse(scanner: Literal["yara", "opengrep"], metrics: ScannerReuseMetrics | None) -> None:
    """Count only committed, accepted leases; scanner labels come from the route."""
    if metrics is None:
        return
    for name, counter in scanner_reuse_counters.items():
        counter.labels(scanner, metrics.mode).inc(getattr(metrics, name))
    scanner_reuse_reports.labels(scanner, metrics.mode).inc()
    scanner_reuse_engine_seconds.labels(scanner, metrics.mode).inc(metrics.engine_us / 1_000_000)
    scanner_reuse_overhead_seconds.labels(scanner, metrics.mode).inc(metrics.overhead_us / 1_000_000)
    scanner_reuse_last_report.labels(scanner, metrics.mode).set_to_current_time()
