# MediaHub — production Docker image
# Build:  docker build -t mediahub:latest .
# Run:    docker run -p 5000:5000 --env-file .env mediahub:latest
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=5000 \
    PYTHONPATH=/app/src

# System deps:
#  - libpangocairo / fonts: WeasyPrint (graphic_renderer fallback)
#  - libnss3 / libxss1 / libgbm1: Chromium/Playwright runtime
#  - poppler-utils: PDF parsing in interpreter
#  - libgl1: image/video preprocessing
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates gnupg \
    poppler-utils \
    libgl1 \
    libpango-1.0-0 libpangocairo-1.0-0 libcairo2 libffi-dev \
    libnss3 libxss1 libgbm1 libasound2 libatk-bridge2.0-0 libatk1.0-0 \
    libcups2 libdrm2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libxshmfence1 libxkbcommon0 \
    fonts-liberation \
  && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
  && apt-get install -y --no-install-recommends nodejs \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching).
COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip \
 && pip install -r /app/requirements.txt \
 && pip install gunicorn

# Install Playwright + Chromium for graphic_renderer's HTML→PNG step.
# (Optional: comment out if you only need the WeasyPrint fallback.)
RUN pip install playwright \
 && playwright install --with-deps chromium

# Copy app code.
COPY src/ /app/src/
COPY data/ /app/data/
COPY legacy/ /app/legacy/
COPY samples/ /app/samples/
COPY scripts/ /app/scripts/
COPY pyproject.toml /app/pyproject.toml

# Install MediaHub itself in editable mode so the console script is wired.
RUN pip install -e /app

# Install Remotion node modules so /api/.../motion + /reel render MP4s.
RUN cd /app/src/mediahub/remotion && npm install --no-audit --no-fund

# Create runtime dirs (mounted volumes will overlay these).
RUN mkdir -p /app/runs_v4 /app/uploads_v4 /app/.cache \
 && chmod +x /app/scripts/docker-entrypoint.sh

EXPOSE 5000

# Health check.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:${PORT}/healthz || exit 1

# Entrypoint does the persistent-disk setup (mkdir + first-boot seed
# from /app/data) then exec's gunicorn. Keeps the startup behaviour
# in one place that's shared between local docker run and Render.
CMD ["/app/scripts/docker-entrypoint.sh"]
