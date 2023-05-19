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
