from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Column, FetchedValue, ForeignKey, Table
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
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
    Column("package_id", ForeignKey("packages.package_id"), primary_key=True),
    Column("rule_name", ForeignKey("rules.name"), primary_key=True),
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
    rules: Mapped[list[Rule]] = relationship(secondary=package_rules)
    rule_names: AssociationProxy[list[str]] = association_proxy("rules", "name", creator=lambda name: Rule(name=name))
    download_urls: Mapped[list[DownloadURL]] = relationship()

    queued_at: Mapped[Optional[datetime]] = mapped_column(server_default=FetchedValue(), default=datetime.utcnow)
    queued_by: Mapped[str]

    pending_at: Mapped[Optional[datetime]]
    pending_by: Mapped[Optional[str]]

    finished_at: Mapped[Optional[datetime]]
    finished_by: Mapped[Optional[str]]

    reported_at: Mapped[Optional[datetime]]
    reported_by: Mapped[Optional[str]]


class DownloadURL(Base):
    """Download URLs"""

    __tablename__: str = "download_urls"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=FetchedValue(),
        default=uuid.uuid4,
    )

    package_id: Mapped[str] = mapped_column(ForeignKey("packages.package_id"))

    url: Mapped[str]


class Rule(Base):
    """YARA rules"""

    __tablename__: str = "rules"

    name: Mapped[str] = mapped_column(primary_key=True)
