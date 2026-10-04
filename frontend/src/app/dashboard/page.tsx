'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import { api, Stats, TopJob } from '@/lib/api'
import clsx from 'clsx'

// ── Helpers ───────────────────────────────────────────────────────────────────

function timeAgo(isoStr: string): string {
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins  = Math.floor(diff / 60000)
  const hours = Math.floor(mins / 60)
  const days  = Math.floor(hours / 24)
  if (mins < 2)   return 'just now'
  if (mins < 60)  return `${mins}m ago`
  if (hours < 24) return `${hours}h ago`
  return `${days}d ago`
}

function fitColor(score: number | null) {
  if (score == null) return 'text-slate-400'
  if (score >= 70)   return 'text-green-600'
  if (score >= 45)   return 'text-yellow-600'
  return 'text-red-500'
}

function fitBg(score: number | null) {
  if (score == null) return 'bg-slate-100 text-slate-500'
  if (score >= 70)   return 'bg-green-50 text-green-700'
  if (score >= 45)   return 'bg-yellow-50 text-yellow-700'
  return 'bg-red-50 text-red-600'
}

// ── Stat tile ─────────────────────────────────────────────────────────────────

interface TileProps {
  icon: string
  value: string | number
  label: string
  sub?: string
  accent?: string
}

function Tile({ icon, value, label, sub, accent = 'bg-slate-50' }: TileProps) {
  return (
    <div className={clsx('rounded-xl border border-slate-200 p-5 flex flex-col gap-1', accent)}>
      <div className="text-2xl">{icon}</div>
      <div className="text-3xl font-bold text-slate-900 tabular-nums mt-1">{value}</div>
      <div className="text-sm font-medium text-slate-600">{label}</div>
      {sub && <div className="text-xs text-slate-400 mt-0.5">{sub}</div>}
    </div>
  )
}

// ── Mini bar chart ────────────────────────────────────────────────────────────

function MiniBar({ label, value, max, color }: { label: string; value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 text-xs text-slate-500 text-right shrink-0">{label}</div>
      <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
        <div
          className={clsx('h-full rounded-full transition-all duration-700', color)}
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="w-7 text-xs font-medium text-slate-700 tabular-nums">{value}</div>
    </div>
  )
}

// ── Top job row ───────────────────────────────────────────────────────────────

