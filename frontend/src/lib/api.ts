/**
 * JobForge — typed API client
 * All calls go to the FastAPI backend.
 */

const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
export const WS_URL = process.env.NEXT_PUBLIC_WS_URL || 'ws://localhost:8000'

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...init?.headers },
    ...init,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(typeof err.detail === 'string' ? err.detail : typeof err.detail?.message === 'string' ? err.detail.message : JSON.stringify(err.detail || `HTTP ${res.status}`))
  }
  return res.json()
}

// ── Types ────────────────────────────────────────────────────────────────────

export type SponsorshipStatus = 'mentioned' | 'conditional' | 'not_available' | 'not_specified'
export type SponsorshipFilter = SponsorshipStatus | 'not_assessed'

export interface Job {
  id: number
  title: string
  company: string
  description: string | null
  description_source: string | null
  description_checked_at: string | null
  description_error: string | null
  sponsorship_status: SponsorshipStatus | null
  sponsorship_checked_at: string | null
  sponsorship_needs_review: boolean
  sponsorship_evidence: { quote: string; status: SponsorshipStatus; method: string; reason?: string; triggers?: string[] }[] | null
  sponsorship_notes: string | null
  location: string | null
  url: string
  portal: string
  remote: boolean
  salary_range: string | null
  salary_min: number | null
  salary_max: number | null
  salary_currency: string | null
  salary_period: 'year' | 'month' | 'hour' | null
  job_type: string | null
  fit_score: number | null
  tech_score: number | null
  exp_score: number | null
  location_score: number | null
  growth_score: number | null
  strengths: string[] | null
  gaps: string[] | null
  // Research Agent fields (populated after clicking Research)
  fit_summary: string | null
  talking_points: string[] | null
  researched_at: string | null
  status: string
  found_at: string
  posted_at: string | null
}

export interface JobsQuery {
  sponsorship_status?: SponsorshipFilter
  status?: string
  application_status?: string
  keyword?: string
  company?: string
  portal?: string
  location?: string
  remote?: boolean
  min_score?: number
  salary_min?: number
  salary_max?: number
  salary_currency?: string
  salary_period?: string
  has_salary?: boolean
  posted_within_days?: number
  sort?: string
  limit?: number
  offset?: number
}

