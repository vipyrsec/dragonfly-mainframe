#!/bin/sh
if [ "$GIT_SHA" = "development" ] || [ "$GIT_SHA" = "testing" ] ; then
    python -m alembic upgrade head && python -m uvicorn src.mainframe.server:app --host 0.0.0.0 --reload && exec "$0"
else
    python -m alembic upgrade head && python -m uvicorn src.mainframe.server:app --host 0.0.0.0 && exec "$0"
fi
