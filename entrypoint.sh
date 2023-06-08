#!/bin/sh
python -m alembic upgrade head && python -m uvicorn src.mainframe.server:app && exec "$0"
