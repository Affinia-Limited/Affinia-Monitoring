# syntax=docker/dockerfile:1.7
# Background worker image (Celery). Same code and dependencies as the API image.
# Scheduler: run this image with `celery -A app.workers.celery_app beat --loglevel=INFO`.

FROM python:3.12-slim AS builder
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /build
COPY requirements.txt .
RUN python -m venv /opt/venv \
 && /opt/venv/bin/pip install --upgrade pip \
 && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app ./app
USER 10001
HEALTHCHECK --interval=60s --timeout=20s --start-period=30s --retries=3 \
  CMD celery -A app.workers.celery_app inspect ping -d "celery@$(hostname)" --timeout 10 >/dev/null 2>&1 || exit 1
CMD ["celery", "-A", "app.workers.celery_app", "worker", "--loglevel=INFO", "--concurrency=4"]
