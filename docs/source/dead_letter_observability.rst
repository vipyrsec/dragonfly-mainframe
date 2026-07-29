Dead-letter Observability
=========================

Mainframe gives each scan a bounded worker-assignment budget. The initial
assignment counts as one attempt. A pending scan whose lease is older than
``JOB_TIMEOUT`` is eligible for another assignment while its ``attempt_count``
is below ``MAX_JOB_ATTEMPTS``. Once the final lease expires, the next job poll
moves the scan to ``FAILED``, records ``dead_lettered_at`` and a failure reason,
and never assigns it again.

Metrics
-------

``packages_dead_lettered_total``
    Process event counter incremented whenever Mainframe dead-letters a scan.

``packages_fail_total``
    Process event counter for every failed scan, including dead letters.

``packages_success_total``
    Process event counter for successful scans.

``packages_scan_outcomes{outcome="finished|failed|dead_lettered"}``
    Database-reconciled terminal outcome totals. ``failed`` excludes dead
    letters so the three series do not overlap.

``packages_queue{state="exhausted"}``
    Expired scans that have consumed their attempt budget but have not yet been
    reaped by a job poll.

``performance_snapshot_timestamp_seconds``
    Timestamp of the latest successful database reconciliation.

Recommended alerts
------------------

Alert immediately when any scan is dead-lettered:

.. code-block:: promql

    increase(packages_dead_lettered_total[15m]) > 0

Alert when an exhausted scan is waiting to be reaped:

.. code-block:: promql

    packages_queue{state="exhausted"} > 0

Alert on a sustained failure-rate regression after at least 20 terminal
outcomes in 15 minutes:

.. code-block:: promql

    (
      sum(increase(packages_fail_total[15m]))
      /
      clamp_min(
        sum(increase(packages_success_total[15m]))
        + sum(increase(packages_fail_total[15m])),
        1
      )
    ) > 0.10
    and
    (
      sum(increase(packages_success_total[15m]))
      + sum(increase(packages_fail_total[15m]))
    ) >= 20

Alert if durable outcome metrics have not refreshed for three refresh periods:

.. code-block:: promql

    time() - performance_snapshot_timestamp_seconds > 180

Every dead letter also emits a structured ``scan_dead_lettered`` error log with
the package name, version, attempt count, prior worker, lease timestamp, and
terminal reason.
