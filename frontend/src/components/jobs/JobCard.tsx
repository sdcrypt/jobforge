'use client'

import { useState } from 'react'
import { Job, api } from '@/lib/api'
import clsx from 'clsx'

interface Props {
  job: Job
  onRefresh?: () => void
}

function scorePercent(value: number | null) {
  if (value == null) return null
  return Math.round(Math.max(0, Math.min(100, value)))
}

function ScoreBar({ label, value }: { label: string; value: number | null }) {
  const pct = scorePercent(value)
  const color =
    pct == null   ? 'bg-slate-200' :
    pct >= 70     ? 'bg-green-500' :
    pct >= 45     ? 'bg-yellow-500' :
                    'bg-red-400'
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-500 mb-0.5">
        <span>{label}</span>
        <span>{pct != null ? `${pct}%` : '—'}</span>
      </div>
      <div className="score-bar">
        <div className={clsx('score-fill', color)} style={{ width: `${pct ?? 0}%` }} />
      </div>
    </div>
  )
}

/** Colour-coded score badge shown in the top-right of the card */
function FitBadge({ pct }: { pct: number }) {
  const color =
    pct >= 70 ? 'text-green-600' :
    pct >= 45 ? 'text-yellow-600' :
                'text-red-500'
  return (
    <div className={clsx('text-xl font-bold tabular-nums shrink-0', color)}>
      {pct}%
    </div>
  )
}

// ── Research panel ─────────────────────────────────────────────────────────────

interface ResearchPanelProps {
  job: Job
  onClose: () => void
}

