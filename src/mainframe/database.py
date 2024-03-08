from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from mainframe.constants import mainframe_settings

engine = create_engine(mainframe_settings.db_url, pool_size=25)
sessionmaker = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    session = sessionmaker()
    try:
        yield session
    finally:
        session.close()
