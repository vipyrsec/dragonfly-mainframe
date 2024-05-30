from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from mainframe.constants import mainframe_settings

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
