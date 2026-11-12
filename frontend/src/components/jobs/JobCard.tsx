'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { Application, ApplicationStatus, Job, api } from '@/lib/api'
import { formatDate, statusLabel } from '@/lib/applications'
import clsx from 'clsx'
import SponsorshipBadge from './SponsorshipBadge'
import SponsorshipDetails from './SponsorshipDetails'

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
  const [detailsOpen, setDetailsOpen] = useState(false)
  const dialogRef = useRef<HTMLDialogElement>(null)
  const [generating, setGenerating]   = useState(false)
  const [docsReady, setDocsReady]     = useState(false)
  const [dismissing, setDismissing]   = useState(false)
  const [researching, setResearching] = useState(false)
  const [showPanel, setShowPanel]     = useState(false)
  const [error, setError]             = useState<string | null>(null)
  const [application, setApplication] = useState<Application | null>(null)
  const [tracking, setTracking] = useState(false)

  // Local copy of research data — updated optimistically after API call
  const [localJob, setLocalJob] = useState<Job>(job)

  // Keep localJob in sync when SWR refreshes after auto-research.
  useEffect(() => {
    setLocalJob(job)
  }, [job])

  const fitPct = scorePercent(localJob.fit_score)
  const hasResearch = !!localJob.researched_at

  useEffect(() => {
    const dialog = dialogRef.current
    if (!detailsOpen || !dialog) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    dialog.showModal()
    return () => {
      dialog.close()
      document.body.style.overflow = previousOverflow
    }
  }, [detailsOpen])

  useEffect(() => {
    let cancelled = false
    api.applications.get(localJob.id)
      .then((app) => {
        if (!cancelled) {
          setApplication(app)
          setDocsReady(Boolean(app.one_pager_path))
        }
      })
      .catch(() => {
        // No application exists yet for this job.
      })
    return () => {
      cancelled = true
    }
  }, [localJob.id, job])

  async function track(status: ApplicationStatus) {
    setTracking(true)
    setError(null)
    try {
      let current = await api.applications.save(localJob.id)
      if (status !== 'saved') current = await api.applications.updateStatus(localJob.id, status, current.status)
      setApplication(current)
      onRefresh?.()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not update application')
    } finally {
      setTracking(false)
    }
  }

  // ── Actions ──────────────────────────────────────────────────────────────

  async function generateDocs() {
    setGenerating(true)
    setDocsReady(false)
    setError(null)
    try {
      const queued = await api.applications.generateDocs(localJob.id)
      await api.runs.wait(queued.run_id)
      const ready = await api.applications.get(localJob.id)
      setApplication(ready)
      setDocsReady(Boolean(ready.one_pager_path))
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
        researched_at:  result.researched_at,
        description: result.description,
        description_source: result.description_source,
        description_checked_at: result.description_checked_at,
        description_error: result.description_error,
        sponsorship_status: result.sponsorship_status,
        sponsorship_checked_at: result.sponsorship_checked_at,
        sponsorship_needs_review: result.sponsorship_needs_review,
        sponsorship_evidence: result.sponsorship_evidence,
        sponsorship_notes: result.sponsorship_notes,
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
    <div className="bg-white rounded-xl border border-slate-200 shadow-sm hover:border-brand-300 hover:shadow-md transition-all p-5 flex flex-col gap-4">

      {/* Top row: title + fit score badge */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <h3 className="font-semibold text-slate-900 text-sm"><button type="button" onClick={() => setDetailsOpen(true)} aria-haspopup="dialog" className="line-clamp-2 text-left leading-6 hover:text-brand-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 rounded">{localJob.title}</button></h3>
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
        {application && (
          <Link href="/applications" className="text-xs bg-brand-50 text-brand-700 rounded px-2 py-0.5">
            {statusLabel(application.status)}
          </Link>
        )}
        <SponsorshipBadge job={localJob} />
        <span className="text-xs bg-slate-100 text-slate-600 rounded px-2 py-0.5 capitalize">
          {localJob.portal === 'manual' ? 'Manually added' : localJob.portal}
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

      <div className="mt-auto border-t border-slate-100 pt-3">
        <button type="button" onClick={() => setDetailsOpen(true)} aria-haspopup="dialog" className="flex w-full items-center justify-between rounded text-xs font-medium text-brand-700 hover:text-brand-900 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-500">
          <span>View job details</span><span aria-hidden="true">→</span>
        </button>
      </div>

      <dialog
        ref={dialogRef}
        aria-labelledby={`job-details-${localJob.id}`}
        aria-modal="true"
        onCancel={event => { event.preventDefault(); setDetailsOpen(false) }}
        onClose={() => setDetailsOpen(false)}
        onClick={event => {
          if (event.target !== event.currentTarget) return
          const bounds = event.currentTarget.getBoundingClientRect()
          if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) setDetailsOpen(false)
        }}
        className="m-auto max-h-[90dvh] w-[calc(100%_-_2rem)] max-w-2xl overflow-y-auto rounded-2xl border border-slate-200 bg-white p-0 text-slate-900 shadow-2xl backdrop:bg-slate-950/50"
      >
      {detailsOpen && <>
        <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-slate-100 bg-white p-6">
          <div className="min-w-0"><p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">Job details</p><h2 id={`job-details-${localJob.id}`} className="text-xl font-semibold leading-7">{localJob.title}</h2><p className="mt-1 text-sm text-slate-500">{localJob.company}{localJob.location ? ` · ${localJob.location}` : ''}{localJob.remote ? ' · Remote' : ''}</p></div>
          <button type="button" onClick={() => setDetailsOpen(false)} aria-label="Close job details" className="shrink-0 rounded-lg border border-slate-200 px-3 py-2 text-sm text-slate-500 hover:bg-slate-50 focus-visible:ring-2 focus-visible:ring-brand-500">✕</button>
        </header>
        <div className="space-y-5 p-6">
          <div className="flex flex-wrap items-center gap-3 text-sm text-slate-600">
            {fitPct != null && <span className="rounded-lg bg-brand-50 px-3 py-1 font-semibold text-brand-700">{fitPct}% fit</span>}
            <span className="capitalize">{localJob.portal === 'manual' ? 'Manually added' : localJob.portal}</span>
            {localJob.job_type && <span>{localJob.job_type}</span>}
            {localJob.salary_range && <span className="font-medium text-green-700">{localJob.salary_range}</span>}
            {application && <Link href="/applications" className="rounded bg-brand-50 px-2 py-1 text-brand-700 hover:underline">{statusLabel(application.status)} · Manage application</Link>}
          </div>

      <SponsorshipDetails job={localJob} />

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
      <div className="space-y-4 border-t border-slate-100 pt-5">
        <div className="flex flex-wrap items-center gap-2">
        {!application && (
          <button onClick={() => track('saved')} disabled={tracking} className="text-xs px-3 py-1.5 rounded-lg border border-brand-200 text-brand-700 disabled:opacity-50">
            {tracking ? 'Saving…' : 'Save job'}
          </button>
        )}
        {(!application || application.allowed_transitions.includes('applied')) && (
          <button onClick={() => track('applied')} disabled={tracking} className="text-xs px-3 py-1.5 rounded-lg border border-brand-200 text-brand-700 disabled:opacity-50">
            Mark applied
          </button>
        )}
        {localJob.url.startsWith('http') && <a
          href={localJob.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 text-slate-600 hover:border-slate-400 transition-colors"
        >
          Original listing ↗
        </a>}

        </div>
        <div className="flex flex-wrap items-center gap-2">

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
          disabled={generating || application?.document_status === 'generating'}
          className="text-xs px-3 py-1.5 rounded-lg bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-60 transition-colors"
        >
          {generating || application?.document_status === 'generating' ? 'Generating…' : 'Generate documents'}
        </button>

        </div>
        <div className="flex flex-wrap items-center gap-2">

        {(docsReady || generating) && (
          <a
            href={api.applications.previewOnePager(localJob.id)}
            target="_blank"
            rel="noopener noreferrer"
            aria-disabled={!docsReady}
            onClick={(e) => {
              if (!docsReady) e.preventDefault()
            }}
            className={clsx(
              'text-xs px-3 py-1.5 rounded-lg border transition-colors',
              docsReady
                ? 'border-brand-200 text-brand-600 hover:bg-brand-50'
                : 'border-slate-200 text-slate-300 pointer-events-none',
            )}
          >
            Preview Resume
          </a>
        )}

        {(docsReady || generating) && (
          <a
            href={api.applications.downloadOnePager(localJob.id)}
            aria-disabled={!docsReady}
            onClick={(e) => {
              if (!docsReady) e.preventDefault()
            }}
            className={clsx(
              'text-xs px-3 py-1.5 rounded-lg border transition-colors',
              docsReady
                ? 'border-brand-200 text-brand-600 hover:bg-brand-50'
                : 'border-slate-200 text-slate-300 pointer-events-none',
            )}
          >
            Resume PDF
          </a>
        )}

        {(docsReady || generating) && (
          <a
            href={api.applications.downloadCoverLetter(localJob.id)}
            aria-disabled={!docsReady}
            onClick={(e) => {
              if (!docsReady) e.preventDefault()
            }}
            className={clsx(
              'text-xs px-3 py-1.5 rounded-lg border transition-colors',
              docsReady
                ? 'border-brand-200 text-brand-600 hover:bg-brand-50'
                : 'border-slate-200 text-slate-300 pointer-events-none',
            )}
          >
            Cover Letter PDF
          </a>
        )}

        </div>
        <div className="border-t border-slate-100 pt-3">

        <button
          onClick={dismiss}
          disabled={dismissing}
          title="Hide this job"
          className="text-xs px-2 py-1.5 rounded-lg border border-slate-200 text-slate-400 hover:border-red-300 hover:text-red-500 disabled:opacity-40 transition-colors ml-auto"
        >
          {dismissing ? 'Hiding…' : 'Hide this job'}
        </button>
        </div>
      </div>
      <section className="border-t border-slate-100 pt-5">
        <h3 className="mb-2 text-sm font-semibold">Job description</h3>
        {localJob.description_error && <p role="status" className="mb-3 rounded-lg bg-amber-50 p-3 text-sm text-amber-800">The full listing could not be retrieved. Showing the available text, which may be incomplete.</p>}
        <p className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{localJob.description || 'No description stored. Open the original listing for the full requirements.'}</p>
        <p className="mt-4 text-xs text-slate-400">{localJob.posted_at ? `Posted ${formatDate(localJob.posted_at)}` : `Discovered ${formatDate(localJob.found_at)}`}</p>
      </section>
      </div>
      </>}
      </dialog>
    </div>
  )
}
