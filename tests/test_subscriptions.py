from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from mainframe.endpoints.subscriptions import (
    create_subscription_route,
    get_person_route,
)
from mainframe.models.orm import Package, Person, Scan, Status
from mainframe.models.schemas import AddSubscription


def test_create_subscription(db_session: Session):
    package = Package(name="test-package", scans=[], people=[])
    db_session.add(package)
    db_session.commit()

    discord_id = 123456789

    payload = AddSubscription(
        package_name=package.name,
        discord_id=discord_id,
    )

    create_subscription_route(payload, db_session)

    package = db_session.scalar(select(Package).where(Package.name == "test-package"))
    assert package is not None
    assert package.people[0].discord_id == discord_id


def test_create_subscription_nonexistent_package(db_session: Session):
    payload = AddSubscription(
        package_name="nonexistent-package",
        discord_id=123456789,
    )

    with pytest.raises(HTTPException) as error:
        create_subscription_route(payload, db_session)
        assert error.value.status_code == 404


def test_get_person(db_session: Session):
    scan = Scan(
        name="test-package",
        version="1.0.0",
        status=Status.QUEUED,
        queued_at=datetime.now(),
        queued_by="remmy",
    )
    person = Person(discord_id=123, email_address=None)
    package = Package(name="test-package", scans=[scan], people=[person])

    db_session.add(package)
    db_session.commit()

    person = get_person_route(person_id=person.id, session=db_session)

    assert person.discord_id == 123
    assert person.email_address is None
    assert person.packages == ["test-package"]
