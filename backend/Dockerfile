# ── JobForge Backend — Dockerfile ──────────────────────────────────────────
# Works on M1 Mac (arm64) and x86_64
# Ollama runs on the HOST (not in Docker) to keep Metal GPU acceleration

FROM python:3.11-slim

WORKDIR /app

# System dependencies
# - WeasyPrint (PDF generation): pango, gdk-pixbuf, cairo
# - Playwright (Apply Agent): Chromium deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    # WeasyPrint
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    libcairo2 \
    # Playwright Chromium
    libnss3 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps (cached layer — only re-runs if requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright browser (Chromium only)
RUN playwright install chromium --with-deps

# Copy source code (changes often — last layer)
COPY . .

# Create documents directory for generated PDFs
RUN mkdir -p /app/documents

EXPOSE 8000

# Hot-reload in dev; swap for gunicorn in production
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
