# 🔨 JobForge

A personal job-search app. Find jobs, compare them with your profile, prepare
application documents, and track your applications.

JobForge runs on your Mac using Docker and Ollama by default.

## Setup

Follow [SETUP_MAC.md](SETUP_MAC.md) to install Docker and Ollama and download the models.

Start the app from the project folder:

```bash
docker compose up -d --build
```

- App: http://localhost:3000
- API documentation: http://localhost:8000/docs
- Health check: http://localhost:8000/health

Use the same command after updating the project to rebuild and restart services.

## Daily Use

1. **My Profile:** enter your details or upload a PDF/DOCX resume. Review before saving.
2. **Search Config:** choose keywords, locations, portals, and a schedule.
3. **Run Pipeline:** search for jobs, rank them, and research the best matches.
4. **Jobs:** browse results and click a title or **View job details** to see actions.
5. **Research:** compare the description with your skills and experience.
6. **Generate documents:** create a tailored resume and cover letter.
7. **Applications:** save jobs, record applications, and track interviews and follow-ups.

## Finding Jobs

Supported sources: **LinkedIn, RemoteOK, We Work Remotely, HackerNews Hiring,
and JobLeads**. Results depend on what each portal makes publicly available.

- Search by keyword or company. Filter by portal, location, remote work, fit score, date, or salary.
- Sort results and browse pages of 20, 50, or 100 jobs.
- Use **Saved** to see jobs currently saved in the application tracker.
- Use **Add job manually** to paste a description or save a listing URL from another source.
- Manual URLs are references only. Paste the description for AI analysis; the URL is not fetched automatically.
- Salary amounts are compared within the selected currency and pay period. Unknown amounts are excluded.
- Posting-date filters exclude jobs whose posting date is unknown.

For JobLeads, enter country names such as `Germany, Singapore, India` in Locations.
For city-only searches, `JOBLEADS_COUNTRY` in `backend/.env` sets the fallback country
(default: `in`).

### Search Configurations

Save named configurations for different roles or markets. Each keeps its own
settings and schedule. Editing one does not replace the others.

- **Save & Run This Config** runs the selected configuration.
- Set the interval to `0` for manual runs only.
- Pause a configuration to disable its scheduled runs.
- The generic **Run Pipeline** button uses the most recently updated active configuration.

### Job Descriptions

The app keeps available descriptions without cutting them short. Ranking,
research, and document generation receive the full stored text.

Public listings are checked for fuller descriptions when needed. Failed fetches
keep the existing text and show a warning. Manual imports use your pasted text.
Very long descriptions still depend on the AI model's context limit.

### Visa Sponsorship

Job cards show what the available description says:

| Badge | Meaning |
|---|---|
| Sponsorship mentioned | The listing offers sponsorship. |
| Conditional sponsorship | Sponsorship has conditions or transfer limits. |
| No sponsorship | The listing refuses sponsorship. |
| Sponsorship unclear | The description gives no clear answer. |
| Not assessed | The description has not been checked yet. |

Open job details to read the original sentence behind the badge. Conflicting
statements are shown together. Rules handle clear wording; Research uses AI to
review unclear wording and checks its quotes against the description.

Remote work, relocation assistance, and past company sponsorship do not prove
that the current job offers sponsorship. Sponsorship filters and search
preferences are not available yet.

## Applications

Track applications in board or table view:

**Saved → Preparing → Applied → Screening → Interviewing → Offer → Accepted / Rejected / Withdrawn**

- Keep recruiter contacts, notes, application dates, deadlines, and follow-up reminders.
- Record interview rounds, preparation notes, and outcomes.
- View the status timeline. Invalid or outdated status changes are rejected.
- Regenerating documents does not change the application stage.
- **Mark applied** records your application; it does not submit it to an employer.
- **Delete application permanently** removes the local opportunity and its related data.

Reminders appear inside the app; there are no email or push notifications.

## Runs and Background Work

Long tasks run in Celery workers. Open **Runs** to see progress, results, portal
failures, and retry options. Closing the browser does not stop the work.
Your Mac and Docker must stay awake for processing to continue.

- Duplicate discovery runs are prevented.
- Completed work is saved even when a later stage fails.
- Temporary failures retry automatically within the attempt limit.
- The scheduler checks schedules and interrupted work every minute.
- **Retry run** starts a linked retry while keeping the original history.

Keep the backend, worker, Beat scheduler, PostgreSQL, and Redis running.
Changed worker code needs a worker restart.

## Cleanup

Automatic cleanup removes old untracked jobs. It preserves manual imports and
tracked applications, and uses the longest active search window.

**Hide this job** hides a result. **Clear** deletes untracked jobs, including manual
imports, while keeping tracked applications. A later search can rediscover a deleted listing.

## AI Configuration

Settings are in `backend/.env`. The default uses Ollama on your Mac:

```env
LLM_BASE_URL=http://host.docker.internal:11434/v1
LLM_API_KEY=ollama
LLM_MODEL_SMART=qwen2.5:7b
LLM_MODEL_FAST=llama3.2:3b
```

You can change these settings to use another OpenAI-compatible provider.
Job portals are contacted during discovery. Profile and job text are also sent
to your AI provider if you choose a cloud service.

## Technology

| Part | Tools |
|---|---|
| Frontend | Next.js, TypeScript, Tailwind CSS |
| Backend | FastAPI, SQLAlchemy |
| AI | Ollama by default |
| Database | PostgreSQL in Docker; SQLite for optional local development |
| Background tasks | Celery and Redis |
| Documents | Jinja2 and WeasyPrint |

The app is built for one person's use and has no login system.

## Tests

```bash
docker compose exec backend python -m unittest discover -s tests -v
```

Tests use temporary SQLite databases by default. Optional integration tests use
`JOBFORGE_TEST_DATABASE_URL` and `JOBFORGE_TEST_REDIS_URL`. Use disposable test
services for these, especially Redis; never use the application's live broker.
