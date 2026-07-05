FROM python:3.11-slim

WORKDIR /app

COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

# Flush stdout immediately so logs appear live in `docker compose logs -f`
ENV PYTHONUNBUFFERED=1

# Create the user and volume paths BEFORE declaring VOLUME: the legacy
# builder discards changes made to a path after its VOLUME declaration.
RUN adduser --system --group --no-create-home app \
    && mkdir -p /app/data /app/logs \
    && chown -R app:app /app/data /app/logs
USER app

# Persist coaching data outside the container image
VOLUME ["/app/data", "/app/docs/knowledge"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s CMD \
    python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/live')"

# Single worker by design: the app keeps its state in an on-disk SQLite file
# plus in-process caches (tool-router embedding index, rerank model). Extra
# uvicorn workers in one container each duplicate that warm-up work and race
# each other to initialize the SQLite schema on first boot (observed
# intermittently as a "Child process died" self-healing restart even with
# WAL + busy_timeout). Scale horizontally with separate container replicas
# behind a load balancer instead of raising --workers here.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
