import os

from dotenv import load_dotenv
from fastapi import FastAPI
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from .models import Package

load_dotenv()

app = FastAPI()

engine = create_engine(os.getenv("DB_URL", "sqlite:///:memory:"))


@app.post("/queue-package")
def queue_package():
    """Add a package to the database to be scanned later."""


@app.get("/package")
def give_work():
    """Find an unscanned package and return it."""
    with Session(engine) as session:
        print(session)
        print(select(Package))


@app.post("/package")
def update_verdict():
    """Update the database with the result of a package scan."""
