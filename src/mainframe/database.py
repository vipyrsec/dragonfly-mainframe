from collections.abc import Sequence, Generator
import datetime as dt
from typing import Generator, Optional
from typing import Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from mainframe.constants import mainframe_settings
from mainframe.models.orm import Scan
from typing import Protocol

# pool_size and max_overflow are set to their default values. There is never
# enough load to justify increasing them.
engine = create_engine(
    mainframe_settings.db_url,
    pool_size=mainframe_settings.db_connection_pool_persistent_size,
    max_overflow=mainframe_settings.db_connection_pool_max_size - mainframe_settings.db_connection_pool_persistent_size,
)
sessionmaker = sessionmaker(bind=engine, expire_on_commit=False, autobegin=False)


def get_db() -> Generator[Session, None, None]:
    session = sessionmaker()
    try:
        yield session
    finally:
        session.close()
class StorageProtocol(Protocol):
    def lookup_packages(
        self, name: Optional[str] = None, version: Optional[str] = None, since: Optional[dt.datetime] = None
    ) -> Sequence[Scan]:
        """
        Lookup information on scanned packages based on name, version, or time
        scanned. If multiple packages are returned, they are ordered with the most
        recently queued package first.

        Args:
            since: A int representing a Unix timestamp representing when to begin the search from.
            name: The name of the package.
            version: The version of the package.
            session: DB session.

        Exceptions:
            ValueError: Invalid parameter combination was passed. See below.

        Returns:
            Sequence of `Scan`s, representing the results of the query

        Only certain combinations of parameters are allowed. A query is valid if any of the following combinations are used:
            - `name` and `version`: Return the package with name `name` and version `version`, if it exists.
            - `name` and `since`: Find all packages with name `name` since `since`.
            - `since`: Find all packages since `since`.
            - `name`: Find all packages with name `name`.
        All other combinations are disallowed.

        In more formal terms, a query is valid
            iff `((name and not since) or (not version and since))`
        where a given variable name means that query parameter was passed. Equivalently, a request is invalid
            iff `(not (name or since) or (version and since))`
        """
        ...

    def mark_reported(self, *, scan: Scan, subject: str) -> None:
        """Mark the given `Scan` record as reported by `subject`."""
        ...
