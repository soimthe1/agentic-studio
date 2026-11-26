# Agent Studio (agent-studio) - APP image: backend (FastAPI: sign-in, Agent Studio API) + built web app.
# Talks to the engine container over HTTP (config engine.url). Built by .\scripts\dev.ps1 build.

# ---- web app ----
FROM node:20-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN useradd -m -u 1000 -s /usr/sbin/nologin agent-studio && install -d -o agent-studio -g agent-studio /data/files /data/contracts
COPY backend /tmp/backend
RUN pip install /tmp/backend && rm -rf /tmp/backend
COPY --from=web /web/dist /app/web
# config/ is mounted at runtime (/app/config), never baked into the image.
ENV CONFIG_DIR=/app/config BRAND_ROOT=/app/branding
USER agent-studio
WORKDIR /app
EXPOSE 8095
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=6 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8095/health')"
CMD ["uvicorn", "agent_studio.app:app", "--host", "0.0.0.0", "--port", "8095", "--proxy-headers", "--no-server-header"]
