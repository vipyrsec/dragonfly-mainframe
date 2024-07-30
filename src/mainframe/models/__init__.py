"""Database models."""

from typing import Optional, Any, Type
from pydantic import BaseModel
from sqlalchemy import Dialect, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB


class Pydantic[T: BaseModel](TypeDecorator[T]):
    """TypeDecorator to convert between Pydantic models and JSONB."""

    impl = JSONB
    cache_ok = True

    def __init__(self, pydantic_type: Type[T]):
        super().__init__()
        self.pydantic_type = pydantic_type

    def process_bind_param(self, value: Optional[T], dialect: Dialect) -> dict[str, Any]:
        if value:
            return value.model_dump()
        else:
            return {}

    def process_result_value(self, value: Any, dialect: Dialect) -> Optional[T]:
        if value:
            return self.pydantic_type.model_validate(value)
