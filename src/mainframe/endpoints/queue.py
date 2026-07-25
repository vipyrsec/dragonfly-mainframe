from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from mainframe.dependencies import get_queue_monitor, validate_token
from mainframe.models.schemas import QueueStatus
from mainframe.queue_monitor import QueueMonitor

router = APIRouter(tags=["queue"])


@router.get("/queue-status", dependencies=[Depends(validate_token)])
def queue_status(monitor: Annotated[QueueMonitor, Depends(get_queue_monitor)]) -> QueueStatus:
    """Return the latest cached database queue snapshot."""
    snapshot = monitor.get_snapshot()
    if snapshot is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="Queue status is not available yet.")
    return snapshot
