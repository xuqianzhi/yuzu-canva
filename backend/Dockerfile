# Override BASE_IMAGE (in .env or with --build-arg) if Docker Hub is blocked.
ARG BASE_IMAGE=python:3.12-slim
FROM ${BASE_IMAGE} AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    CANVAS_DATA_DIR=/app/data

WORKDIR /app
RUN useradd --create-home --uid 10001 app

COPY requirements.txt ./
RUN python3 -m pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
RUN mkdir -p /app/data && chown -R app:app /app
USER app

# No secrets are baked in: API keys come from the environment at run time.
# Cloud Run sets PORT (8080); locally it's 8788. One process: the job worker
# lives inside it, so there must be exactly one.
EXPOSE 8788
CMD ["sh", "-c", "exec uvicorn canvas_api.app:app --host 0.0.0.0 --port ${PORT:-8788} --workers 1 --timeout-graceful-shutdown 8"]


# Adds pytest/ruff. Built only by the `test` compose service.
FROM base AS dev
USER root
COPY requirements-dev.txt ./
RUN python3 -m pip install --no-cache-dir -r requirements-dev.txt
USER app
CMD ["python3", "-m", "pytest", "-q"]


# The image Cloud Run runs (`gcloud run deploy --source` builds the last
# stage): the base image as it is, without the test tools.
FROM base AS prod
