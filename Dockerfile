FROM python:3.12-slim

ENV POETRY_VERSION=2.1.3 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && pip install --no-cache-dir "poetry==${POETRY_VERSION}" \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml poetry.lock* README.md ./
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./

RUN poetry install --no-ansi --only main

EXPOSE 8000

CMD ["vault-api"]
