"""Authenticated, optional durable cache; unavailable means scan normally."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mainframe import scan_cache
from mainframe.dependencies import get_rules, validate_token
from mainframe.json_web_token import AuthenticationData
from mainframe.models.scan_cache import CacheLookup, CacheReply, CacheWrite, CacheWriteReply
from mainframe.rules import Rules

router = APIRouter(
    prefix="/scan-cache", tags=["scan-cache"], dependencies=[Depends(validate_token), Depends(scan_cache.require_cache)]
)
Database = Annotated[Session, Depends(scan_cache.cache_session, scope="function")]
RuleState = Annotated[Rules, Depends(get_rules)]
Authenticated = Annotated[AuthenticationData, Depends(validate_token)]


@router.post("/lookup")
def lookup_cache(body: CacheLookup, session: Database, rules: RuleState) -> CacheReply:
    scan_cache.validate_context(body.context, rules)
    with scan_cache.latency.labels("lookup").time():
        result = scan_cache.lookup(session, body)
    scan_cache.requests.labels("lookup", "revoked" if result.revoked else "ok").inc()
    return result


@router.post("/write")
def write_cache(body: CacheWrite, session: Database, rules: RuleState, auth: Authenticated) -> CacheWriteReply:
    scan_cache.validate_context(body.context, rules)
    scan_cache.validate_lease(session, body.context.scanner, body.lease, auth.subject)
    if not scan_cache.writer_lock(session, body.context.scanner):
        scan_cache.requests.labels("write", "busy").inc()
        raise HTTPException(503, "Cache writer busy; scan normally")
    with scan_cache.latency.labels("write").time():
        if body.revoke:
            generation = scan_cache.generation_for_write(session, body.context)
            if generation is not None:
                generation.revoked = True
            scan_cache.requests.labels("write", "revoked").inc()
            return CacheWriteReply()
        result = scan_cache.store(session, body.context, body.entries)
    scan_cache.requests.labels("write", "ok").inc()
    return result
