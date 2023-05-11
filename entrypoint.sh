#!/bin/sh
python -m alembic upgrade head && python -m uvicorn src.mainframe.__main__:app && exec "$0"
