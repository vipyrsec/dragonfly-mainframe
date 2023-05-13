import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import FetchedValue
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Status(Enum):
    """
    Package status.

    QUEUED - waiting to be sent to a worker
    PENDING - waiting for a response from a worker
    FINISHED - verdict received from worker
    """

    QUEUED = "queued"
    PENDING = "pending"
    FINISHED = "finished"
    FAILED = "failed"


class Package(Base):
    """The packages."""

    __tablename__: str = "packages"

    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=FetchedValue(),
        default=uuid.uuid4,
    )

    name: Mapped[str]
    version: Mapped[str]
    status: Mapped[Status]

    score: Mapped[Optional[int]]
    most_malicious_file: Mapped[Optional[str]]

    queued_at: Mapped[datetime]
    pending_at: Mapped[Optional[datetime]]
    finished_at: Mapped[Optional[datetime]]

    client_id: Mapped[Optional[str]]

    reported_at: Mapped[Optional[datetime]]
