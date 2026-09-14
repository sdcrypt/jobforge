# 🔨 JobForge

> **Forge your next career move.**  
> Local AI-powered job search, fit analysis, and document generation — runs entirely on your Mac. No cloud, no paid APIs, no subscriptions.

---

## What it does

JobForge automates the repetitive parts of job hunting:

1. **Searches** multiple job portals simultaneously for roles matching your keywords and locations
2. **Scores** every job against your profile (fit score 0–100) with sub-scores for tech, experience, location, and growth
3. **Deep-analyses** top jobs with AI — strengths, gaps, and talking points tailored to each role
4. **Generates** a professional one-pager CV + cover letter as PDF, tailored per job
5. **Tracks** everything locally — no data leaves your machine

---

## Architecture

```
Your Mac
├── Ollama (host)              ← Local LLM, Metal GPU acceleration
│   ├── qwen2.5:7b             ← Smart model: research, docgen, rank
│   └── llama3.2:3b            ← Fast model: search, quick tasks
└── Docker Compose
    ├── frontend  :3000        ← Next.js 15 UI
    ├── backend   :8000        ← FastAPI + WebSocket agent feed
    ├── postgres  :5432        ← Job store, profile, config
    └── redis     :6379        ← Celery task queue
```

Everything talks to Ollama at `host.docker.internal:11434` — the LLM never leaves your machine.

---

## AI Agents

| Agent | Model | What it does |
|-------|-------|-------------|
| 🔍 **Search** | Fast | Scrapes job portals in parallel, deduplicates results |
| 📊 **Rank** | Smart | Quick-scores every new job against your profile |
| 🔬 **Research** | Smart | Deep-analyses a job: fit score, strengths, gaps, talking points |
| 📄 **DocGen** | Smart | Generates tailored one-pager CV + cover letter as PDF |
| ✉️ **Apply** | Smart | (Planned) Browser automation for form filling |
| 🧠 **Coordinator** | Smart | Orchestrates multi-step agent workflows |

All agents emit real-time events to the frontend via WebSocket — you watch them think live.

---

## Job Portals

| Portal | Type | Coverage |
|--------|------|----------|
| 🔗 **LinkedIn** | HTML scrape (guest API) | Global, all industries — up to 4 pages × 25 results |
| 🌍 **RemoteOK** | Free JSON API | Remote tech jobs, salary data included |
| 🏠 **We Work Remotely** | RSS feed | Senior remote roles, 3 category feeds |
| 🟠 **HackerNews Hiring** | Algolia API | Monthly "Who is Hiring" thread — startups, founding roles |

> Portals with reCAPTCHA v3 (Naukri, Indeed, Glassdoor) block automated scraping and are not included. Google Careers and Amazon Jobs are on the roadmap.

---

## Key Features

### Search & Pipeline
- Multi-portal parallel search with configurable depth
- **Configurable search depth** — results per search (5–100), LinkedIn pages (1–4)
- Two-layer deduplication: exact URL + company+title match
- Auto-runs on a schedule (`run_every_hours` in config)

### AI Research (per job)
- Fetches full job description from the posting URL
- LLM analysis against your profile → fit score, tech/exp/location/growth sub-scores
- Specific strengths, gaps, and cover letter talking points
- **Auto-research** — top N jobs by score are analysed automatically after each pipeline run (configurable, default: top 5)

### Documents
- **One-pager CV** — professional two-column A4 PDF, tailored per job with fit score badge
- **Cover letter** — matching header, tailored body referencing the specific role
- WeasyPrint HTML→PDF (no LaTeX, no Puppeteer)

### Profile
- Drag-and-drop resume upload (PDF or DOCX)
- AI auto-parses resume → pre-fills your entire profile
- Skills with proficiency levels (beginner / intermediate / expert)
- Full experience history with per-role highlights

### Frontend
- Real-time agent activity feed (WebSocket)
- Jobs board with status tabs and fit score filter
- Dismiss jobs to hide them, clear all to reset
- Research panel expands inline on each job card

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, TypeScript, Tailwind CSS, SWR |
| Backend | FastAPI (async), SQLAlchemy 2.0, Pydantic v2 |
| LLM | Ollama (local) — swap to OpenAI/Groq via `.env` |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Task Queue | Celery + Redis |
| PDF | WeasyPrint + Jinja2 templates |
| Resume Parse | pypdf (PDF), python-docx (DOCX) |
| Scraping | httpx (async) + BeautifulSoup4 |
| Containers | Docker Compose |

---

## Build Status

| Phase | Feature | Status |
|-------|---------|--------|
| 1–3 | Backend scaffold — agents, DB, WebSocket, API | ✅ Done |
| 4 | Next.js frontend — Jobs, Search Config, Profile, AgentFeed | ✅ Done |
| 4.5 | Resume upload + AI auto-parse, one-pager + cover letter redesign | ✅ Done |
| 5A | Research Agent — AI job-fit analysis per job | ✅ Done |
| 5B | Auto-research — top N jobs analysed after every pipeline run | ✅ Done |
| — | 4 working portals (LinkedIn, RemoteOK, WWR, HackerNews) | ✅ Done |
| — | Configurable search depth (results per search, LinkedIn pages) | ✅ Done |
| — | Job dismiss, clear, status tracking | ✅ Done |

---

## LLM Configuration

Default: **Ollama** (local, free, private).

```env
# backend/.env
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama
LLM_MODEL_SMART=qwen2.5:7b
LLM_MODEL_FAST=llama3.2:3b
```

Switch to any OpenAI-compatible provider with no code changes:

```env
# OpenAI
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key
LLM_MODEL_SMART=gpt-4o
LLM_MODEL_FAST=gpt-4o-mini
```

---

## Setup

See **[SETUP_MAC.md](SETUP_MAC.md)** for the full step-by-step setup guide on Mac M1.

Quick start (after Ollama is running with models pulled):

```bash
cd jobforge
docker compose up --build
```

Then open:
- **App** → http://localhost:3000
- **API docs** → http://localhost:8000/docs
- **Health** → http://localhost:8000/health

---

## Workflow

1. **Profile** → fill in your details or drag-drop your resume to auto-parse
2. **Search Config** → set keywords, locations, portals, search depth, auto-research N
3. **Run Pipeline** → Search → Rank → Auto-research top N → results appear live
4. **Jobs** → browse ranked cards, click 📊 Analysis to see full AI fit report
5. **Docs** → click 📄 Docs to generate tailored one-pager + cover letter PDF
6. **Apply** → open the job URL, use the generated PDFs to apply

---

## Design Decisions

- **Local only** — Ollama on host Mac, all data in local Docker volumes. Nothing goes to the cloud.
- **Single user** — designed for personal use. No auth, no multi-tenancy.
- **No system installs** — all Python dependencies run inside Docker. Only Ollama is installed on the host (for Metal GPU access).
- **Provider-agnostic LLM** — same `openai` SDK throughout. Swap providers by changing `.env`.
- **No Playwright for scraping** — reCAPTCHA v3 blocks headless browsers on most job portals anyway. httpx + BeautifulSoup is faster and more reliable for the portals that work.
