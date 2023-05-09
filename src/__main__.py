from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession

from .models import Package

load_dotenv()

engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432")
app = FastAPI()


@app.post("/queue-package")
async def queue_package():
    """Add a package to the database to be scanned later."""


@app.get("/package")
async def give_work():
    """Find an unscanned package and return it."""
    async with AsyncSession(engine) as session:
        data = await session.execute(select(Package))
        for row in data.scalars():
            print(row)


@app.post("/package")
async def update_verdict():
    """Update the database with the result of a package scan."""
