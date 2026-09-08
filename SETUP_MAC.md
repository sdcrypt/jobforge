# JobForge — Mac Setup Guide (M1)

## What runs where

```
Your Mac (host)
├── Ollama          ← runs here to keep Metal GPU acceleration
│   └── models: qwen2.5:7b, llama3.2:3b
└── Docker Desktop
    ├── jobforge_backend   (FastAPI on :8000)
    ├── jobforge_postgres  (PostgreSQL on :5432)
    └── jobforge_redis     (Redis on :6379)
```

Nothing is installed on your system Python. Everything runs in containers.

---

## Step 1 — Install Docker Desktop

Download from: https://www.docker.com/products/docker-desktop/

Choose **Apple Silicon** version. After install:
- Open Docker Desktop
- Wait for the whale icon in the menu bar to stop animating (engine started)

---

## Step 2 — Install Ollama (on host, for Metal GPU)

```bash
brew install ollama
```

Or download from: https://ollama.com/download/mac

**Start Ollama** (runs as a background service):
```bash
ollama serve
```

**Pull models** (one-time download, ~7GB total):
```bash
# Open a new terminal tab while ollama serve is running

# Smart model — Coordinator, DocGen, Rank (~4.7GB)
ollama pull qwen2.5:7b

# Fast model — Search agent, parallel calls (~2GB)
ollama pull llama3.2:3b
```

Verify:
```bash
ollama list
# NAME              ID            SIZE    MODIFIED
# qwen2.5:7b        ...           4.7 GB  ...
# llama3.2:3b       ...           2.0 GB  ...
```

---

## Step 3 — Clone & configure

```bash
cd ~/Documents/Python
git clone <your-github-repo-url> jobforge
cd jobforge

# Create .env from template (pre-configured for Ollama + Docker)
cp backend/.env.example backend/.env
```

No changes needed in `.env` — it's ready to go.

---

## Step 4 — Start everything with Docker Compose

```bash
# From the jobforge/ root directory:
docker compose up --build
```

First run takes ~3–5 minutes (downloads Python image, installs deps, pulls Playwright).
Subsequent runs start in seconds.

You'll see:
```
jobforge_postgres  | database system is ready to accept connections
jobforge_backend   | INFO: JobForge starting up
jobforge_backend   | INFO: DB tables created
jobforge_backend   | INFO: Uvicorn running on http://0.0.0.0:8000
```

---

## Step 5 — Verify everything works

```bash
# API is up
curl http://localhost:8000/health

# Ollama connection (backend → host Ollama)
curl http://localhost:8000/health/llm
# Expected: {"status": "connected", "model": "llama3.2:3b", "response": "OK"}
```

Open API docs: http://localhost:8000/docs

---

## Step 6 — Quick first test

```bash
# 1. Create your profile
curl -X POST http://localhost:8000/api/profile \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Sourabh Dixit",
    "email": "sourabh.a.dixit@accenture.com",
    "skills": [
      {"name": "Python", "level": "expert"},
      {"name": "FastAPI", "level": "intermediate"}
    ],
    "target_roles": ["Backend Engineer", "Python Developer"],
    "remote_preference": "remote",
    "salary_min": 80000,
    "salary_currency": "USD"
  }'

# 2. Search for jobs
curl -X POST "http://localhost:8000/api/jobs/search?query=Python+Developer&location=remote"

# 3. Check WebSocket for live agent events (in browser console):
# const ws = new WebSocket("ws://localhost:8000/ws");
# ws.onmessage = e => console.log(JSON.parse(e.data));

# 4. List found jobs
curl http://localhost:8000/api/jobs
```

---

## Common commands

```bash
# Start (foreground — see logs)
docker compose up

# Start (background)
docker compose up -d

# Stop
docker compose down

# Stop + delete database
docker compose down -v

# View backend logs
docker compose logs -f backend

# Rebuild after code changes to requirements.txt
docker compose up --build

# Open a shell inside the backend container
docker compose exec backend bash
```

---

## Switching LLM provider

Edit `backend/.env` — no code changes, no rebuild needed:

```env
# → OpenAI
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key-here
LLM_MODEL_SMART=gpt-4o
LLM_MODEL_FAST=gpt-4o-mini
```

Then restart backend:
```bash
docker compose restart backend
```
