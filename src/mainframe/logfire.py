import logfire

logfire.configure(send_to_logfire="if-token-present")

package_success = logfire.metric_counter(
    name="package_success", description="Number of successful packages scanned", unit="packages"
)

package_fails = logfire.metric_counter(
    name="package_fails",
    description="Number of packages that failed scanning",
    unit="packages",
)

packages_reported = logfire.metric_counter(
    name="packages_reported",
    description="Number of packages that have been reported",
    unit="packages",
)

packages_ingested = logfire.metric_counter(
    name="packages_ingested",
    description="Total number of packages that have been ingested",
    unit="packages",
)