function ResearchPanel({ job, onClose }: ResearchPanelProps) {
  return (
    <div className="border-t border-slate-100 pt-3 mt-1 space-y-3">
      {/* Fit summary */}
      {job.fit_summary && (
        <p className="text-xs text-slate-600 leading-relaxed">
          {job.fit_summary}
        </p>
      )}

      {/* Strengths */}
      {job.strengths && job.strengths.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-green-700 mb-1">✓ Strengths</p>
          <ul className="space-y-0.5">
            {job.strengths.map((s, i) => (
              <li key={i} className="text-xs text-slate-600 flex gap-1.5">
                <span className="text-green-500 shrink-0">•</span>
                {s}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Gaps */}
      {job.gaps && job.gaps.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-red-600 mb-1">✗ Gaps</p>
          <ul className="space-y-0.5">
            {job.gaps.map((g, i) => (
              <li key={i} className="text-xs text-slate-600 flex gap-1.5">
                <span className="text-red-400 shrink-0">•</span>
                {g}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Talking points */}
      {job.talking_points && job.talking_points.length > 0 && (
        <div>
          <p className="text-xs font-semibold text-brand-700 mb-1">💬 Talking points</p>
          <ul className="space-y-0.5">
            {job.talking_points.map((t, i) => (
              <li key={i} className="text-xs text-slate-600 flex gap-1.5">
                <span className="text-brand-400 shrink-0">›</span>
                {t}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Score breakdown */}
      <div className="space-y-1.5 pt-1">
        <ScoreBar label="Tech"     value={job.tech_score} />
        <ScoreBar label="Exp"      value={job.exp_score} />
        <ScoreBar label="Location" value={job.location_score} />
        <ScoreBar label="Growth"   value={job.growth_score} />
      </div>

      {job.researched_at && (
        <p className="text-xs text-slate-400 text-right">
          Researched {new Date(job.researched_at).toLocaleDateString()}
        </p>
      )}

      <button
        onClick={onClose}
        className="text-xs text-slate-400 hover:text-slate-600 transition-colors"
      >
        ↑ Collapse
      </button>
    </div>
  )
}

// ── Main card ──────────────────────────────────────────────────────────────────

export default function JobCard({ job, onRefresh }: Props) {
  const [generating, setGenerating]   = useState(false)
  const [dismissing, setDismissing]   = useState(false)
  const [researching, setResearching] = useState(false)
  const [showPanel, setShowPanel]     = useState(false)
  const [error, setError]             = useState<string | null>(null)

  // Local copy of research data — updated optimistically after API call
  const [localJob, setLocalJob] = useState<Job>(job)

  // Keep localJob in sync when SWR refreshes the parent
  // (only update fields not overwritten by research)
  if (localJob.id !== job.id) setLocalJob(job)

  const fitPct = scorePercent(localJob.fit_score)
  const hasResearch = !!localJob.researched_at

  // ── Actions ──────────────────────────────────────────────────────────────

  async function generateDocs() {
    setGenerating(true)
    setError(null)
    try {
      await api.applications.generateDocs(localJob.id)
      onRefresh?.()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to generate docs')
    } finally {
      setGenerating(false)
    }
  }

  async function dismiss() {
    setDismissing(true)
    try {
      await api.jobs.dismiss(localJob.id)
      onRefresh?.()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to dismiss')
      setDismissing(false)
    }
  }

  async function runResearch() {
    setResearching(true)
    setError(null)
    try {
      const result = await api.jobs.research(localJob.id)
      // Merge research data into localJob so the panel shows immediately
      setLocalJob((prev) => ({
        ...prev,
        fit_score:      result.fit_score,
        fit_summary:    result.fit_summary,
        talking_points: result.talking_points,
        strengths:      result.strengths,
        gaps:           result.gaps,
        researched_at:  new Date().toISOString(),
      }))
      setShowPanel(true)
      onRefresh?.()   // background refresh so list re-sorts by score
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Research failed — is Ollama running?')
    } finally {
      setResearching(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow p-5 flex flex-col gap-4">

      {/* Top row: title + fit score badge */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-slate-900 truncate text-sm">{localJob.title}</h3>
          <p className="text-slate-500 text-xs mt-0.5">
            {localJob.company}
            {localJob.location ? ` · ${localJob.location}` : ''}
            {localJob.remote ? ' · Remote' : ''}
          </p>
        </div>
        {fitPct != null && <FitBadge pct={fitPct} />}
      </div>

      {/* Badges: portal / job type / salary */}
      <div className="flex flex-wrap gap-1.5">
        <span className="text-xs bg-slate-100 text-slate-600 rounded px-2 py-0.5 capitalize">
          {localJob.portal}
        </span>
        {localJob.job_type && (
          <span className="text-xs bg-slate-100 text-slate-600 rounded px-2 py-0.5">
            {localJob.job_type}
          </span>
        )}
        {localJob.salary_range && (
          <span className="text-xs bg-green-50 text-green-700 rounded px-2 py-0.5">
            {localJob.salary_range}
          </span>
        )}
        {hasResearch && (
          <span className="text-xs bg-brand-50 text-brand-700 rounded px-2 py-0.5">
            ✓ Researched
          </span>
        )}
      </div>

      {/* Quick strengths/gaps row — shown when NOT in full panel */}
      {!showPanel && (localJob.strengths?.length || localJob.gaps?.length) ? (
        <div className="flex gap-3 text-xs flex-wrap">
          {localJob.strengths?.slice(0, 2).map((s) => (
            <span key={s} className="text-green-600">✓ {s}</span>
          ))}
          {localJob.gaps?.slice(0, 1).map((g) => (
            <span key={g} className="text-red-500">✗ {g}</span>
          ))}
        </div>
      ) : null}

      {/* Inline score bars — shown only without full panel and when ranked */}
      {!showPanel && localJob.fit_score != null && !hasResearch && (
        <div className="space-y-1.5">
          <ScoreBar label="Tech"     value={localJob.tech_score} />
          <ScoreBar label="Exp"      value={localJob.exp_score} />
          <ScoreBar label="Location" value={localJob.location_score} />
          <ScoreBar label="Growth"   value={localJob.growth_score} />
        </div>
      )}

      {/* Research panel (expanded) */}
      {showPanel && (
        <ResearchPanel job={localJob} onClose={() => setShowPanel(false)} />
      )}

      {/* Error */}
      {error && <p className="text-xs text-red-500">{error}</p>}

      {/* Actions row */}
      <div className="flex gap-2 flex-wrap mt-auto items-center">
        <a
          href={localJob.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:border-slate-400 transition-colors"
        >
          View ↗
        </a>

        {/* Research / View Analysis button */}
        {hasResearch ? (
          <button
            onClick={() => setShowPanel((v) => !v)}
            className="text-xs px-3 py-1.5 rounded-lg border border-brand-200 text-brand-700 hover:bg-brand-50 transition-colors"
          >
            {showPanel ? '↑ Hide' : '📊 Analysis'}
          </button>
        ) : (
          <button
            onClick={runResearch}
            disabled={researching}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:border-brand-400 hover:text-brand-700 disabled:opacity-60 transition-colors"
          >
            {researching ? (
              <span className="flex items-center gap-1">
                <span className="animate-spin inline-block">⚙</span> Analysing…
              </span>
            ) : '🔍 Research'}
          </button>
        )}

        <button
          onClick={generateDocs}
          disabled={generating}
          className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-60 transition-colors"
        >
          {generating ? 'Generating…' : '📄 Docs'}
        </button>

        <a
          href={api.applications.downloadOnePager(localJob.id)}
          className="text-xs px-3 py-1.5 rounded-lg border border-brand-200 text-brand-600 hover:bg-brand-50 transition-colors"
        >
          ↓ PDF
        </a>

        <button
          onClick={dismiss}
          disabled={dismissing}
          title="Hide this job"
          className="text-xs px-2 py-1.5 rounded-lg border border-slate-200 text-slate-400 hover:border-red-300 hover:text-red-500 disabled:opacity-40 transition-colors ml-auto"
        >
          {dismissing ? '…' : '✕'}
        </button>
      </div>
    </div>
  )
}
