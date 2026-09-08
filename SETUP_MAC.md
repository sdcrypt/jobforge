# JobForge — Mac Setup Guide (M1)

## Prerequisites

### 1. Install Homebrew (if not installed)
```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

### 2. Install Python 3.11+
```bash
brew install python@3.11
python3 --version   # should be 3.11+
```

### 3. Install Node.js 20+ (for frontend, Phase 6)
```bash
brew install node@20
node --version
```

---

## Install Ollama (Local LLM — no API key needed)

### 1. Download and install
```bash
brew install ollama
```

Or download from: https://ollama.com/download/mac

### 2. Start Ollama (runs in background)
```bash
ollama serve
```

### 3. Pull the models (one-time, ~8GB total)
Open a new terminal tab and run:
```bash
# Smart model — Coordinator, DocGen, Rank agents (~4.7GB)
ollama pull qwen2.5:7b

# Fast model — Search agent, parallel calls (~2GB)
ollama pull llama3.2:3b
```

### 4. Verify Ollama is working
```bash
ollama list
# Should show both models

curl http://localhost:11434/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"llama3.2:3b","messages":[{"role":"user","content":"Say OK"}]}'
```

---

## Backend Setup

### 1. Clone the repo
```bash
cd ~/Documents/Python
git clone <your-github-repo-url> jobforge
cd jobforge/backend
```

### 2. Create virtual environment
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Install Playwright browsers (for Apply Agent)
```bash
playwright install chromium
```

### 5. Set up environment
```bash
cp .env.example .env
# .env is pre-configured for Ollama — no changes needed to start
```

### 6. Run the backend
```bash
uvicorn main:app --reload --port 8000
```

You should see:
```
INFO: JobForge starting up
INFO: DB tables created
INFO: Uvicorn running on http://127.0.0.1:8000
```

---

## Verify Everything Works

### Check the API
```bash
open http://localhost:8000/docs
```

### Check LLM connection
```bash
curl http://localhost:8000/health/llm
# Should return: {"status": "connected", "model": "llama3.2:3b", "response": "OK"}
```

### Test WebSocket (in browser console)
```javascript
const ws = new WebSocket("ws://localhost:8000/ws");
ws.onmessage = (e) => console.log(JSON.parse(e.data));
ws.send("ping");  // Should receive "pong"
```

---

## Quick First Run

Once the server is running, try this in another terminal:

```bash
# 1. Create your profile
curl -X POST http://localhost:8000/api/profile \
  -H "Content-Type: application/json" \
  -d '{
    "full_name": "Sourabh Dixit",
    "email": "sourabh.a.dixit@accenture.com",
    "skills": [{"name": "Python", "level": "expert"}],
    "target_roles": ["Backend Engineer"],
    "remote_preference": "remote"
  }'

# 2. Trigger a job search
curl -X POST "http://localhost:8000/api/jobs/search?query=Python+Developer&location=remote"

# 3. Check for jobs (wait ~30 seconds for search to complete)
curl http://localhost:8000/api/jobs

# 4. Rank the jobs
curl -X POST http://localhost:8000/api/jobs/rank
```

---

## Switching LLM Provider (Optional)

To switch from Ollama to OpenAI (when you have an API key), just edit `.env`:

```env
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-your-key-here
LLM_MODEL_SMART=gpt-4o
LLM_MODEL_FAST=gpt-4o-mini
```

No code changes needed.
