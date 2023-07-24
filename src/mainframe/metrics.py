from prometheus_client import Counter, Histogram, make_asgi_app  # type: ignore

package_ingest_counter = Counter("packages_ingested", "Total amount of packages ingested so far")
package_scanned_counter = Counter("packages_scanned", "Total amount of packages scanned")
package_scan_success_counter = Counter("package_scan_success", "Total amount of packages successfully scanned")
package_scan_fail_counter = Counter("package_scan_fail", "Total amount of packages that failed while scanning")
package_scan_report_counter = Counter("package_scan_report", "Total amount of packages that have been reported")

request_time = Histogram("request_time", "Time taken to serve a request")
request_counter = Counter("requests", "Total amount of requests served")

metrics_app = make_asgi_app()  # type: ignore
