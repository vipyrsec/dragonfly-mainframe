from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    or_,
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
    Column("scan_id", ForeignKey("scans.scan_id")),  # pyright: ignore[reportUnknownArgumentType]
    Column("rule_id", ForeignKey("rules.id")),  # pyright: ignore[reportUnknownArgumentType]
    PrimaryKeyConstraint("scan_id", "rule_id"),
)


class Scan(Base):
    """The scans."""

    __tablename__: str = "scans"
    __table_args__ = (
        UniqueConstraint("name", "version"),
        CheckConstraint("attempt_count >= 0", name="scans_nonnegative_attempt_count"),
    )

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
    attempt_count: Mapped[int] = mapped_column(default=0, server_default="0")
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    finished_by: Mapped[str | None] = mapped_column(default=None)

    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    reported_by: Mapped[str | None] = mapped_column(default=None)
    report_summary: Mapped[str | None] = mapped_column(default=None)

    fail_reason: Mapped[str | None] = mapped_column(default=None)

    commit_hash: Mapped[str | None] = mapped_column(default=None)
    analytics_outcome_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )
    analytics_report_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )


Index(None, Scan.status, postgresql_where=or_(Scan.status == Status.QUEUED, Scan.status == Status.PENDING))
Index(
    "ix_scans_analytics_outcome_pending",
    Scan.scan_id,
    postgresql_where=Scan.analytics_outcome_processed_at.is_(None) & Scan.status.in_((Status.FINISHED, Status.FAILED)),
)
Index(
    "ix_scans_analytics_report_pending",
    Scan.scan_id,
    postgresql_where=Scan.analytics_report_processed_at.is_(None) & Scan.reported_at.is_not(None),
)


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

    url: Mapped[str] = mapped_column(kw_only=True)


class Rule(Base):
    """YARA rules."""

    __tablename__: str = "rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid.uuid4,
        init=False,
    )

    name: Mapped[str] = mapped_column(unique=True, kw_only=True)


class AlertingConfiguration(Base):
    """Durable alerting configuration shared by Mainframe clients."""

    __tablename__: str = "alerting_configuration"
    __table_args__ = (
        CheckConstraint("id = 1", name="alerting_configuration_singleton"),
        CheckConstraint(
            "production_score_threshold >= 0",
            name="alerting_configuration_nonnegative_threshold",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    production_score_threshold: Mapped[int] = mapped_column(default=8)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
    )
    updated_by: Mapped[str] = mapped_column(default="system")


class PerformanceRollup(Base):
    """Compact, replayable totals derived from terminal scans."""

    __tablename__: str = "performance_rollup"
    __table_args__ = (
        CheckConstraint("id = 1", name="performance_rollup_singleton"),
        CheckConstraint(
            "packages_scanned >= 0 AND packages_failed >= 0 AND packages_dead_lettered >= 0 AND packages_reported >= 0",
            name="performance_rollup_nonnegative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, default=1)
    packages_scanned: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    packages_failed: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    packages_dead_lettered: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")
    packages_reported: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class RuleHitRollup(Base):
    """Successful scan hits for one historical rule identity."""

    __tablename__: str = "rule_hit_rollup"
    __table_args__ = (CheckConstraint("hits >= 0", name="rule_hit_rollup_nonnegative"),)

    rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("rules.id"),
        primary_key=True,
        kw_only=True,
    )
    hits: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class ScoreRollup(Base):
    """Successful scan totals grouped by score."""

    __tablename__: str = "score_rollup"
    __table_args__ = (CheckConstraint("scans >= 0", name="score_rollup_nonnegative"),)

    score: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, kw_only=True)
    scans: Mapped[int] = mapped_column(BigInteger, default=0, server_default="0")


class PerformanceProjectionState(Base):
    """Durable progress for the bounded performance projection."""

    __tablename__: str = "performance_projection_state"
    __table_args__ = (CheckConstraint("id = 1", name="performance_projection_state_singleton"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=False, default=1)
    initial_backfill_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )
    last_processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=None,
    )


class Suppression(Base):
    """A durable package-version alert suppression."""

    __tablename__: str = "suppressions"
    __table_args__ = (
        CheckConstraint("package_name <> ''", name="suppressions_package_name_nonempty"),
        CheckConstraint("package_version <> ''", name="suppressions_package_version_nonempty"),
        Index("ix_suppressions_package_name_version", "package_name", "package_version"),
    )

    suppression_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default_factory=uuid.uuid4,
        init=False,
    )
    package_name: Mapped[str] = mapped_column(default=None)
    package_version: Mapped[str] = mapped_column(default=None)
    created_by: Mapped[str] = mapped_column(default=None)
    updated_by: Mapped[str] = mapped_column(default=None)
    rules: Mapped[list[str] | None] = mapped_column(ARRAY(String()), default=None)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
        init=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
    )
