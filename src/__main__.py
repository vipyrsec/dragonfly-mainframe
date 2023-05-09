from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from .models import Package

load_dotenv()

engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432")
app = FastAPI()

