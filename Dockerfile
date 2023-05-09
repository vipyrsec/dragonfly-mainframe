FROM python:3.11-slim@sha256:181e49146bfdc8643ebe0f66cd06f27f42df40a0921438e96770dab09797effb AS builder

RUN pip install -U pip setuptools wheel
RUN pip install pdm

WORKDIR /app
COPY pyproject.toml pdm.lock ./
COPY src/ src
RUN python -m pdm install --prod --no-lock --no-editable

CMD ["pdm", "run", "python", "-m", "uvicorn", "src.__main__:app"]

EXPOSE 8000
