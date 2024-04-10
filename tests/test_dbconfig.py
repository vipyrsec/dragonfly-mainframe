from threading import Barrier
from concurrent.futures import ThreadPoolExecutor
from mainframe.models.orm import Scan, Status
from mainframe.endpoints.job import get_jobs
import itertools
import string
from unittest.mock import Mock
from sqlalchemy.orm import Session, sessionmaker


def test_database_reaches_max_connections(db_session: Session, sm: sessionmaker[Session]):
    """
    A regression test for improper connection pool config.
    """

    # chosen to make sure we exceed the connection pool threshold of 25
    n_senders = 30

    # insert a lot of queued packages so our threads have something to return
    with db_session.begin():
        db_session.add_all(
            [
                Scan(
                    name="".join(x),
                    version="1.0.0",
                    status=Status.QUEUED,
                    queued_by="remmy",
                    download_urls=[],
                )
                for x in itertools.islice(itertools.product(string.ascii_lowercase, repeat=2), n_senders)
            ]
        )

    b = Barrier(n_senders)

    auth = Mock()
    auth.subject = "remmy"
    state = Mock()
    state.rules_commit = "0xc0ffee"

    # spawn many threads, wait for them all to be ready, then send many
    # concurrent job requests
    def sender(_: int):
        b.wait()
        with sm() as session:
            r = get_jobs(session, auth, state)  # type: ignore
        return r

    with ThreadPoolExecutor(max_workers=n_senders) as tpe:
        for r in tpe.map(sender, range(n_senders), timeout=30):
            assert r != []
