FROM python:3.12-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml uv.lock README.md LICENSE alembic.ini ./
COPY src ./src
COPY alembic ./alembic

RUN pip install --no-cache-dir uv \
    && uv sync --frozen --no-dev --group celery \
    && useradd --create-home --uid 1000 cine \
    && mkdir -p /artifacts /tmp/cine \
    && chown -R cine:cine /app /artifacts /tmp/cine

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    CINE_ARTIFACT_ROOT=/artifacts \
    CINE_API_HOST=0.0.0.0

USER cine
EXPOSE 8000
CMD ["cine-analyzer", "serve", "--host", "0.0.0.0"]
