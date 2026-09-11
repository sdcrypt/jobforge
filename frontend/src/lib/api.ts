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
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

// ── Types ────────────────────────────────────────────────────────────────────

export interface Job {
  id: string
  title: string
  company: string
  location: string | null
  url: string
  portal: string
  remote: boolean
  salary_range: string | null
  job_type: string | null
  fit_score: number | null
  tech_score: number | null
  exp_score: number | null
  location_score: number | null
  growth_score: number | null
  strengths: string[] | null
  gaps: string[] | null
  status: string
  found_at: string
}

export interface UserProfile {
  id: string
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
  id: string
  keywords: string[]
  locations: string[]
  portals: string[]
  remote_only: boolean
  posted_within_days: number
  active: boolean
  run_every_hours: number
  last_run_at: string | null
  last_run_found: number
}

export interface Application {
  id: string
  job_id: string
  status: string
  one_pager_path: string | null
  cover_letter_path: string | null
  applied_at: string | null
}

export interface AgentEventData {
  agent: string
  status: 'started' | 'thinking' | 'done' | 'error'
  message: string
  extra: Record<string, unknown>
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
      req<{ id: string; message: string }>('/api/profile', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
  },

  // ── Search Config ───────────────────────────────────────────────────────
  searchConfig: {
    get: () => req<SearchConfig>('/api/search-config'),
    save: (data: Partial<SearchConfig>) =>
      req<{ id: string; message: string }>('/api/search-config', {
        method: 'POST',
        body: JSON.stringify(data),
      }),
  },

  // ── Pipeline ────────────────────────────────────────────────────────────
  pipeline: {
    run: () => req<{ message: string }>('/api/pipeline/run', { method: 'POST' }),
  },

  // ── Jobs ────────────────────────────────────────────────────────────────
  jobs: {
    list: (params?: { status?: string; min_score?: number; limit?: number }) => {
      const qs = new URLSearchParams()
      if (params?.status)    qs.set('status', params.status)
      if (params?.min_score) qs.set('min_score', String(params.min_score))
      if (params?.limit)     qs.set('limit', String(params.limit))
      return req<{ jobs: Job[]; count: number }>(`/api/jobs?${qs}`)
    },
    get: (id: string) => req<Job>(`/api/jobs/${id}`),
  },

  // ── Applications ─────────────────────────────────────────────────────────
  applications: {
    list: () => req<{ applications: Application[]; count: number }>('/api/applications'),
    generateDocs: (jobId: string) =>
      req<{ message: string; application_id: string }>(`/api/applications/${jobId}/generate-docs`, {
        method: 'POST',
      }),
    updateStatus: (jobId: string, status: string) =>
      req<{ message: string }>(`/api/applications/${jobId}/status?status=${status}`, {
        method: 'PATCH',
      }),
    previewOnePager: (jobId: string) =>
      `${BASE}/api/applications/${jobId}/preview/one-pager`,
    downloadOnePager: (jobId: string) =>
      `${BASE}/api/applications/${jobId}/download/one-pager`,
    downloadCoverLetter: (jobId: string) =>
      `${BASE}/api/applications/${jobId}/download/cover-letter`,
  },
}
