# The dashboard and the collectors in one image. Market data lives on a volume at /data;
# tastytrade credentials come in as environment variables at run time, never baked in.
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    ALPHASURFACE_DATA_DIR=/data

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /app
# Pinned dependencies first, so code changes reuse this layer.
COPY requirements.lock ./
RUN pip install -r requirements.lock

COPY pyproject.toml README.md CLAUDE.md ./
COPY src ./src
COPY config/symbols.toml config/config.example.toml config/scans.example.toml ./config/
COPY docs ./docs
COPY .streamlit ./.streamlit
# Editable install: the app resolves docs/, config/ and .streamlit/ relative to the repo root.
RUN pip install --no-deps -e . && mkdir -p /data && chown -R app:app /data /app

USER app
VOLUME ["/data"]
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD curl -fsS http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "src/alphasurface/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
