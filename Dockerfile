FROM python:3.11-slim@sha256:1966141ab594e175852a033da2a38f0cb042b5b92896c22073f8477f96f43b06 as builder

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

FROM python:3.11-slim@sha256:1966141ab594e175852a033da2a38f0cb042b5b92896c22073f8477f96f43b06 as prod

ENV PYTHONPATH=/app/pkgs
ENV PRODUCTION=true
WORKDIR /app
COPY --from=builder /app/__pypackages__/3.11/lib pkgs/

COPY alembic/ alembic/
COPY alembic.ini ./
COPY src/ src/
COPY entrypoint.sh ./
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]

EXPOSE 8000
