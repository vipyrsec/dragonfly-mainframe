import asyncio
import uuid
from collections.abc import Generator

import httpx
import pytest
from fastapi import FastAPI, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from mainframe.database import get_db
from mainframe.endpoints.suppressions import (
    SuppressionPath,
    create_suppression,
    delete_suppression,
    delete_version_suppressions,
    get_suppression,
    list_package_suppressions,
    update_suppression,
)
from mainframe.json_web_token import AuthenticationData
from mainframe.models.schemas import SuppressionCreate, SuppressionUpdate


def test_suppression_lifecycle_and_package_enumeration(
    db_session: Session,
    auth: AuthenticationData,
) -> None:
    all_rules = create_suppression(
        "Example_Package",
        "1.0.0",
        SuppressionCreate(),
        db_session,
        auth,
    )
    one_rule = create_suppression(
        "example-package",
        "2.0.0",
        SuppressionCreate(rules=["false_positive_rule"]),
        db_session,
        auth,
    )

    assert all_rules.package_name == "example-package"
    assert all_rules.rules is None
    assert all_rules.created_by == auth.subject
    assert one_rule.suppression_id != all_rules.suppression_id

    suppressions = list_package_suppressions("EXAMPLE.package", db_session, auth)
    assert [suppression.suppression_id for suppression in suppressions] == [
        all_rules.suppression_id,
        one_rule.suppression_id,
    ]

    fetched = get_suppression(
        SuppressionPath("example-package", "2.0.0", one_rule.suppression_id),
        db_session,
        auth,
    )
    assert fetched == one_rule

    updated = update_suppression(
        SuppressionPath("example-package", "2.0.0", one_rule.suppression_id),
        SuppressionUpdate(rules=["replacement_rule"]),
        db_session,
        auth,
    )
    assert updated.rules == ["replacement_rule"]
    assert updated.updated_by == auth.subject
    assert updated.updated_at >= one_rule.updated_at

    deleted = delete_suppression(
        SuppressionPath("example-package", "2.0.0", one_rule.suppression_id),
        db_session,
        auth,
    )
    assert deleted.deleted == 1
    remaining = list_package_suppressions("example-package", db_session, auth)
    assert [suppression.suppression_id for suppression in remaining] == [all_rules.suppression_id]


def test_delete_all_suppressions_only_deletes_requested_version(
    db_session: Session,
    auth: AuthenticationData,
) -> None:
    first = create_suppression("example", "1.0.0", SuppressionCreate(rules=["one"]), db_session, auth)
    create_suppression("example", "1.0.0", SuppressionCreate(rules=["two"]), db_session, auth)
    retained = create_suppression("example", "2.0.0", SuppressionCreate(), db_session, auth)

    response = delete_version_suppressions("example", "1.0.0", db_session, auth)

    assert response.deleted == 2
    assert [suppression.suppression_id for suppression in list_package_suppressions("example", db_session, auth)] == [
        retained.suppression_id
    ]
    with pytest.raises(HTTPException) as error:
        get_suppression(SuppressionPath("example", "1.0.0", first.suppression_id), db_session, auth)
    assert error.value.status_code == status.HTTP_404_NOT_FOUND


def test_suppression_identity_is_scoped_to_package_and_version(
    db_session: Session,
    auth: AuthenticationData,
) -> None:
    suppression = create_suppression("example", "1.0.0", SuppressionCreate(), db_session, auth)

    with pytest.raises(HTTPException) as error:
        get_suppression(SuppressionPath("other", "1.0.0", suppression.suppression_id), db_session, auth)
    assert error.value.status_code == status.HTTP_404_NOT_FOUND

    with pytest.raises(HTTPException) as error:
        get_suppression(SuppressionPath("example", "2.0.0", suppression.suppression_id), db_session, auth)
    assert error.value.status_code == status.HTTP_404_NOT_FOUND

    with pytest.raises(HTTPException) as error:
        get_suppression(SuppressionPath("example", "1.0.0", uuid.uuid4()), db_session, auth)
    assert error.value.status_code == status.HTTP_404_NOT_FOUND


def test_rule_corpus_distinguishes_all_rules_from_no_rules() -> None:
    assert SuppressionCreate().rules is None
    assert SuppressionCreate(rules=[]).rules == []

    with pytest.raises(ValidationError, match="rules must not contain duplicates"):
        SuppressionCreate(rules=["duplicate", "duplicate"])

    with pytest.raises(ValidationError):
        SuppressionCreate(rules=[""])


def test_suppression_http_resource_routes(
    db_session: Session,
    app_without_auth: FastAPI,
) -> None:
    def get_test_db() -> Generator[Session, None, None]:
        yield db_session

    app_without_auth.dependency_overrides[get_db] = get_test_db

    async def exercise_routes() -> None:
        transport = httpx.ASGITransport(app=app_without_auth)
        collection = "/packages/Example_Package/versions/1.0%2Blocal/suppressions"
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(collection, json={"rules": ["false_positive_rule"]})
            assert created.status_code == status.HTTP_201_CREATED
            suppression_id = created.json()["suppression_id"]

            listed = await client.get("/packages/example-package/suppressions")
            assert listed.status_code == status.HTTP_200_OK
            assert [suppression["suppression_id"] for suppression in listed.json()] == [suppression_id]

            item = f"{collection}/{suppression_id}"
            fetched = await client.get(item)
            assert fetched.status_code == status.HTTP_200_OK
            assert fetched.json()["rules"] == ["false_positive_rule"]

            invalid_update = await client.patch(item, json={})
            assert invalid_update.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

            updated = await client.patch(item, json={"rules": None})
            assert updated.status_code == status.HTTP_200_OK
            assert updated.json()["rules"] is None

            deleted = await client.delete(collection)
            assert deleted.status_code == status.HTTP_200_OK
            assert deleted.json() == {"deleted": 1}

    try:
        asyncio.run(exercise_routes())
    finally:
        app_without_auth.dependency_overrides.pop(get_db, None)
