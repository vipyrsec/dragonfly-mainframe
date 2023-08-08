FROM python:3.11-slim@sha256:36b544be6e796eb5caa0bf1ab75a17d2e20211cad7f66f04f6f5c9eeda930ef5 as builder

RUN pip install -U pip setuptools wheel
RUN pip install pdm

WORKDIR /app
COPY pyproject.toml pdm.lock .coveragerc ./
RUN mkdir __pypackages__ && pdm install --prod --no-lock --no-editable
COPY src/ src/
RUN pdm install --prod --no-lock --no-editable

FROM builder as test

RUN pdm install -d

COPY tests/ tests/
ENV env=test

CMD ["pdm", "run", "coverage"]

FROM python:3.11-slim@sha256:36b544be6e796eb5caa0bf1ab75a17d2e20211cad7f66f04f6f5c9eeda930ef5 as prod

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
