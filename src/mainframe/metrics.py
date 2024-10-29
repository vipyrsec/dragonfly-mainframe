from prometheus_client import Counter, Gauge


packages_ingested = Counter("packages_ingested", "Total number of packages ingested")

packages_in_queue = Gauge(
    "packages_in_queue",
    "Packages that are currently waiting to be scanned. Includes queued and pending packages.",
)

packages_success = Counter("packages_success", "Number of packages scanned successfully")
packages_fail = Counter("packages_fail", "Number of packages that failed scanning")

packages_reported = Counter("packages_reported", "Number of packages reported")
