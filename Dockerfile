FROM python:3.12-slim@sha256:afc139a0a640942491ec481ad8dda10f2c5b753f5c969393b12480155fe15a63 as builder

RUN pip install -U pip setuptools wheel
RUN pip install pdm

WORKDIR /app
COPY pyproject.toml pdm.lock ./
COPY src/ src/
RUN mkdir __pypackages__ && pdm install --prod --no-lock --no-editable
RUN pdm install --prod --no-lock --no-editable

FROM builder as test

RUN pdm install -d

COPY tests/ tests/
ENV env=test
ENV GIT_SHA="testing"

CMD ["pdm", "run", "coverage"]

FROM python:3.12-slim@sha256:afc139a0a640942491ec481ad8dda10f2c5b753f5c969393b12480155fe15a63 as prod

# Define Git SHA build argument for sentry
ARG git_sha="development"
ENV GIT_SHA=$git_sha

ENV PYTHONPATH=/app/pkgs
WORKDIR /app
COPY --from=builder /app/__pypackages__/3.12/lib pkgs/

COPY alembic/ alembic/
COPY alembic.ini ./
COPY src/ src/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

CMD ["sh", "./entrypoint.sh"]

EXPOSE 8000
