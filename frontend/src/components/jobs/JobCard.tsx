'use client'

import { useState } from 'react'
import { Job, api } from '@/lib/api'
import clsx from 'clsx'

interface Props {
  job: Job
  onRefresh?: () => void
}

function ScoreBar({ label, value }: { label: string; value: number | null }) {
  const pct = value != null ? Math.round(value * 100) : 0
  const color =
    pct >= 70 ? 'bg-green-500' :
    pct >= 45 ? 'bg-yellow-500' :
    'bg-red-400'

  return (
    <div>
      <div className="flex justify-between text-xs text-slate-500 mb-0.5">
        <span>{label}</span>
        <span>{value != null ? `${pct}%` : '—'}</span>
      </div>
      <div className="score-bar">
        <div className={clsx('score-fill', color)} style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

export default function JobCard({ job, onRefresh }: Props) {
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fitPct = job.fit_score != null ? Math.round(job.fit_score * 100) : null

  const fitColor =
    fitPct == null ? 'text-slate-400' :
    fitPct >= 70 ? 'text-green-600' :
    fitPct >= 45 ? 'text-yellow-600' :
    'text-red-500'

  async function generateDocs() {
    setGenerating(true)
    setError(null)
    try {
      await api.applications.generateDocs(job.id)
      onRefresh?.()
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Failed to generate docs')
    } finally {
      setGenerating(false)
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm hover:shadow-md transition-shadow p-5 flex flex-col gap-4">
      {/* Top row */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-slate-900 truncate text-sm">{job.title}</h3>
          <p className="text-slate-500 text-xs mt-0.5">
            {job.company}
            {job.location ? ` · ${job.location}` : ''}
            {job.remote ? ' · Remote' : ''}
          </p>
        </div>
        {fitPct != null && (
          <div className={clsx('text-xl font-bold tabular-nums shrink-0', fitColor)}>
            {fitPct}%
          </div>
        )}
      </div>

      {/* Badges */}
      <div className="flex flex-wrap gap-1.5">
        <span className="text-xs bg-slate-100 text-slate-600 rounded px-2 py-0.5 capitalize">
          {job.portal}
        </span>
        {job.job_type && (
          <span className="text-xs bg-slate-100 text-slate-600 rounded px-2 py-0.5">
            {job.job_type}
          </span>
        )}
        {job.salary_range && (
          <span className="text-xs bg-green-50 text-green-700 rounded px-2 py-0.5">
            {job.salary_range}
          </span>
        )}
      </div>

      {/* Score breakdown — only when ranked */}
      {job.fit_score != null && (
        <div className="space-y-1.5">
          <ScoreBar label="Tech"     value={job.tech_score} />
          <ScoreBar label="Exp"      value={job.exp_score} />
          <ScoreBar label="Location" value={job.location_score} />
          <ScoreBar label="Growth"   value={job.growth_score} />
        </div>
      )}

      {/* Strengths / Gaps */}
      {(job.strengths?.length || job.gaps?.length) ? (
        <div className="flex gap-3 text-xs">
          {job.strengths?.slice(0, 3).map((s) => (
            <span key={s} className="text-green-600">✓ {s}</span>
          ))}
          {job.gaps?.slice(0, 2).map((g) => (
            <span key={g} className="text-red-500">✗ {g}</span>
          ))}
        </div>
      ) : null}

      {/* Error */}
      {error && <p className="text-xs text-red-500">{error}</p>}

      {/* Actions */}
      <div className="flex gap-2 flex-wrap mt-auto">
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:border-slate-400 transition-colors"
        >
          View Job ↗
        </a>
        <button
          onClick={generateDocs}
          disabled={generating}
          className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-60 transition-colors"
        >
          {generating ? 'Generating…' : '📄 Gen Docs'}
        </button>
        <a
          href={api.applications.previewOnePager(job.id)}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs px-3 py-1.5 rounded-lg border border-brand-200 text-brand-600 hover:bg-brand-50 transition-colors"
        >
          Preview
        </a>
        <a
          href={api.applications.downloadOnePager(job.id)}
          className="text-xs px-3 py-1.5 rounded-lg border border-brand-200 text-brand-600 hover:bg-brand-50 transition-colors"
        >
          ↓ PDF
        </a>
      </div>
    </div>
  )
}
