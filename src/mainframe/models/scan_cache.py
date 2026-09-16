"""Bounded wire format for the optional durable scanner cache."""

import hashlib
import json
import uuid
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_RESULT_BYTES = 16_384

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class CacheContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scanner: Literal["yara", "opengrep"]
    rules_commit: Annotated[str, Field(min_length=1, max_length=64)]
    rules_digest: Digest
    engine_digest: Digest

    def namespace(self) -> bytes:
        return hashlib.sha256(self.model_dump_json().encode()).digest()


class CacheKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    file_digest: Digest
    language: Annotated[str, Field(max_length=32)] = ""


class CacheValue(CacheKey):
    result: Annotated[str, Field(max_length=16_384)]

    @model_validator(mode="after")
    def validate_result(self) -> Self:
        if len(self.result.encode()) > MAX_RESULT_BYTES or not isinstance(json.loads(self.result), list):
            msg = "Cache results must be a JSON array of at most 16384 encoded bytes"
            raise ValueError(msg)
        return self


class CacheLookup(BaseModel):
    context: CacheContext
    keys: Annotated[list[CacheKey], Field(min_length=1, max_length=128)]


class CacheReply(BaseModel):
    revoked: bool = False
    entries: list[CacheValue] = Field(default_factory=list[CacheValue])


class CacheLease(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=256)]
    version: Annotated[str, Field(min_length=1, max_length=256)]
    assignment_id: uuid.UUID
    attempt: Annotated[int, Field(ge=1)]


class CacheWrite(BaseModel):
    context: CacheContext
    lease: CacheLease
    entries: Annotated[list[CacheValue], Field(max_length=128)]
    revoke: bool = False

    @model_validator(mode="after")
    def validate_batch(self) -> Self:
        if sum(len(entry.result.encode()) for entry in self.entries) > 512 * 1024:
            msg = "Cache write batch exceeds 512 KiB"
            raise ValueError(msg)
        return self


class CacheWriteReply(BaseModel):
    inserted: int = 0
    skipped: int = 0
