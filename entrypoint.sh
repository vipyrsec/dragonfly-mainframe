#!/bin/sh
python -m alembic upgrade head && python -m uvicorn mainframe.__main__:app && exec "$0"
