from typing import Annotated
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from mainframe.database import get_db
from mainframe.dependencies import validate_token
from mainframe.models.orm import Package, Person
from mainframe.models.schemas import AddSubscription, GetPerson

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"], dependencies=[Depends(validate_token)])
logger: structlog.stdlib.BoundLogger = structlog.get_logger()


@router.post("/")
def create_subscription_route(payload: AddSubscription, session: Annotated[Session, Depends(get_db)]) -> None:
    package = session.scalar(select(Package).where(Package.name == payload.package_name))
    if package is None:
        raise HTTPException(404, "Package with that name was not found")

    query = select(Person)
    if payload.discord_id:
        query = query.where(Person.discord_id == payload.discord_id)
    if payload.email_address:
        query = query.where(Person.email_address == payload.email_address)

    person = session.scalar(query)
    if not person:
        person = Person(discord_id=payload.discord_id, email_address=payload.email_address)
        session.add(person)

    person.packages.append(package)

    session.commit()


@router.get("/{person_id}")
def get_person_route(person_id: UUID, session: Annotated[Session, Depends(get_db)]) -> GetPerson:
    person = session.scalar(select(Person).where(Person.id == person_id))
    if person is None:
        raise HTTPException(404, detail="A user with that ID could not be found")

    subscribed_packages = [package.name for package in person.packages]

    return GetPerson(
        person_id=person.id,
        discord_id=person.discord_id,
        email_address=person.email_address,
        packages=subscribed_packages,
    )
