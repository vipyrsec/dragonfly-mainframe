import uuid
from enum import Enum

from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from sqlalchemy import FetchedValue
from sqlalchemy.dialects.postgresql import UUID


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
    status: Mapped[Status]
