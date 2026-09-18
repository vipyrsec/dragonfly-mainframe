from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    FetchedValue,
    ForeignKey,
    Index,
    LargeBinary,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    and_,
    or_,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
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


class OpenGrepScan(Base):
    """An isolated OpenGrep shadow scan for one canonical package scan."""

    __tablename__: str = "opengrep_scans"
    __table_args__ = (
        CheckConstraint("attempt_count >= 0", name="opengrep_scans_nonnegative_attempt_count"),
        CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="opengrep_scans_nonnegative_duration",
        ),
        CheckConstraint(
            "published_chunks >= 0",
            name="opengrep_scans_nonnegative_published_chunks",
        ),
    )

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scans.scan_id", ondelete="CASCADE"),
        primary_key=True,
        kw_only=True,
    )
    status: Mapped[Status] = mapped_column(default=Status.QUEUED)
    alerted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default_factory=lambda: datetime.now(UTC),
    )
    queued_by: Mapped[str] = mapped_column(default="system")
    pending_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    pending_by: Mapped[str | None] = mapped_column(default=None)
    attempt_count: Mapped[int] = mapped_column(default=0, server_default="0")
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    dead_lettered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)
    finished_by: Mapped[str | None] = mapped_column(default=None)
    fail_reason: Mapped[str | None] = mapped_column(default=None)
    commit_hash: Mapped[str | None] = mapped_column(default=None)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, default=None)
    findings: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default_factory=list)
    publication_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), default=None)
    publication_claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    discord_alert_message_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    discord_message_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    discord_thread_id: Mapped[int | None] = mapped_column(BigInteger, default=None)
    published_chunks: Mapped[int] = mapped_column(default=0, server_default="0")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None, index=True)


Index(
    "ix_opengrep_scans_status",
    OpenGrepScan.status,
    postgresql_where=and_(
        OpenGrepScan.alerted_at.is_not(None),
        or_(
            OpenGrepScan.status == Status.QUEUED,
            OpenGrepScan.status == Status.PENDING,
        ),
    ),
)


Index(None, Scan.status, postgresql_where=or_(Scan.status == Status.QUEUED, Scan.status == Status.PENDING))


class SuppressedPackage(Base):
    """Suppressed packages"""

    __tablename__: str = "suppressed_packages"
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        init=False,
    )
    scan_id: Mapped[str] = mapped_column(
        ForeignKey("scans.scan_id"),
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


class ScanCacheNamespace(Base):
    """A revocable rules/engine generation; counters change only with batch writes."""

    __tablename__ = "scan_cache_namespaces"
    __table_args__ = (
        CheckConstraint("octet_length(namespace) = 32", name="cache_namespace_digest_length"),
        CheckConstraint("entry_count >= 0 AND payload_bytes >= 0", name="cache_nonnegative_counts"),
    )
    namespace: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    scanner: Mapped[str] = mapped_column()
    rules_commit: Mapped[str] = mapped_column()
    rules_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    engine_digest: Mapped[bytes] = mapped_column(LargeBinary(32))
    revoked: Mapped[bool] = mapped_column(default=False)
    entry_count: Mapped[int] = mapped_column(default=0)
    payload_bytes: Mapped[int] = mapped_column(BigInteger, default=0)


class ScanCacheEntry(Base):
    """Immutable completed file results with bounded expiry renewal on hits."""

    __tablename__ = "scan_cache_entries"
    __table_args__ = (
        CheckConstraint("octet_length(file_digest) = 32", name="cache_file_digest_length"),
        CheckConstraint("octet_length(result) <= 16384", name="cache_result_size"),
        CheckConstraint("char_length(language) <= 32", name="cache_language_size"),
    )
    namespace: Mapped[bytes] = mapped_column(
        LargeBinary(32), ForeignKey("scan_cache_namespaces.namespace"), primary_key=True
    )
    file_digest: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    language: Mapped[str] = mapped_column(primary_key=True)
    result: Mapped[str] = mapped_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    quarantined: Mapped[bool] = mapped_column(default=False, server_default="false")
