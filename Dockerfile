FROM python:3.11-slim@sha256:53a67c012da3b807905559fa59fac48a3a68600d73c5da10c2f0d8adc96dbd01 as builder

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

CMD ["pdm", "run", "pytest", "tests", "-vv"]

FROM python:3.11-slim@sha256:53a67c012da3b807905559fa59fac48a3a68600d73c5da10c2f0d8adc96dbd01 as prod

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

CMD ["./entrypoint.sh"]

EXPOSE 8000