function TopJobRow({ job, rank }: { job: TopJob; rank: number }) {
  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-slate-50 last:border-0">
      <div className="text-xs font-bold text-slate-300 w-4 shrink-0 tabular-nums">{rank}</div>

      <div
        className={clsx(
          'text-sm font-bold tabular-nums w-10 text-center shrink-0 rounded-lg py-0.5',
          fitBg(job.fit_score),
        )}
      >
        {Math.round(job.fit_score)}%
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-slate-900 truncate">{job.title}</p>
        <p className="text-xs text-slate-500 truncate">
          {job.company}
          {job.location ? ` · ${job.location}` : ''}
          {job.remote ? ' · Remote' : ''}
        </p>
      </div>

      <div className="flex items-center gap-1.5 shrink-0">
        {job.researched_at && (
          <span className="text-xs bg-brand-50 text-brand-700 rounded px-1.5 py-0.5">✓</span>
        )}
        <span className="text-xs bg-slate-100 text-slate-500 rounded px-1.5 py-0.5 capitalize">
          {job.portal}
        </span>
        <a
          href={job.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs px-2 py-1 border border-slate-200 rounded text-slate-500 hover:border-slate-400 hover:text-slate-700 transition-colors"
        >
          ↗
        </a>
      </div>
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState({ onRun, running }: { onRun: () => void; running: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="text-6xl mb-4">🔨</div>
      <h2 className="text-xl font-bold text-slate-800 mb-2">Welcome to JobForge</h2>
      <p className="text-slate-500 text-sm max-w-xs mb-2">
        No jobs yet. Set up your profile and search config, then run the pipeline to find your next role.
      </p>
      <div className="flex gap-3 mt-6">
        <Link
          href="/profile"
          className="px-4 py-2 border border-slate-300 text-slate-700 rounded-lg text-sm hover:border-slate-400 transition-colors"
        >
          👤 Set up Profile
        </Link>
        <Link
          href="/search"
          className="px-4 py-2 border border-slate-300 text-slate-700 rounded-lg text-sm hover:border-slate-400 transition-colors"
        >
          🔍 Configure Search
        </Link>
        <button
          onClick={onRun}
          disabled={running}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-60 transition-colors flex items-center gap-2"
        >
          {running ? <><span className="animate-spin">⚙️</span> Running…</> : '🚀 Run Pipeline'}
        </button>
      </div>
    </div>
  )
}

// ── Main dashboard ────────────────────────────────────────────────────────────

export default function DashboardPage() {
  const [stats, setStats]         = useState<Stats | null>(null)
  const [loading, setLoading]     = useState(true)
  const [running, setRunning]     = useState(false)
  const [pipelineMsg, setPipelineMsg] = useState<string | null>(null)

  async function load() {
    try {
      const data = await api.stats.get()
      setStats(data)
    } catch {
      // no jobs yet — stats endpoint may 500 if tables empty
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
    const iv = setInterval(load, 15000)
    return () => clearInterval(iv)
  }, [])

  async function runPipeline() {
    setRunning(true)
    setPipelineMsg(null)
    try {
      await api.pipeline.run()
      setPipelineMsg('Pipeline started — jobs will appear as the search completes.')
      setTimeout(() => { load(); setPipelineMsg(null) }, 4000)
    } catch (e: unknown) {
      setPipelineMsg(e instanceof Error ? e.message : 'Pipeline failed')
    } finally {
      setRunning(false)
    }
  }

  if (loading) {
    return (
      <div className="max-w-5xl mx-auto space-y-6 pt-2 animate-pulse">
        <div className="h-10 bg-slate-100 rounded-lg w-64" />
        <div className="grid grid-cols-4 gap-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-32 bg-slate-100 rounded-xl" />
          ))}
        </div>
        <div className="grid grid-cols-5 gap-4">
          <div className="col-span-3 h-80 bg-slate-100 rounded-xl" />
          <div className="col-span-2 space-y-4">
            <div className="h-36 bg-slate-100 rounded-xl" />
            <div className="h-36 bg-slate-100 rounded-xl" />
          </div>
        </div>
      </div>
    )
  }

  const isEmpty = !stats || stats.total_jobs === 0

  if (isEmpty) {
    return <EmptyState onRun={runPipeline} running={running} />
  }

  const { total_jobs, researched, high_fit, docs_generated, avg_fit_score,
          by_portal, score_buckets, top_jobs, last_pipeline } = stats!

  const researchedPct = total_jobs > 0 ? Math.round((researched / total_jobs) * 100) : 0
  const maxPortal     = Math.max(...Object.values(by_portal), 1)
  const maxBucket     = Math.max(...Object.values(score_buckets), 1)

  const BUCKET_COLORS: Record<string, string> = {
    '85-100': 'bg-green-500',
    '70-84':  'bg-green-400',
    '50-69':  'bg-yellow-400',
    '30-49':  'bg-orange-400',
    '0-29':   'bg-red-400',
  }

  const PORTAL_LABELS: Record<string, string> = {
    linkedin:       '🔗 LinkedIn',
    remoteok:       '🌍 RemoteOK',
    weworkremotely: '🏠 WWR',
    hackernews:     '🟠 HN Hiring',
  }

  return (
    <div className="max-w-5xl mx-auto space-y-6">

      {/* ── Header ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Dashboard</h1>
          {last_pipeline ? (
            <p className="text-slate-500 text-sm mt-0.5">
              Last pipeline run <span className="font-medium text-slate-700">{timeAgo(last_pipeline.run_at)}</span>
              {' · '}found <span className="font-medium text-slate-700">{last_pipeline.found}</span> jobs
            </p>
          ) : (
            <p className="text-slate-500 text-sm mt-0.5">No pipeline run yet</p>
          )}
        </div>

        <div className="flex items-center gap-2">
          {pipelineMsg && (
            <span className="text-xs text-green-700 bg-green-50 border border-green-200 px-3 py-1.5 rounded-lg">
              {pipelineMsg}
            </span>
          )}
          <button
            onClick={runPipeline}
            disabled={running}
            className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-60 transition-colors flex items-center gap-2"
          >
            {running ? <><span className="animate-spin">⚙️</span> Running…</> : '🚀 Run Pipeline'}
          </button>
        </div>
      </div>

      {/* ── Stat tiles ── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <Tile
          icon="💼"
          value={total_jobs}
          label="Total Jobs"
          sub={avg_fit_score != null ? `Avg fit ${avg_fit_score}%` : 'Not yet scored'}
          accent="bg-white"
        />
        <Tile
          icon="🔬"
          value={researched}
          label="Researched"
          sub={`${researchedPct}% of jobs`}
          accent="bg-white"
        />
        <Tile
          icon="✨"
          value={high_fit}
          label="High Fit (70%+)"
          sub={total_jobs > 0 ? `${Math.round((high_fit / total_jobs) * 100)}% of pipeline` : ''}
          accent={high_fit > 0 ? 'bg-green-50' : 'bg-white'}
        />
        <Tile
          icon="📄"
          value={docs_generated}
          label="Docs Generated"
          sub="CVs + cover letters"
          accent="bg-white"
        />
      </div>

      {/* ── Body: two columns ── */}
      <div className="grid grid-cols-5 gap-4">

        {/* Left — Top Jobs */}
        <div className="col-span-3 bg-white rounded-xl border border-slate-200 p-5">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-semibold text-slate-800">Top Jobs by Fit Score</h2>
            <Link
              href="/jobs"
              className="text-xs text-brand-600 hover:text-brand-700 font-medium transition-colors"
            >
              See all {total_jobs} →
            </Link>
          </div>

          {top_jobs.length === 0 ? (
            <p className="text-sm text-slate-400 py-8 text-center">
              Run the pipeline and rank jobs to see top matches here.
            </p>
          ) : (
            <div>
              {top_jobs.map((job, i) => (
                <TopJobRow key={job.id} job={job} rank={i + 1} />
              ))}
            </div>
          )}

          <div className="mt-4 pt-4 border-t border-slate-50 flex gap-2">
            <Link
              href="/jobs"
              className="flex-1 text-center py-2 border border-slate-200 text-slate-600 text-xs rounded-lg hover:border-brand-300 hover:text-brand-700 transition-colors"
            >
              💼 Browse All Jobs
            </Link>
            <Link
              href="/search"
              className="flex-1 text-center py-2 border border-slate-200 text-slate-600 text-xs rounded-lg hover:border-slate-400 transition-colors"
            >
              🔍 Search Config
            </Link>
          </div>
        </div>

        {/* Right — Charts */}
        <div className="col-span-2 flex flex-col gap-4">

          {/* Score distribution */}
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <h2 className="font-semibold text-slate-800 mb-4">Fit Score Distribution</h2>
            <div className="space-y-2.5">
              {Object.entries(score_buckets).map(([bucket, count]) => (
                <MiniBar
                  key={bucket}
                  label={bucket}
                  value={count}
                  max={maxBucket}
                  color={BUCKET_COLORS[bucket] ?? 'bg-slate-400'}
                />
              ))}
            </div>
          </div>

          {/* Portal breakdown */}
          <div className="bg-white rounded-xl border border-slate-200 p-5">
            <h2 className="font-semibold text-slate-800 mb-4">Portal Breakdown</h2>
            <div className="space-y-2.5">
              {Object.entries(by_portal)
                .sort(([, a], [, b]) => b - a)
                .map(([portal, count]) => (
                  <MiniBar
                    key={portal}
                    label={PORTAL_LABELS[portal] ?? portal}
                    value={count}
                    max={maxPortal}
                    color="bg-brand-500"
                  />
                ))}
            </div>
          </div>

        </div>
      </div>

      {/* ── Quick actions footer ── */}
      <div className="grid grid-cols-3 gap-4 pb-4">
        {[
          {
            href: '/profile',
            icon: '👤',
            title: 'My Profile',
            desc: 'Update your skills, experience, and target roles',
          },
          {
            href: '/search',
            icon: '🔍',
            title: 'Search Config',
            desc: 'Set keywords, locations, portals, and search depth',
          },
          {
            href: '/jobs',
            icon: '💼',
            title: 'Browse Jobs',
            desc: `${high_fit} high-fit jobs waiting · filter, research, generate docs`,
          },
        ].map((card) => (
          <Link
            key={card.href}
            href={card.href}
            className="bg-white rounded-xl border border-slate-200 p-4 hover:border-brand-300 hover:shadow-sm transition-all group"
          >
            <div className="text-xl mb-2">{card.icon}</div>
            <p className="text-sm font-semibold text-slate-800 group-hover:text-brand-700 transition-colors">
              {card.title}
            </p>
            <p className="text-xs text-slate-500 mt-0.5">{card.desc}</p>
          </Link>
        ))}
      </div>

    </div>
  )
}
