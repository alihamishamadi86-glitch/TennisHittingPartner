# One image for all backend workloads:
#   API:     default (APP_MODULE=app.main:app)
#   Worker:  APP_MODULE=app.worker:app
#   Migrate: command override `alembic upgrade head`
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /srv

COPY pyproject.toml ./
RUN mkdir app && touch app/__init__.py && pip install . && rm -rf app

COPY . .
RUN pip install --no-deps . && useradd --uid 10001 --no-create-home appuser \
    && mkdir -p /srv/media && chown appuser /srv/media
USER appuser

ENV PORT=8080 \
    APP_MODULE=app.main:app
CMD ["sh", "-c", "exec uvicorn ${APP_MODULE} --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
