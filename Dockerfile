FROM python:3.11-slim@sha256:4b2e5faf103be72abb65046501a89f8feaef28c1148fc2f9b3326e31694ee735 as builder

RUN pip install -U pip setuptools wheel
RUN pip install pdm

WORKDIR /app
COPY pyproject.toml pdm.lock ./
RUN mkdir __pypackages__ && pdm install --prod --no-lock --no-editable
COPY src/ src/
RUN pdm install --prod --no-lock --no-editable

FROM builder as test

RUN pdm install -d

COPY tests/ tests/
ENV env=test
ENV GIT_SHA="testing"

CMD ["pdm", "run", "coverage"]

FROM python:3.11-slim@sha256:4b2e5faf103be72abb65046501a89f8feaef28c1148fc2f9b3326e31694ee735 as prod

# Define Git SHA build argument for sentry
ARG git_sha="development"
ENV GIT_SHA=$git_sha

ENV PYTHONPATH=/app/pkgs
WORKDIR /app
COPY --from=builder /app/__pypackages__/3.11/lib pkgs/

COPY alembic/ alembic/
COPY alembic.ini ./
COPY src/ src/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

CMD ["sh", "./entrypoint.sh"]

EXPOSE 8000
