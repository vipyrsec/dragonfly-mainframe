#!/usr/bin/env bash
set -eu

alembic upgrade head

RELOAD=""
if [ "$GIT_SHA" = "development" ] || [ "$GIT_SHA" = "testing" ]; then
  RELOAD=--reload
fi

uvicorn src.mainframe.server:app --host 0.0.0.0 $RELOAD

exec $0
