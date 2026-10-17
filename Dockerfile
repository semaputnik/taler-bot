# syntax=docker/dockerfile:1
FROM python:3.14-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.6 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Dependencies only: this layer is rebuilt only when pyproject.toml or uv.lock change.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

FROM python:3.14-slim AS runtime
ARG REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/semaputnik/taler-bot" \
      org.opencontainers.image.revision="${REVISION}"
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
# Fixed uid/gid: the operator makes the bind-mounted receipts directory writable for 1000.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data/receipts \
    && chown -R app:app /data
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src ./src
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./
USER app
CMD ["python", "-m", "src"]
