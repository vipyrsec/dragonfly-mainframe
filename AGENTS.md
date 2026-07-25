# AGENTS.md — Dragonfly Mainframe Local Tooling

The workspace root `AGENTS.md` remains authoritative. These instructions add
repository-specific local test tooling.

## PostgreSQL Tests

Docker will not be installed for this repository. Run database-backed tests
against an isolated local PostgreSQL instance using Unix-domain sockets.

PostgreSQL 16 server binaries are installed under
`/usr/lib/postgresql/16/bin`, even when they are not present on `PATH`.

Keep disposable server state and sockets under `/tmp`, use a non-default port,
and pass the socket explicitly in `DB_URL`. A representative setup is:

```bash
MAINFRAME_PG_BIN=/usr/lib/postgresql/16/bin
MAINFRAME_PG_DATA=/tmp/vipyrsec-mainframe-pgdata
MAINFRAME_PG_SOCKET=/tmp/vipyrsec-mainframe-pgsocket
MAINFRAME_PG_PORT=55432

mkdir -p "$MAINFRAME_PG_SOCKET"
"$MAINFRAME_PG_BIN/initdb" -D "$MAINFRAME_PG_DATA" --auth=trust
"$MAINFRAME_PG_BIN/pg_ctl" \
  -D "$MAINFRAME_PG_DATA" \
  -o "-h '' -k $MAINFRAME_PG_SOCKET -p $MAINFRAME_PG_PORT" \
  -w start
createuser \
  --host="$MAINFRAME_PG_SOCKET" \
  --port="$MAINFRAME_PG_PORT" \
  --username="$(id -un)" \
  --superuser \
  postgres
createdb \
  --host="$MAINFRAME_PG_SOCKET" \
  --port="$MAINFRAME_PG_PORT" \
  --username=postgres \
  dragonfly
```

Run tests with:

```bash
DRAGONFLY_GITHUB_TOKEN=test \
  DB_URL="postgresql+psycopg2://postgres:postgres@/dragonfly?host=$MAINFRAME_PG_SOCKET&port=$MAINFRAME_PG_PORT" \
  uv run --locked pytest
```

Stop the disposable server after validation:

```bash
"$MAINFRAME_PG_BIN/pg_ctl" -D "$MAINFRAME_PG_DATA" -m fast -w stop
```

## Workspace Tools

Hadolint and the audited `prek` runner are installed at:

* `/home/rem/github/vipyrsec/.tools/bin/hadolint`
* `/home/rem/github/vipyrsec/.tools/bin/prek-workspace`

Run the repository hook suite with:

```bash
/home/rem/github/vipyrsec/.tools/bin/prek-workspace run --all-files
```
