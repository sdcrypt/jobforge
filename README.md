# 🔨 JobForge

> **Forge your next career move.**  
> AI-powered job search, ranking, document generation, and auto-apply platform.

---

## What it does

JobForge runs 6 AI agents that work together to automate your job search end-to-end:

| Agent | What it does |
|---|---|
| 🧠 **Coordinator** | Orchestrates all agents, decides what to do next |
| 🔍 **Search** | Scrapes job portals (LinkedIn, Indeed…) for matching listings |
| 📊 **Rank** | Scores every job against your profile (0–100) |
| 📄 **DocGen** | Generates a tailored one-pager + cover letter as PDF |
| 🔬 **Research** | Gathers company intel before you apply |
| ✉️ **Apply** | Auto-fills application forms via browser automation |

## Tech Stack

- **Backend**: FastAPI (Python 3.11+)
- **LLM**: Ollama (local, free) → swap to OpenAI/Groq via one `.env` change
- **Database**: SQLite (dev) / PostgreSQL (prod)
- **Real-time**: WebSocket agent activity feed
- **PDF**: WeasyPrint (HTML → PDF, no LaTeX needed)
- **Apply**: Playwright browser automation
- **Frontend**: Next.js (Phase 6)

## Setup

See [SETUP_MAC.md](SETUP_MAC.md) for the full setup guide on Mac M1.

```bash
# Quick start (after Ollama is running)
cd backend
cp .env.example .env
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000/docs
```

## Build Phases

- [x] **Phase 1** — Backend scaffold (agents, DB, WebSocket, API) ← *current*
- [ ] **Phase 2** — Search + Rank pipeline
- [ ] **Phase 3** — DocGen (one-pager + cover letter PDF)
- [ ] **Phase 4** — Apply Agent (Playwright)
- [ ] **Phase 5** — Research Agent
- [ ] **Phase 6** — Next.js frontend

## LLM Provider

Configured for **Ollama** (local, zero API cost) by default.
Switch providers with one `.env` change — no code changes needed.

```env
# Ollama (default — free, local)
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL_SMART=qwen2.5:7b
LLM_MODEL_FAST=llama3.2:3b
```
