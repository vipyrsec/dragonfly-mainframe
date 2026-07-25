from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from mainframe.dependencies import get_performance_monitor, validate_token
from mainframe.models.schemas import PublicStatistics, RulePerformance
from mainframe.performance_monitor import PerformanceMonitor

router = APIRouter(tags=["performance"])


@router.get("/rules/performance", dependencies=[Depends(validate_token)])
def rule_performance(
    monitor: Annotated[PerformanceMonitor, Depends(get_performance_monitor)],
) -> RulePerformance:
    """Return internal hit counts keyed by full rule name."""
    snapshot = monitor.get_snapshot()
    if snapshot is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Rule performance is not available yet.",
        )

    return RulePerformance(
        hits=snapshot.rule_hits,
        sampled_at=snapshot.sampled_at,
    )


@router.get("/public/statistics")
def public_statistics(
    monitor: Annotated[PerformanceMonitor, Depends(get_performance_monitor)],
) -> PublicStatistics:
    """Return package totals explicitly approved for public display."""
    snapshot = monitor.get_snapshot()
    if snapshot is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Public statistics are not available yet.",
        )

    return PublicStatistics(
        packages_scanned=snapshot.packages_scanned,
        packages_reported=snapshot.packages_reported,
        sampled_at=snapshot.sampled_at,
    )
