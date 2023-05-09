#!/bin/sh
python -m alembic upgrade head
python -m uvicorn src.__main__:app
exec "$0"
