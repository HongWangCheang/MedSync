# Slim Python image. Model weights are downloaded on first run into a named volume (see docker-compose.yml),
# so the image itself stays small and a model upgrade doesn't require rebuilding it.
FROM python:3.12-slim
WORKDIR /app

RUN groupadd -r medtrack && useradd -r -g medtrack medtrack

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/.cache && chown -R medtrack:medtrack /app

USER medtrack
ENV MEDTRACK_CACHE_DIR=/app/.cache \
    # The system user has no home directory; keep Hugging Face's own lock/metadata files on the cache volume too.
    HF_HOME=/app/.cache/hf
EXPOSE 8765

# The first start after the label snapshots change embeds every passage (~4,500, a few minutes on CPU); the vectors
# are cached in the model-cache volume, so later starts take seconds.
HEALTHCHECK --interval=10s --timeout=5s --start-period=300s --retries=5 \
    CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8765/health', timeout=4)" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8765"]
