# The backend container (backend design §8): the FastAPI service with graphrag as its engine library.
# Built from the repository root, as platform/docker-compose.yml does:
#
#   docker build -f backend/Dockerfile -t kg-backend .
#
# Holds only what runs: the two Python packages, the configuration, the schemas and the committed chunk bundle the
# engine loads (graphrag/data.py CHUNKS; graphrag/results for the validated facts). Everything else comes from the
# environment and from volumes: the stores (BACKEND_SOURCE=stores), the model endpoints file, page images, and the
# writable data/interim/ for the question log and the model client's cache.
FROM python:3.12.16-slim@sha256:37fc60d303cb9294d3718b5b48998a0210bb1c73611c1399ef5eb7964c0536e5

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app

COPY backend/requirements-deploy.txt /tmp/requirements-deploy.txt
RUN pip install --no-cache-dir -r /tmp/requirements-deploy.txt && rm /tmp/requirements-deploy.txt

# Code and data belong to root and are read-only to the service; only data/interim/ is the service's to write.
RUN useradd --system --uid 10001 --no-create-home --home-dir /app app
COPY configs/ configs/
COPY schemas/ schemas/
COPY data/processed/gdr_chunks_full.jsonl data/processed/
COPY graphrag/ graphrag/
COPY backend/ backend/
RUN mkdir -p data/interim && chown app:app data/interim

USER app
EXPOSE 8000
# The first health call loads the engine, so it may take a while after a start.
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=8)"]
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
