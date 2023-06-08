#!/bin/sh
python -m alembic upgrade head && python -m uvicorn src.mainframe.server:app --host 0.0.0.0 && exec "$0"
