from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, FetchedValue, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


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


package_rules = Table(
    "package_rules",
    Base.metadata,
    Column("package_id", ForeignKey("packages.package_id")),
    Column("rule_name", ForeignKey("rules.name")),
)


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
    inspector_url: Mapped[Optional[str]]
    rules: Mapped[list[Rules]] = relationship(secondary=package_rules)

    queued_at: Mapped[Optional[datetime]] = mapped_column(server_default=FetchedValue(), default=datetime.utcnow)
    pending_at: Mapped[Optional[datetime]]
    finished_at: Mapped[Optional[datetime]]

    client_id: Mapped[Optional[str]]

    reported_at: Mapped[Optional[datetime]]


class Rules(Base):
    """YARA rules"""

    __tablename__: str = "rules"

    name: Mapped[str] = mapped_column(primary_key=True)
