# Contributing Guide

welcome, or something

# Setting up the dev environment
## PDM
We use `pdm` to manage dev dependencies.
You can install `pdm` here [https://pdm.fming.dev/latest/#recommended-installation-method](https://pdm.fming.dev/latest/#recommended-installation-method).

Once installed, use `pdm install -d` to install dev dependencies.

## Tests
### Writing tests
We use `pytest` to run our tests. Tests go in the `tests/` directory.
The tests for each python module should go in a separate tests file.

We use `requests` for making requests to the API. Use the fixture `api_url` for the URL to make requests to.
For example:
```py
def test_root(api_url: str):
    r = requests.get(api_url)
    assert r.status_code == 200
```
Additionally, we can connect to the database to check if our request had the desired effect.
The `db_session` fixture gives a `sqlalchemy.orm.Session` that you can use to make queries.
The database is preloaded with some test data.
For example:
```py
def test_query(api_url: str, db_session: Session):
    r = requests.get(api_url + "/package?name=a&version=0.1.0")
    data = r.json()
    assert r["name"] == "a"
```
All database changes are rolled back after each test, so you are given a fresh database with the original test data every time.

### Running the tests
#### Method 1 - Recommended
Use `pdm test`. This should be the go-to method.

#### Method 2
Alternatively you can run Postgresql locally or in a container, then run the server using `pdm run python -m uvicorn src.mainframe.server:app`.
To run the tests, use `pdm run pytest`.
If you choose to use this method, be sure to set the environment variable `DB_URL` to the appropriate value, so that the tests can connect to the database.
You can also use manual testing via a browser, or `curl`, for example, but this requires some additional setup, described in the Database Migrations section below.

# Database Migrations
We use `Alembic` to manage database migrations.
Migrations handle changes between versions of a database schema.
You only need to worry about this if you want to run manual tests, or you have made changes to the database schema.

## Generating revisions
For each schema change, you should create a revision file using `pdm run alembic revision --autogenerate -m "<short change message>"`.

**Important**: You must then edit the created file and make sure it is correct.

## Running migrations
For manual testing, run `pdm run alembic upgrade head` in order to set up the database. If you get an error along the lines of `relation "packages" does not exist`, then you probably did not run the migration.

## Environment Variables
The following table illustrates configuration options in the form of environment variables that may be set.


| Environment Variable    | Type | Default                                                 | Description                                                                                                                                                 |
|-------------------------|------|---------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `PRODUCTION`              | bool | True                                                    | Flag that sets if the instance is running in a production environment or not. Non-production environments do not enforce authentication.                    |
| `AUTH0_DOMAIN`            | str  | "vipyrsec.us.auth0.com"                                 | Authentication domain for Auth0                                                                                                                             |
| `AUTH0_AUDIENCE`          | str  | "dragonfly.vipyrsec.com"                                | Audience field for Auth0                                                                                                                                    |
| `DRAGONFLY_GITHUB_TOKEN`  | str  |                                                         | Github PAT for accessing YARA rules in the security-intelligence repository                                                                                 |
| `JOB_TIMEOUT`             | int  | 60 * 2                                                  | The maximum time to wait for clients to respond with job results. After this time has elapsed, the server will begin distributing this job to other clients |
|                         |      |                                                         |                                                                                                                                                             |
| `EMAIL_RECIPIENT`         | str  | "security@pypi.org"                                     | The recipient address of report emails                                                                                                                      |
| `BCC_RECIPIENTS`          | set  | set()                                                   | Additional addresses that should be BCC'd in email reports. Defaults to an empty set.                                                                       |
| `DB_URL`                  | str  | "postgresql+asyncpg://postgres:postgres@localhost:5432" | PostgreSQL database connection string                                                                                                                       |
|                         |      |                                                         |                                                                                                                                                             |
| `SENTRY_DSN`              | str  | ""                                                      | Sentry Data Source Name (DSN)                                                                                                                               |
| `SENTRY_ENVIRONMENT`      | str  | ""                                                      | Sentry environment                                                                                                                                          |
| `SENTRY_RELEASE_PREFIX`   | str  | ""                                                      | Sentry release prefix                                                                                                                                       |
|                         |      |                                                         |                                                                                                                                                             |
| `MICROSOFT_TENANT_ID`     | str  |                                                         | Microsoft tenant ID for automated emails                                                                                                                    |
| `MICROSOFT_CLIENT_ID`     | str  |                                                         | Microsoft client ID for automated emails                                                                                                                    |
| `MICROSOFT_CLIENT_SECRET` | str  |                                                         | Microsoft client secret for automated emails                                                                                                                |

**NOTE**: Environment variables with type `str` and `default` `""` are not required for the application to startup but may cause the application to function incorrectly