export interface JobsResult {
  jobs: Job[]
  count: number
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface ManualJobInput {
  title: string
  company: string
  url?: string
  description?: string
  location?: string
  remote?: boolean
  salary_min?: number
  salary_max?: number
  salary_currency?: string
  salary_period?: string
  posted_at?: string
}

export interface UserProfile {
  id: number
  full_name: string
  email: string
  phone: string | null
  location: string | null
  linkedin_url: string | null
  headline: string | null
  summary: string | null
  skills: { name: string; level: string }[] | null
  experience: {
    company: string; role: string; start: string; end: string; highlights: string[]
  }[] | null
  education: { institution: string; degree: string; year: number }[] | null
  target_roles: string[] | null
  remote_preference: string | null
  salary_min: number | null
  salary_max: number | null
}

export interface SearchConfig {
  id: number
  name: string
  keywords: string[]
  locations: string[]
  portals: string[]
  remote_only: boolean
  posted_within_days: number
  active: boolean
  run_every_hours: number
  /** Results fetched per keyword+location+portal combo (default 15, max 100) */
  max_results_per_search: number
  /** LinkedIn result pages per search (each page ≈ 25 jobs, default 1, max 4) */
  linkedin_pages: number
  /** Auto-research top N jobs by fit score after each pipeline run (0 = disabled) */
  auto_research_top_n: number
  last_run_at: string | null
  last_run_found: number
}

export type ApplicationStatus = 'saved' | 'preparing' | 'applied' | 'screening' | 'interviewing' | 'offer' | 'accepted' | 'rejected' | 'withdrawn'

export interface InterviewRound {
  id: number | string
  round: number
  type: string
  date: string | null
  interviewer: string | null
  preparation_notes: string | null
  notes: string | null
  outcome: string | null
}

export interface ApplicationDetails {
  applied_at: string | null
  recruiter_name: string | null
  recruiter_email: string | null
  recruiter_phone: string | null
  notes: string | null
  preparation_notes: string | null
  outcome: string | null
  deadline_at: string | null
  follow_up_at: string | null
  follow_up_completed_at: string | null
  interview_rounds: InterviewRound[]
}

export interface Application extends ApplicationDetails {
  id: number
  job_id: number
  status: ApplicationStatus
  document_status: 'not_started' | 'generating' | 'ready' | 'failed'
  document_error: string | null
  one_pager_path: string | null
  cover_letter_path: string | null
  created_at: string
  updated_at: string
  allowed_transitions: ApplicationStatus[]
  status_history: { from_status: ApplicationStatus | null; to_status: ApplicationStatus; changed_at: string; note: string | null }[] | null
  job: Pick<Job, 'id' | 'title' | 'company' | 'url' | 'location' | 'portal' | 'fit_score'>
}

export interface TopJob {
  id: number
  title: string
  company: string
  fit_score: number
  portal: string
  location: string | null
  remote: boolean
  researched_at: string | null
  url: string
}

export interface Stats {
  total_jobs: number
  researched: number
  high_fit: number
  docs_generated: number
  avg_fit_score: number | null
  by_portal: Record<string, number>
  score_buckets: Record<string, number>
  top_jobs: TopJob[]
  last_pipeline: { run_at: string; found: number } | null
}

export interface AgentEventData {
  id: number
  run_id: number | null
  created_at: string
  agent: string
  status: 'started' | 'thinking' | 'done' | 'error'
  message: string
  extra: Record<string, unknown>
}

export interface TaskRun {
  label: string
  children?: TaskRun[]
  id: number
  kind: string
  status: 'queued' | 'running' | 'retrying' | 'succeeded' | 'partial' | 'failed' | 'cancelled'
  job_id: number | null
  config_id: number | null
  parent_id: number | null
  retry_of: number | null
  trigger: string
  stage: string
  stages: { name: string; attempt: number; status: string; message: string; completed: number; total: number; error?: string }[]
  result: Record<string, unknown> | null
  error: string | null
  error_type: string | null
  dispatch_error: string | null
  traceback?: string | null
  attempts: number
  max_attempts: number
  next_retry_at: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
}

export interface QueuedRun {
  run_id: number
  run: TaskRun
  duplicate: boolean
  message: string
}

async function waitForRun(runId: number | string): Promise<TaskRun> {
  for (let attempt = 0; attempt < 300; attempt += 1) {
    const run = await req<TaskRun>(`/api/runs/${runId}`)
    if (run.status === 'succeeded' || run.status === 'partial') return run
    if (run.status === 'failed') throw new Error(run.error || 'Task failed. Open Runs for details and retry.')
    if (run.status === 'cancelled') throw new Error('Run stopped at your request.')
    await new Promise(resolve => setTimeout(resolve, 3000))
  }
  throw new Error('Work is still queued or running. Open Runs to follow progress; it will continue after you leave this page.')
}

// ── Health ───────────────────────────────────────────────────────────────────

export const api = {
  health: {
    get: () => req<{ status: string; llm_model_smart: string }>('/health'),
    llm: () => req<{ status: string; model: string }>('/health/llm'),
  },

  // ── Profile ────────────────────────────────────────────────────────────
  profile: {
    get: () => req<UserProfile>('/api/profile'),
    save: (data: Partial<UserProfile>) =>
      req<{ id: number; message: string }>('/api/profile', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
    /** Upload a PDF or DOCX resume — returns parsed fields for review, does NOT auto-save. */
    parseResume: async (file: File): Promise<{ parsed: Partial<UserProfile>; message: string }> => {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`${BASE}/api/profile/parse-resume`, {
        method: 'POST',
        body: form,
        // No Content-Type — let browser set multipart/form-data + boundary
      })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }))
        throw new Error(err.detail || `HTTP ${res.status}`)
      }
      const queued = await res.json() as QueuedRun
      const completed = await waitForRun(queued.run_id)
      return { parsed: completed.result?.parsed as Partial<UserProfile>, message: 'Resume parsed. Review the fields and save your profile.' }
    },
  },

  // ── Search Config ───────────────────────────────────────────────────────
  searchConfig: {
    get: () => req<SearchConfig>('/api/search-config'),
    list: () => req<{ configs: SearchConfig[] }>('/api/search-config/all'),
    save: (data: Partial<SearchConfig>) =>
      req<{ id: number; message: string }>(data.id ? `/api/search-config/${data.id}` : '/api/search-config', {
        method: data.id ? 'PUT' : 'POST',
        body: JSON.stringify(data),
      }),
  },

  // ── Pipeline ────────────────────────────────────────────────────────────
  pipeline: {
    run: (configId?: number) => req<QueuedRun>(`/api/pipeline/run${configId ? `?config_id=${encodeURIComponent(configId)}` : ''}`, { method: 'POST' }),
  },

  runs: {
    list: (params?: { kind?: string; status?: string; limit?: number; offset?: number }) => {
      const query = new URLSearchParams()
      Object.entries(params || {}).forEach(([key, value]) => { if (value !== undefined) query.set(key, String(value)) })
      return req<{ runs: TaskRun[]; count: number }>(`/api/runs?${query}`)
    },
    get: (runId: number | string) => req<TaskRun>(`/api/runs/${runId}`),
    stop: (runId: number | string) => req<TaskRun>(`/api/runs/${runId}/stop`, { method: 'POST' }),
    events: (runId?: number) => req<{ events: AgentEventData[] }>(`/api/runs/events${runId ? `?run_id=${runId}&limit=200` : ''}`),
    retry: (runId: number | string, maxAttempts = 3) => req<QueuedRun>(`/api/runs/${runId}/retry`, { method: 'POST', body: JSON.stringify({ max_attempts: maxAttempts }) }),
    wait: waitForRun,
  },

  // ── Jobs ────────────────────────────────────────────────────────────────
  jobs: {
    list: (params?: JobsQuery) => {
      const qs = new URLSearchParams()
      Object.entries(params || {}).forEach(([key, value]) => { if (value !== undefined && value !== '') qs.set(key, String(value)) })
      return req<JobsResult>(`/api/jobs?${qs}`)
    },
    import: (data: ManualJobInput) => req<Job>('/api/jobs/import', { method: 'POST', body: JSON.stringify(data) }),
    get: (id: number) => req<Job>(`/api/jobs/${id}`),
    dismiss: (id: number) =>
      req<{ message: string }>(`/api/jobs/${id}/dismiss`, { method: 'PATCH' }),
    /** Run Research Agent — AI fit analysis against profile. Returns updated scores. */
    research: async (id: number) => {
      const queued = await req<QueuedRun>(`/api/jobs/${id}/research`, { method: 'POST' })
      await waitForRun(queued.run_id)
      return req<Job>(`/api/jobs/${id}`)
    },
    clear: (portal?: string) => {
      const qs = portal ? `?portal=${portal}` : ''
      return req<{ message: string; deleted: number }>(`/api/jobs/clear${qs}`, { method: 'DELETE' })
    },
  },

  // ── Stats ───────────────────────────────────────────────────────────────
  stats: {
    get: () => req<Stats>('/api/jobs/stats'),
  },

  // ── Applications ─────────────────────────────────────────────────────────
  applications: {
    list: () => req<{ applications: Application[]; count: number }>('/api/applications'),
    get: (jobId: number | string) => req<Application>(`/api/applications/${jobId}`),
    save: (jobId: number | string) => req<Application>(`/api/applications/${jobId}`, { method: 'PUT' }),
    remove: (jobId: number | string) => req<{ message: string; cleanup_warning: string | null }>(`/api/applications/${jobId}`, { method: 'DELETE' }),
    update: (jobId: number | string, data: Partial<ApplicationDetails>) =>
      req<Application>(`/api/applications/${jobId}`, { method: 'PATCH', body: JSON.stringify(data) }),
    generateDocs: (jobId: number | string) =>
      req<QueuedRun & { application_id: number }>(`/api/applications/${jobId}/generate-docs`, {
        method: 'POST',
      }),
    updateStatus: (jobId: number | string, status: ApplicationStatus, expectedStatus: ApplicationStatus, note?: string) =>
      req<Application>(`/api/applications/${jobId}/status`, {
        method: 'PATCH',
        body: JSON.stringify({ status, expected_status: expectedStatus, note: note || null }),
      }),
    previewOnePager: (jobId: number | string) =>
      `${BASE}/api/applications/${jobId}/preview/one-pager`,
    downloadOnePager: (jobId: number | string) =>
      `${BASE}/api/applications/${jobId}/download/one-pager`,
    downloadCoverLetter: (jobId: number | string) =>
      `${BASE}/api/applications/${jobId}/download/cover-letter`,
  },
}
