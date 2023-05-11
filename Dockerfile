FROM python:3.11-slim@sha256:181e49146bfdc8643ebe0f66cd06f27f42df40a0921438e96770dab09797effb as builder

RUN pip install -U pip setuptools wheel
RUN pip install pdm

WORKDIR /app
COPY pyproject.toml pdm.lock ./
COPY src/ src/
RUN mkdir __pypackages__ && python -m pdm install --prod --no-lock --no-editable

############################################
FROM python:3.11-slim@sha256:181e49146bfdc8643ebe0f66cd06f27f42df40a0921438e96770dab09797effb as test

RUN pip install -U pip setuptools wheel
RUN pip install pdm


WORKDIR /app
COPY tests/ tests/
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini pyproject.toml pdm.lock ./
RUN python -m pdm install -d

CMD ["python", "-m", "pdm", "run", "pytest"]

############################################
FROM python:3.11-slim@sha256:181e49146bfdc8643ebe0f66cd06f27f42df40a0921438e96770dab09797effb as prod

ENV PYTHONPATH=/app/pkgs
WORKDIR /app

COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini entrypoint.sh ./
RUN chmod +x entrypoint.sh

CMD ["./entrypoint.sh"]

EXPOSE 8000
