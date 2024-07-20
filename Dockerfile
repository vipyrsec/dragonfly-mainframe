FROM python:3.12-slim@sha256:6bab0b6977b98f24a1c65855a1592152f3c4268afd19adc4da3fde9e7ffb238d as builder

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

FROM python:3.12-slim@sha256:6bab0b6977b98f24a1c65855a1592152f3c4268afd19adc4da3fde9e7ffb238d as prod

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
