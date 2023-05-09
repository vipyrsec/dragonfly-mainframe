# Contributing guide

welcome, or something

## Setting up the dev environment
### PDM
We use `pdm` to manage dev dependencies. You can install `pdm` here [https://pdm.fming.dev/latest/#recommended-installation-method](https://pdm.fming.dev/latest/#recommended-installation-method).

Once installed, use `pdm install -d` to install dev dependencies.

### Postgres
We use postgres to store packages. I recommend simply using the postgres docker container.

Something like, `docker run --rm -it -e POSTGRES_PASSWORD=postgres postgres`

Once postgres is installed and running, you can run the alembic migrations with `pdm run alembic upgrade head`.

For each schema change, you should create a revision file using `pdm run alembic revision --autogenerate -m "<short change message>"`.
**Important**: You must then edit the created file and make sure it is correct.
