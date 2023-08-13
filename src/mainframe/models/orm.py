# type: ignore

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Column,
    DateTime,
    FetchedValue,
    ForeignKey,
    Table,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


package_rules = Table(
    "package_rules",
    Base.metadata,
    Column("scan_id", ForeignKey("scans.scan_id"), primary_key=True),
    Column("rule_id", ForeignKey("rules.id"), primary_key=True),
)


class Scan(Base):
    """The scans."""

    __tablename__: str = "scans"
    __table_args__ = (UniqueConstraint("name", "version"),)

    scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=FetchedValue(),
        default=uuid.uuid4,
    )

    name: Mapped[str]
    version: Mapped[str]

    score: Mapped[Optional[int]]
    inspector_url: Mapped[Optional[str]]
    rules: Mapped[list[Rule]] = relationship(secondary=package_rules)

    reported_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reported_by: Mapped[Optional[str]]

    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class Rule(Base):
    """YARA rules"""

    __tablename__: str = "rules"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=FetchedValue(),
        default=uuid.uuid4,
    )

    name: Mapped[str] = mapped_column(unique=True)
