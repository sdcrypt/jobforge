# 🔨 JobForge

> **Forge your next career move.**  
> Local-first AI-powered job search, fit analysis, and document generation — runs on your Mac with Ollama by default.

---

## What it does

JobForge automates the repetitive parts of job hunting:

1. **Searches** multiple job portals simultaneously for roles matching your keywords and locations
2. **Scores** every job against your profile (fit score 0–100) with sub-scores for tech, experience, location, and growth
3. **Deep-analyses** top jobs with AI — strengths, gaps, and talking points tailored to each role
4. **Generates** a professional one-pager CV + cover letter as PDF, tailored per job
5. **Tracks** your profile, jobs, and generated documents in your local database

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
    ├── redis     :6379        ← Celery broker/result backend
    ├── worker                  ← Celery worker for pipeline jobs
    └── beat                    ← Celery beat for scheduled runs
```

Containers talk to Ollama at `host.docker.internal:11434`. With the default Ollama config, LLM calls stay on your Mac. External job portals are still queried during scraping, and profile/job text may leave your machine if you switch to a cloud LLM provider.

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
| **JobLeads** | Public HTML search pages | Configurable country market (India by default) |
| 🔗 **LinkedIn** | HTML scrape (guest API) | Global, all industries — up to 4 pages × 25 results |
| 🌍 **RemoteOK** | Free JSON API | Remote tech jobs, salary data included |
| 🏠 **We Work Remotely** | RSS feed | Senior remote roles, 3 category feeds |
| 🟠 **HackerNews Hiring** | Algolia API | Monthly "Who is Hiring" thread — startups, founding roles |

> Portals with reCAPTCHA v3 (Naukri, Indeed, Glassdoor) block automated scraping and are not included. Google Careers and Amazon Jobs are on the roadmap.

Select **JobLeads** in Search Config to include its dedicated agent in the pipeline.
Enter country names in the UI's Locations field, for example `Germany, Singapore,
India`, to search all three markets in the same pipeline run. Country names and
their two-letter codes select the corresponding JobLeads market automatically.
`JOBLEADS_COUNTRY` in `backend/.env` is only the fallback for city-only locations
such as `Berlin` or `Remote` (default: `in`). Set it to `de` for city-only searches
within Germany. Country entries search the whole market without a city filter.
Searches collect up to four public
pages, respect the result limit and remote filter, and use the existing ranking
and research agents. No additional model or JobLeads credentials are needed.
Availability depends on JobLeads returning public HTML listings; login-only or
blocked pages cannot be searched. Relative posting dates are parsed when exact;
labels such as "14 days+" are left without an exact timestamp.

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
- Dismiss jobs to hide them; clear untracked jobs while preserving applications
- Research panel expands inline on each job card

### Application Tracker
- **Applications** page with board and table views, company/role/contact search, stage filters, and due follow-ups
- **Save job** and **Mark applied** actions on job cards; recording an application does not submit it to the employer
- Application lifecycle: Saved → Preparing → Applied → Screening → Interviewing → Offer → Accepted / Rejected / Withdrawn
- Validated transitions allow skipping screening/interview stages when appropriate; terminal outcomes close the lifecycle
- Recruiter name, email and phone; application date, deadline, notes, preparation notes, and outcome
- Interview rounds with dates, interviewers, preparation, notes, and outcomes
- Follow-up reminders with completion controls and an in-app due list; no email or push notifications
- Timestamped status history with optional notes and protection against stale status updates
- Separate document status (`not_started`, `generating`, `ready`, `failed`); regenerating documents preserves submitted application stages
- Tracked jobs are preserved by stale-job cleanup and the Jobs page's Clear action
- Open an application and choose **Delete application permanently** to remove an expired, closed, or unwanted opportunity from both Applications and Jobs, including its notes, interviews, reminders, history, and generated PDF/HTML documents. Confirmation is required, and deletion waits for active document generation to finish. Shared documents used by another application are retained.
- Deletion removes the local records; a later search can rediscover the job if the portal still lists it. Use **Withdrawn** when you want to retain a record of a decision to stop pursuing a role.

Existing application records are upgraded automatically on backend startup. Legacy
document states become preparation/document states, and legacy job tracking states
move into application records. Existing document references are retained. Rebuild
the services with `docker compose up -d --build` after updating.

The tracker API uses job IDs: `PUT /api/applications/{job_id}` saves a job,
`PATCH /api/applications/{job_id}` edits details, and
`PATCH /api/applications/{job_id}/status` accepts a JSON body containing `status`,
`expected_status`, and an optional `note`. Responses include the job summary,
status history, document status, and allowed next stages. Dates are stored in UTC
and displayed in the browser's local timezone.

`DELETE /api/applications/{job_id}` permanently deletes the application and its job.
Any document-cleanup failure is reported separately after the database deletion.

Run backend tests with `docker compose exec backend python -m unittest discover -s tests -v`.

### Discovery & Shortlisting
- Sponsorship is assessed independently of fit and application status. Stored categories are `mentioned` (Sponsorship mentioned), `conditional` (Conditional / limited), `not_available` (No sponsorship), and `not_specified` (Not specified). New imports and discovered descriptions use conservative English-language rules; existing descriptions receive a rules-only assessment at startup. Research reviews ambiguous wording with AI. AI quotes must match complete original sentences, including negation and restrictions; unsupported interpretations remain Not specified with a review flag. Explicit refusals and conflicting rule evidence cannot be overridden by AI. Relocation, remote work, work authorization, and company history alone do not establish an offer for the vacancy.
- Job APIs expose `sponsorship_status`, `sponsorship_evidence` (original quotes, category, and method), `sponsorship_needs_review`, `sponsorship_method`, `sponsorship_notes`, and `sponsorship_checked_at`. Research run results also include a `sponsorship` assessment. Assessments are tied to a hash of the stored description and reset when it changes; a checked timestamp records analysis time, not an employer guarantee or independent confirmation. Missing descriptions remain Not specified. AI failures preserve the conservative assessment and flag review. Job cards show a sponsorship badge; jobs without an assessment timestamp show **Not assessed**, while assessed descriptions with no clear decision show **Not specified**. Badge tooltips explain the category and flag review when needed. Filters and search preferences are a separate UI step.
- Portal descriptions are stored without character truncation. Ranking, research, and document generation receive the entire stored description. Before analysis, public listing text is checked once and cached, preferring structured JobPosting data or a description section over page navigation. Existing snippets are eligible for fetching regardless of length; shorter responses never replace longer stored text. Failed fetches retain available text, show a warning in job details, and can retry after an hour. Manual-source URLs are never fetched; paste the full requirements when importing.
- When a longer description replaces older text, previous fit/research results are cleared for fresh analysis; application lifecycle and existing document files are preserved. Re-run Research or regenerate documents to update earlier results. Previously discarded text can only be recovered if the source still supplies it. Full text is sent to the configured AI model without the former 500/1,500/3,000-character caps; the provider's context window still applies, so choose an adequately sized context/model for unusually long listings. No automatic chunking or model-context reconfiguration is performed.
- **Jobs** filters and sorts in the database, with total matching counts and 20/50/100-row pages. Search title/company/description, filter company, portal, location, remote setting, minimum fit, posted date, and salary information. **Saved** shows jobs whose application lifecycle is currently Saved; it does not change their processing status.
- Salary amount filters use overlapping ranges, an explicit three-letter currency, and a pay period (year/month/hour). No exchange-rate or pay-period conversion is performed. Numeric filtering/sorting excludes unknown amounts; **Has salary information** also includes free-text salary labels that cannot be compared numerically. Structured amounts are recorded for new RemoteOK results and manual imports; older free-text-only salaries remain unknown until structured data is available.
- **Add job manually** accepts a listing URL or pasted description, plus title/company, optional location, remote flag, posting date, and salary amounts. URLs are references only: import and research never automatically fetch manual-source URLs. Paste requirements for meaningful AI evaluation. Duplicate URLs return a conflict without overwriting existing jobs; pasted-only jobs have an internal reference and no external View link. Importing creates neither an application nor an Applied status. Use **Research**, **Save job**, or **Mark applied** afterwards.
- **Search Config** supports multiple named configurations (for example, “Germany Backend” and “Singapore Lead”). Create a new configuration, edit an existing one in place, pause its schedule, or **Save & Run This Config** explicitly. Other configurations are not replaced or deactivated. Jobs/Dashboard's generic Run Pipeline action uses the most recently updated active configuration. Runs show the configuration name captured at queue time.
- Each active configuration has its own schedule. Due configurations run oldest-due first under the shared discovery lock; missed slots do not produce concurrent searches. Setting an interval to `0` disables scheduling for that configuration. Saving edits does not reset its last-run history.
- Discovery excludes known postings older than the configured window across all connectors; LinkedIn also receives that window in its request instead of a hardcoded seven days. Undated postings remain eligible during discovery and are explicitly counted as undated. The Jobs **Posted within** filter is strict and excludes undated jobs; discovery date comparisons normalize timezone-aware timestamps to UTC.
- **Runs → Portal search reports** distinguishes an empty successful search from a failed portal, with keyword/location, error messages, excluded old results, and undated counts. All-portal failure fails/retries the run; successful portals retain their results when others fail. Counts are before URL deduplication. Connectors may still return limited or incomplete public results; these reports do not guarantee portal coverage.
- Automatic stale cleanup preserves manual imports and tracked applications. With multiple active configurations, it uses the longest configured posting window so a narrow search does not delete another market's recent results. **Clear** still deletes untracked manual imports when explicitly requested.

To try this in the UI after rebuilding with `docker compose up -d --build`:
1. Open **Jobs**, combine keyword/company/portal/location filters, and use Next/Previous or change the page size. Counts and ordering apply across all matches, not just the loaded page.
2. Choose **Add job manually**, paste a description, enter title/company and optional salary, then Add job. It appears under Manually added; Research evaluates the pasted requirements. Adding the same listing URL again displays a duplicate warning.
3. Click the job title or **View job details** to open its details. Save job, Mark applied, Original listing, Research/Analysis, and document actions are available there. Save the job and open the **Saved** tab. Adjust salary currency/period and posted-date filters; unknown values are excluded when those filters require known data.
4. In **Search Config**, create two named configurations, switch between them, edit one, and confirm both remain available. Use **Save & Run This Config**, then open **Runs** to check its name, stages, and portal reports. Pausing scheduling does not prevent an explicit manual run.

### Reliable Runs
- Pipeline search, standalone search/ranking/research, document generation, resume parsing, and application assistance execute in Celery workers. Requests return HTTP 202 with a persistent `run_id`.
- **Runs** shows queued, running, retrying, succeeded, partially completed, and failed work, including stage progress, saved results, attempts, failure details, and related research tasks. Closing the browser does not interrupt work.
- Pipeline stages commit useful work independently: cleanup → search → store → rank → research. A later failure does not discard already stored jobs or completed analyses. Ranking drains all pending batches rather than stopping at 50 jobs.
- Active-work keys and atomic worker claims prevent duplicate runs and duplicate message execution. Pipeline, standalone search, and standalone ranking share a discovery lock; per-job work has its own locks.
- Failed transient work retries up to three attempts by default, with increasing delays. Beat checks due retries every minute. **Retry run** creates a new linked run and lets you select 1–5 attempts. Validation failures stop immediately; browser application assistance never retries automatically.
- Workers heartbeat every 15 seconds. After three minutes without a heartbeat, the scheduler records an interruption and retries within the attempt budget. Obsolete workers cannot commit application/database updates after losing ownership.
- The configured `run_every_hours` is honored: `0` means manual only. Scheduled runs become due relative to the latest queued pipeline run for that configuration, or the configuration's creation time before its first run. Beat checks every minute and never overlaps active discovery work.
- Runs are committed before queue publication. If Redis is unavailable, the run remains queued with a dispatch error; the scheduler retries publication when the broker returns. Redis uses append-only persistence in its own Docker volume.
- Worker events are saved in the database and published through Redis to the API's WebSocket listener. The activity feed restores history on reconnect and also polls persisted events, so a missed live event does not erase progress.
- Resume-import results can be reopened from Runs using **Review imported resume in Profile**. Parsing never saves the profile automatically; the uploaded bytes are cleared from the run payload after successful parsing.

Rebuild all services after updating: `docker compose up -d --build`. The API adds
the run-history tables and event index at startup. Keep **backend, worker, beat,
PostgreSQL, and Redis** running: Beat handles scheduling, retry dispatch, and
interruption recovery. Worker/Beat restarts are required to load changed task code.

Run APIs: `GET /api/runs`, `GET /api/runs/{run_id}`,
`GET /api/runs/events?run_id=...`, and `POST /api/runs/{run_id}/retry` with optional
JSON `{ "max_attempts": 3 }`. Search inputs are snapshotted at queue time; retries
reuse those inputs. Jobs and analyses already completed are retained and deduplicated.

Tests use temporary SQLite databases by default. To exercise PostgreSQL locking,
set `JOBFORGE_TEST_DATABASE_URL` to a disposable PostgreSQL database; the run tests
create and remove their own schemas. Set `JOBFORGE_TEST_REDIS_URL` to an isolated
Redis server to also run the real Celery worker/event-bridge integration test.
Never use a production Redis broker for that integration test.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15, TypeScript, Tailwind CSS, SWR |
| Backend | FastAPI (async), SQLAlchemy 2.0, Pydantic v2 |
| LLM | Ollama (local) — swap to OpenAI/Groq via `.env` |
| Database | PostgreSQL via Docker Compose; SQLite only for optional direct backend dev |
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
docker compose up -d --build
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
7. **Applications** → record the application, manage contacts and follow-ups, track interviews and outcomes

---

## Design Decisions

- **Local-first** — Ollama on host Mac, profile/jobs/docs in local Docker volumes. Scraping still contacts external job sites, and cloud LLM providers can be used by changing `.env`.
- **Single user** — designed for personal use. No auth, no multi-tenancy.
- **No system installs** — all Python dependencies run inside Docker. Only Ollama is installed on the host (for Metal GPU access).
- **Provider-agnostic LLM** — same `openai` SDK throughout. Swap providers by changing `.env`.
- **No Playwright for scraping** — reCAPTCHA v3 blocks headless browsers on most job portals anyway. httpx + BeautifulSoup is faster and more reliable for the portals that work.
