import uuid
from dataclasses import dataclass

from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from .models import Package, Status

load_dotenv()

engine = create_async_engine("postgresql+asyncpg://postgres:postgres@localhost:5432")
app = FastAPI()


@dataclass(frozen=True)
class PackageScanResult:
    most_malicious_file: str | None
    score: int


@app.put("/package/{package_id}")
async def update_verdict(pack_res: PackageScanResult, package_id: uuid.UUID):
    """"""
    print(pack_res)

    async with AsyncSession(engine) as session:
        await session.execute(
            update(Package)
            .where(Package.package_id == package_id)
            .values(most_malicious_file=pack_res.most_malicious_file, score=pack_res.score, status=Status.FINISHED)
        )


@app.get("/package/{package_id}")
async def package_info(package_id: uuid.UUID):
    """"""
    async with AsyncSession(engine) as session:
        data = await session.execute(select(Package).filter_by(package_id=package_id))
        return data.scalar_one()
