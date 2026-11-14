FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.13.8 /uv /usr/local/bin/uv
WORKDIR /app
# Dependencies first so a code-only change reuses the cached layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY medsync_agent ./medsync_agent
RUN useradd --system medsync
USER medsync
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "medsync_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
