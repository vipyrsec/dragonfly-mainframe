from fastapi import APIRouter, Request

from mainframe.models.schemas import GetRules

router = APIRouter()


@router.get("/rules")
async def get_rules(request: Request) -> GetRules:
    return GetRules(
        hash=request.app.state.rules.rules_commit,
        rules=request.app.state.rules.rules,
    )
