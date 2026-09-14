# JobForge — Setup Guide (Mac M1/M2/M3)

## What runs where

```
Your Mac (host)
├── Ollama                     ← LLM server, uses Metal GPU
│   ├── qwen2.5:7b             ← Smart model (~4.7 GB)
│   └── llama3.2:3b            ← Fast model (~2.0 GB)
└── Docker Desktop
    ├── frontend   :3000       ← Next.js 15 UI
    ├── backend    :8000       ← FastAPI + agents + WebSocket
    ├── postgres   :5432       ← SQLite in dev, Postgres in prod
    └── redis      :6379       ← Celery task queue
```

**Nothing is installed on your system Python.** Ollama runs on the host for Metal GPU acceleration. Everything else is in Docker.

---

## Prerequisites checklist

- [ ] Mac with Apple Silicon (M1/M2/M3)
- [ ] Docker Desktop installed and running
- [ ] Ollama installed with models pulled
- [ ] ~15 GB free disk space (models + images)

---

## Step 1 — Install Docker Desktop

Download from: https://www.docker.com/products/docker-desktop/

Choose **Apple Silicon**. After install, open Docker Desktop and wait for the whale icon in the menu bar to stop animating (engine ready).

Verify:
```bash
docker --version
docker compose version
```

---

## Step 2 — Install Ollama

Download from: https://ollama.com/download/mac  
*(Or via Homebrew: `brew install ollama`)*

**Start the Ollama server** (keep this running in a terminal tab or set it as a background service):
```bash
ollama serve
```

**Pull the two models** (one-time download, ~7 GB total):
```bash
# Open a new terminal tab while `ollama serve` is running

# Smart model — research, ranking, doc generation
ollama pull qwen2.5:7b

# Fast model — search, quick calls
ollama pull llama3.2:3b
```

Verify models are ready:
```bash
ollama list
# NAME            SIZE    MODIFIED
# qwen2.5:7b      4.7 GB  ...
# llama3.2:3b     2.0 GB  ...
```

---

## Step 3 — Clone the repo

```bash
cd ~/Documents/Python
git clone <your-repo-url> jobforge
cd jobforge
```

---

## Step 4 — Configure environment

```bash
cp backend/.env.example backend/.env
```

The default `.env` is pre-configured for Ollama on Mac. No changes needed:

```env
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama
LLM_MODEL_SMART=qwen2.5:7b
LLM_MODEL_FAST=llama3.2:3b
DATABASE_URL=sqlite+aiosqlite:///./jobforge.db
```

> `host.docker.internal` is the Docker magic hostname that lets containers reach Ollama running on your Mac host.

---

## Step 5 — Build and start everything

```bash
# From the jobforge/ root (where docker-compose.yml lives)
docker compose up --build
```

First build takes 3–8 minutes (downloads images, installs Python deps, builds Next.js).  
Subsequent starts take ~15 seconds.

You should see:
```
jobforge-backend-1   | INFO: JobForge startup complete
jobforge-backend-1   | INFO: DB tables ready
jobforge-backend-1   | INFO: Uvicorn running on http://0.0.0.0:8000
jobforge-frontend-1  | ✓ Ready in 2.1s on http://0.0.0.0:3000
```

---

## Step 6 — Verify everything works

**Health checks:**
```bash
# Backend up?
curl http://localhost:8000/health

# Ollama connected?
curl http://localhost:8000/health/llm
# Expected: {"status": "connected", "model": "llama3.2:3b"}
```

**Open the app:**
- **UI** → http://localhost:3000
- **API docs** (Swagger) → http://localhost:8000/docs

---

## Step 7 — First use

### 1. Set up your profile
Go to **My Profile** (👤) → either:
- **Drag and drop your resume** (PDF or DOCX) → AI auto-fills the form
- Or fill in manually: name, headline, skills, experience, education

Click **Save Profile**.

### 2. Configure your search
Go to **Search Config** (🔍) and fill in:
- **Keywords** — e.g. `Senior Software Engineer, Backend Engineer, Python Developer`
- **Locations** — e.g. `Remote, London, Dubai, Berlin` (add all you want)
- **Portals** — toggle which ones to search (all 4 on by default)
- **Search Depth** — results per search (default 15), LinkedIn pages (default 1)
- **Auto-research** — how many top jobs to AI-analyse after each run (default 5)

Click **Save Config**.

### 3. Run the pipeline
Click **🚀 Run Now** — or go to the **Jobs** page and click **Run Pipeline**.

Watch the **Agent Feed** panel (bottom-left or sidebar) for live progress:
```
search  ▶ Searching 4 portals — 2 keywords × 2 locations…
search  ✓ Found 47 unique jobs across 4 portals
pipeline ● Stored 31 new jobs. Starting ranking…
rank    ✓ Ranked 31 jobs
pipeline ✓ Pipeline complete — 31 new jobs, 31 ranked
research ▶ Auto-researching top 5 jobs…
research ● Researched 2/5 jobs…
research ✓ Auto-research complete — 5/5 jobs analysed
```

