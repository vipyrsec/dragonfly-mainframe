from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from operator import or_

from sqlalchemy import (
    Column,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedAsDataclass,
    mapped_column,
    relationship,
)


class Base(MappedAsDataclass, DeclarativeBase, kw_only=True):
    pass


class Status(Enum):
    """Package status.

    QUEUED - Waiting to be sent to a worker
    PENDING - Waiting for a response from a worker
    FINISHED - Verdict received from worker
    FAILED - Something went wrong with the client when scanning this package
    """

    QUEUED = "queued"
    PENDING = "pending"
    FINISHED = "finished"
    FAILED = "failed"


package_rules = Table(
    "package_rules",
    Base.metadata,
    Column("scan_id", ForeignKey("scans.scan_id")),
    Column("rule_id", ForeignKey("rules.id")),
    PrimaryKeyConstraint("scan_id", "rule_id"),
)


class Scan(Base):
    """The scans."""

    __tablename__: str = "scans"
    __table_args__ = (UniqueConstraint("name", "version"),)

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid.uuid4,
        init=False,
    )

    name: Mapped[str] = mapped_column(default=None)
    version: Mapped[str] = mapped_column(default=None)
    status: Mapped[Status] = mapped_column(default=None)

    score: Mapped[int | None] = mapped_column(default=None)
    inspector_url: Mapped[str | None] = mapped_column(default=None)
    rules: Mapped[list[Rule]] = relationship(secondary=package_rules, default_factory=list)
    download_urls: Mapped[list[DownloadURL]] = relationship(default_factory=list)

    queued_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        server_default=FetchedValue(),
        default_factory=lambda: datetime.now(UTC),
    )
    queued_by: Mapped[str] = mapped_column(default=None)

    pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    pending_by: Mapped[str | None] = mapped_column(default=None)

    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    finished_by: Mapped[str | None] = mapped_column(default=None)

    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    reported_by: Mapped[str | None] = mapped_column(default=None)

    fail_reason: Mapped[str | None] = mapped_column(default=None)

    commit_hash: Mapped[str | None] = mapped_column(default=None)


Index(None, Scan.status, postgresql_where=or_(Scan.status == Status.QUEUED, Scan.status == Status.PENDING))


class DownloadURL(Base):
    """Download URLs."""

    __tablename__: str = "download_urls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid.uuid4,
        init=False,
    )

    scan_id: Mapped[str] = mapped_column(ForeignKey("scans.scan_id"), index=True, init=False)

    url: Mapped[str] = mapped_column()  # pyright: ignore[reportGeneralTypeIssues]


class Rule(Base):
    """YARA rules."""

    __tablename__: str = "rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid.uuid4,
        init=False,
    )

    name: Mapped[str] = mapped_column(unique=True)  # pyright: ignore[reportGeneralTypeIssues]
