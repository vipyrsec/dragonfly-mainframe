from typing import Annotated

from fastapi import APIRouter, Depends

from mainframe.dependencies import get_rules as get_rules_dependency
from mainframe.dependencies import validate_token
from mainframe.models.schemas import GetRules
from mainframe.rules import Rules

router = APIRouter(tags=["rules"])


@router.get("/rules", dependencies=[Depends(validate_token)])
def get_rules(rules: Annotated[Rules, Depends(get_rules_dependency)]) -> GetRules:
    return GetRules(
        hash=rules.rules_commit,
        rules=rules.rules,
    )
