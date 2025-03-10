# Contributing Guide

Requirements:

- [Python 3.12](https://www.python.org/downloads/)
- [Git](https://git-scm.com/downloads)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- [Docker](https://docs.docker.com/engine/install/)

## Getting Started

If you are a member of the organization, create a branch, and a pull request when you are finished.

```sh
git clone https://github.com/vipyrsec/dragonfly-mainframe.git
```

Otherwise, work from a fork of the repository and create a pull request when you're done.
Once you've forked the repository, go ahead and clone that fork with the following command.

```sh
git clone https://github.com/<YourUsernameHere>/dragonfly-mainframe.git
```

Make sure to replace `<YourUsernameHere>` with your GitHub username.

Now that you have your hands on the code, you can run

```sh
cd dragonfly-mainframe
```

Replace `dragonfly-mainframe` with the directory into which you cloned your repository.

Next, you'll want to install the project dependencies, with `uv`. You can do so with the following command.

```sh
uv sync
```

You can activate the virtual environment with one of the following commands.

```sh
source .venv/bin/activate  # If you're using a POSIX-compliant shell such as bash/zsh
source .venv/bin/activate.fish  # If you're using fish
.venv\Scripts\activate  # If you're using Powershell
```

We use `pre-commit` to manage this project's pre-commit hooks, which are run before each commit you make to ensure your
code follows linting and style rules.
You can view the configuration in `.pre-commit-config.yaml`.
You should install the hooks with the following command.

```sh
uv run pre-commit install
```

You can run the following command to run the pre-commit hooks at any time.

```sh
make pre-commit
```

We recommend using `Docker` and `docker compose` for running the API, as that handles most of the setup regarding
environment variables and such for you.
You can run the API with the following command which will invoke `docker compose` for you.

```sh
make start
```

## Tests

### Writing tests

We use `pytest` to run our tests. Tests go in the `tests/` directory.
The tests for each python module should go in a separate tests file.

We use `httpx` for making requests to the API. Use the fixture `api_url` for the URL to make requests to.
For example:

```py
def test_root(api_url: str):
    r = httpx.get(api_url)
    assert r.status_code == 200
```

Additionally, we can connect to the database to check if our request had the desired effect.
The `db_session` fixture gives a `sqlalchemy.orm.Session` that you can use to make queries.
The database is preloaded with some test data.
For example:

```py
def test_query(api_url: str, db_session: Session):
    r = httpx.get(api_url + "/package?name=a&version=0.1.0")
    data = r.json()
    assert r["name"] == "a"
```

All database changes are rolled back after each test, so you are given a fresh database with the original test data
every time.

### Running the tests

#### Using Docker (Recommended)

Use `make test`. This should be the go-to method.

#### Manual setup

Alternatively you can run PostgreSQL locally or in a container, then run the server using `uv run python -m uvicorn
src.mainframe.server:app`.
To run the tests, use `uv run pytest`.
If you choose to use this method, be sure to set the environment variable `DB_URL` to the appropriate value, so that the
tests can connect to the database.
You can also use manual testing via a browser, or `curl`, for example, but this requires some additional setup,
described in the Database Migrations section below.

## Running the API

### Using Docker (Recommended)

Use `docker` and `docker compose` to run the API, as that handles most of the setup regarding environment variables and
such for you.
You can do so by running the following command, which is an alias for `docker compose up --build`.

```sh
make start
```

### Manual setup

Alternatively, you'll want to run PostgreSQL locally or in a container, and run the API manually by invoking `entrypoint.sh`.

```sh
./entrypoint.sh
```

You'll need to have the following environment variables set.

<!-- markdownlint-disable MD013 -->

| Environment Variable                 | Type | Default                                                  | Description                                                                                                                                                 |
| ------------------------------------ | ---- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `AUTH0_DOMAIN`                       | str  | "vipyrsec.us.auth0.com"                                  | Authentication domain for Auth0                                                                                                                             |
| `AUTH0_AUDIENCE`                     | str  | "dragonfly.vipyrsec.com"                                 | Audience field for Auth0                                                                                                                                    |
| `DRAGONFLY_GITHUB_TOKEN`             | str  |                                                          | Github PAT for accessing YARA rules in the security-intelligence repository                                                                                 |
| `JOB_TIMEOUT`                        | int  | 60 \* 2                                                  | The maximum time to wait for clients to respond with job results. After this time has elapsed, the server will begin distributing this job to other clients |
|                                      |      |                                                          |                                                                                                                                                             |
| `REPORTER_URL`                       | str  | ""                                                       | The url of the reporter microservice                                                                                                                        |
| `DB_URL`                             | str  | "postgresql+psycopg2://postgres:postgres@localhost:5432" | PostgreSQL database connection string                                                                                                                       |
| `DB_CONNECTION_POOL_MAX_SIZE`        | int  | 15                                                       | The max number of concurrent database connections                                                                                                           |
| `DB_CONNECTION_POOL_PERSISTENT_SIZE` | int  | 5                                                        | The number of concurrent database connections to maintain in the connection pool                                                                            |
|                                      |      |                                                          |                                                                                                                                                             |
| `SENTRY_DSN`                         | str  | ""                                                       | Sentry Data Source Name (DSN)                                                                                                                               |
| `SENTRY_ENVIRONMENT`                 | str  | ""                                                       | Sentry environment                                                                                                                                          |
| `SENTRY_RELEASE_PREFIX`              | str  | ""                                                       | Sentry release prefix                                                                                                                                       |

<!-- markdownlint-enable MD013 -->

**NOTE**: Environment variables where the `default` column is empty are required for the application to startup.

**NOTE**: Environment variables with type `str` and `default` `""` are not required for the application to startup but
may cause the application to function incorrectly.

## Database Migrations

We use `Alembic` to manage database migrations.
Migrations handle changes between versions of a database schema.
You only need to worry about this if you want to run manual tests, or you have made changes to the database schema.

### Generating revisions

For each schema change, you should create a revision file using `uv run alembic revision --autogenerate -m "<short
change message>"`.

**Always** check the generated migrations to see if they are accurate. There are many situations where alembic is unable
to generate them correctly. You can refer to [this
page](https://alembic.sqlalchemy.org/en/latest/autogenerate.html#what-does-autogenerate-detect-and-what-does-it-not-detect)
for more details.

### Running migrations

For manual testing, run `uv run alembic upgrade head` in order to set up the database.
