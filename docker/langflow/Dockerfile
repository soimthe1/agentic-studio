# syntax=docker/dockerfile:1.7
# Agent Studio (agent-studio) - ENGINE image: the Langflow agent runtime + its builder canvas.
# The Agent Studio app (backend/, frontend/) talks to it over HTTP; see docker/app/Dockerfile.
# Upstream Langflow is used unmodified from pinned wheels; the canvas front end is rebuilt from the
# same upstream tag with branding/ applied (file list: docs/patches.md). No source fork.

ARG LANGFLOW_TAG=v1.13.2
ARG LANGFLOW_SRC_SHA256=9b1f4a0cc8a2707e9497e887fae7f64873298791c7ce00289da92a2108ba8a13

# ---- builder canvas: upstream source + Agent Studio branding -> static build ----
FROM node:20-slim AS canvas
ARG LANGFLOW_TAG
ARG LANGFLOW_SRC_SHA256
ADD --checksum=sha256:${LANGFLOW_SRC_SHA256} \
    https://codeload.github.com/langflow-ai/langflow/tar.gz/refs/tags/${LANGFLOW_TAG} /tmp/langflow.tgz
RUN mkdir /fe && tar -xzf /tmp/langflow.tgz -C /fe --strip-components=3 --wildcards '*/src/frontend/*' && rm /tmp/langflow.tgz
WORKDIR /fe
RUN npm ci --no-audit --no-fund
# Self-hosted fonts (OFL-1.1), replacing Google Fonts.
RUN mkdir -p /fonts && cd /fonts \
 && for p in @fontsource-variable/inter@5.3.0 @fontsource-variable/jetbrains-mono@5.3.0 @fontsource/ibm-plex-sans-arabic@5.3.0; do \
      d=$(echo $p | sed 's#.*/##; s#@.*##'); mkdir $d; npm pack -q $p | xargs -I{} tar -xzf {} -C $d --strip-components=1; rm -f *.tgz; done \
 && printf '@import "inter/index.css";\n@import "jetbrains-mono/index.css";\n@import "ibm-plex-sans-arabic/400.css";\n@import "ibm-plex-sans-arabic/600.css";\n@import "ibm-plex-sans-arabic/700.css";\n' > fonts.css
COPY branding/ /branding/
# Same heap/job settings as upstream docker/build_and_push.Dockerfile.
RUN node /branding/apply-branding.mjs /branding /fe /fonts \
 && ESBUILD_BINARY_PATH="" NODE_OPTIONS="--max-old-space-size=4096" JOBS=1 npm run build

# ---- runtime ----
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 UV_NO_CACHE=1
RUN pip install uv==0.11.28 && useradd -m -u 1000 -s /usr/sbin/nologin langflow
COPY docker/langflow/requirements.lock /tmp/requirements.lock
RUN uv pip install --system --require-hashes -r /tmp/requirements.lock && rm /tmp/requirements.lock
# Agent Studio engine extension (config adapter + session endpoint) and the approved tools bundle.
COPY engine /tmp/studio_engine
COPY tools/studio_tools /tmp/studio_tools
RUN uv pip install --system --no-deps /tmp/studio_engine /tmp/studio_tools && rm -rf /tmp/studio_engine /tmp/studio_tools \
 && install -d -o langflow -g langflow /home/langflow/.cache/langflow /data/files /data/contracts /data/toolkit/wheels /data/toolkit/site
COPY --from=canvas /fe/build /app/frontend
# config/ is mounted at runtime (/app/config), never baked into the image.
ENV CONFIG_DIR=/app/config
USER langflow
WORKDIR /app
EXPOSE 7860
HEALTHCHECK --interval=10s --timeout=5s --start-period=180s --retries=10 \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:7860/health')"
ENTRYPOINT ["python", "-m", "studio_engine.entrypoint"]