### 4. Browse jobs
Go to **Jobs** (💼):
- Jobs are sorted by fit score (highest first)
- Use status tabs to filter: All / New / Reviewed / Applied / Rejected
- Use the **Min fit** slider to hide low-score results
- Click **📊 Analysis** on a researched job to see full AI breakdown
- Click **🔍 Research** on any un-researched job to run it manually
- Click **📄 Docs** to generate a tailored one-pager + cover letter PDF

---

## Common commands

```bash
# Start in background (detached)
docker compose up -d

# Start in foreground (see all logs)
docker compose up

# Stop all containers
docker compose down

# Stop and delete all data (full reset)
docker compose down -v

# View backend logs (live)
docker compose logs -f backend

# View frontend logs
docker compose logs -f frontend

# Rebuild after changing requirements.txt or Dockerfile
docker compose up --build

# Open a shell inside the backend container
docker compose exec backend bash

# Restart just the backend (after code changes, if not using --reload)
docker compose restart backend
```

---

## Troubleshooting

### "LLM not connected" error
Make sure Ollama is running on your Mac:
```bash
ollama serve
# Or check if it's already running:
curl http://localhost:11434/api/tags
```

### Jobs page shows nothing after pipeline
Check the backend logs for errors:
```bash
docker compose logs backend | grep -i error
```

Common causes:
- No profile saved → go to Profile page first
- No search config → go to Search Config and save
- Keywords too specific → try broader terms

### Frontend not loading
```bash
docker compose logs frontend
# If build failed, rebuild:
docker compose up --build frontend
```

### Database reset (wipe all jobs and start fresh)
```bash
docker compose down -v
docker compose up -d
```

### Port already in use
If :3000 or :8000 is taken by another app:
```bash
# Find what's using the port
lsof -i :3000
lsof -i :8000
```

---

## Switching LLM provider

All LLM calls go through the OpenAI-compatible client. Edit `backend/.env` and restart:

```bash
# Ollama (default — free, local, private)
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama
LLM_MODEL_SMART=qwen2.5:7b
LLM_MODEL_FAST=llama3.2:3b

# OpenAI (requires API key, costs money)
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key-here
LLM_MODEL_SMART=gpt-4o
LLM_MODEL_FAST=gpt-4o-mini

# Groq (fast inference, free tier available)
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_your-key-here
LLM_MODEL_SMART=llama-3.1-70b-versatile
LLM_MODEL_FAST=llama-3.1-8b-instant
```

After editing `.env`:
```bash
docker compose restart backend
```

No code changes needed — the same `openai` SDK works with all providers.

---

## File structure

```
jobforge/
├── backend/
│   ├── agents/
│   │   ├── base.py          ← BaseAgent: LLM client, WebSocket emit, retry
│   │   ├── search.py        ← SearchAgent: multi-portal scraping
│   │   ├── rank.py          ← RankAgent: quick job scoring
│   │   ├── research.py      ← ResearchAgent: deep AI fit analysis
│   │   ├── docgen.py        ← DocGenAgent: PDF generation
│   │   ├── apply.py         ← ApplyAgent: form automation (planned)
│   │   ├── pipeline.py      ← Search → Rank → Auto-research orchestration
│   │   └── coordinator.py   ← Multi-agent coordinator
│   ├── api/routes/
│   │   ├── jobs.py          ← CRUD, dismiss, research endpoint
│   │   ├── profile.py       ← Profile CRUD + resume parse
│   │   ├── applications.py  ← Doc generation, download, preview
│   │   ├── search_config.py ← Search config CRUD + pipeline trigger
│   │   └── health.py        ← Health + LLM connectivity check
│   ├── core/
│   │   ├── config.py        ← Settings (reads .env)
│   │   ├── database.py      ← SQLAlchemy engine + auto-migrations
│   │   └── websocket.py     ← WebSocket connection manager
│   ├── models/
│   │   ├── job.py           ← Job model (includes research fields)
│   │   ├── profile.py       ← UserProfile model
│   │   ├── search_config.py ← SearchConfig model
│   │   └── application.py   ← Application + AgentEvent models
│   ├── templates/
│   │   ├── one_pager.html   ← Two-column A4 CV template
│   │   └── cover_letter.html← Cover letter template
│   ├── core/resume_parser.py← PDF/DOCX → profile JSON via LLM
│   ├── main.py              ← FastAPI app entry point
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── jobs/        ← Jobs board page
│   │   │   ├── search/      ← Search Config page
│   │   │   └── profile/     ← Profile + resume upload page
│   │   ├── components/
│   │   │   ├── jobs/JobCard.tsx     ← Job card with research panel
│   │   │   ├── agents/AgentFeed.tsx ← Live WebSocket event feed
│   │   │   └── layout/Sidebar.tsx  ← Navigation sidebar
│   │   ├── hooks/
│   │   │   ├── useJobs.ts          ← SWR job list with auto-refresh
│   │   │   └── useAgentFeed.ts     ← WebSocket hook
│   │   └── lib/api.ts              ← Typed API client
│   ├── Dockerfile
│   └── next.config.js
├── docker-compose.yml
└── README.md
```
