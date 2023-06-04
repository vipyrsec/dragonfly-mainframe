from fastapi import APIRouter, Depends, Request

from mainframe.dependencies import validate_token
from mainframe.models.schemas import GetRules

router = APIRouter()


@router.get("/rules", dependencies=[Depends(validate_token)])
async def get_rules(request: Request) -> GetRules:
    return GetRules(
        hash=request.app.state.rules.rules_commit,
        rules=request.app.state.rules.rules,
    )
