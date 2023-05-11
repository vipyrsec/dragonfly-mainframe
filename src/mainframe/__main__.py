import os
import uuid
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from .models import Package, Status

load_dotenv()

engine = create_async_engine(os.getenv("DB_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432"))
app = FastAPI()


@dataclass(frozen=True)
class PackageScanResult:
    most_malicious_file: Optional[str]
    score: int
