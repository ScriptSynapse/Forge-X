# FORGE-X application image (FORGE-X 2.0 Phase 11).
# Waitress serves the app; the YARA worker runs as a separate process inside the
# same container, started per scan by app/yara/runner.py (no extra service needed).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# Bootstrap, icons, Chart.js and fonts are served locally (strict CSP): fetch them at build time.
RUN python tools/fetch_vendor.py \
 && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin forgex \
 && mkdir -p /app/instance/evidence_store \
 && chown -R forgex:forgex /app/instance

USER forgex
ENV FLASK_DEBUG=0 \
    FORGE_X_HOST=0.0.0.0 \
    FORGE_X_PORT=8000 \
    EVIDENCE_STORAGE_DIR=/app/instance/evidence_store

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

CMD ["python", "serve.py"]
