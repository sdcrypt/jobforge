'use client'

import { useEffect, useState } from 'react'
import { useJobs } from '@/hooks/useJobs'
import JobCard from '@/components/jobs/JobCard'
import { api } from '@/lib/api'
import { usePipelineRun } from '@/hooks/usePipelineRun'
import PipelineStatus from '@/components/agents/PipelineStatus'
import ManualJobForm from '@/components/jobs/ManualJobForm'

const STATUS_TABS = ['all', 'new', 'ranked', 'saved', 'preparing', 'applied', 'screening', 'interviewing', 'offer', 'accepted', 'rejected', 'withdrawn'] as const
type StatusTab = typeof STATUS_TABS[number]
const EMPTY_FILTERS = { keyword: '', company: '', portal: '', location: '', remote: '', salary_min: '', salary_max: '', salary_currency: 'USD', salary_period: 'year', posted_within_days: '', sort: 'fit', has_salary: false }

export default function JobsPage() {
  const [activeTab, setActiveTab] = useState<StatusTab>('all')
  const [minScore, setMinScore] = useState(0)
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [offset, setOffset] = useState(0)
  const [pageSize, setPageSize] = useState(20)
  const [showImport, setShowImport] = useState(false)
  const statusParams = activeTab === 'all' ? {} : ['new', 'ranked'].includes(activeTab) ? { status: activeTab } : { application_status: activeTab }
  const { jobs, total, hasMore, isLoading, error, refresh } = useJobs({
    ...statusParams, keyword: filters.keyword, company: filters.company, portal: filters.portal,
    location: filters.location, remote: filters.remote ? filters.remote === 'true' : undefined,
    salary_min: filters.salary_min === '' ? undefined : Number(filters.salary_min),
    salary_max: filters.salary_max === '' ? undefined : Number(filters.salary_max),
    salary_currency: filters.salary_currency.toUpperCase(), salary_period: filters.salary_period,
    has_salary: filters.has_salary, posted_within_days: filters.posted_within_days ? Number(filters.posted_within_days) : undefined,
    sort: filters.sort, min_score: minScore, limit: pageSize, offset,
  })
  const [runningPipeline, setRunningPipeline] = useState(false)
  const { activeRun, refreshRuns } = usePipelineRun()
  const pipelineBusy = runningPipeline || Boolean(activeRun)
  const [pipelineMsg, setPipelineMsg] = useState<string | null>(null)
  const [clearing, setClearing] = useState(false)

  useEffect(() => {
    if (!isLoading && !error && offset > 0 && offset >= total) setOffset(Math.max(0, Math.ceil(total / pageSize) - 1) * pageSize)
  }, [total, offset, pageSize, isLoading, error])

  function changeFilter(field: keyof typeof EMPTY_FILTERS, value: string | boolean) {
    setFilters(previous => ({ ...previous, [field]: value }))
    setOffset(0)
  }

  async function runPipeline() {
    setRunningPipeline(true)
    setPipelineMsg(null)
    try {
      const res = await api.pipeline.run()
      await refreshRuns()
      setPipelineMsg(res.message)
      setTimeout(() => {
        refresh()
        setPipelineMsg(null)
      }, 3000)
    } catch (e: unknown) {
      setPipelineMsg(e instanceof Error ? e.message : 'Pipeline failed')
    } finally {
      setRunningPipeline(false)
    }
  }

  async function clearJobs() {
    if (!confirm('Delete untracked jobs? Saved applications and their jobs are preserved. This cannot be undone.')) return
    setClearing(true)
    try {
      const res = await api.jobs.clear()
      setPipelineMsg(`Cleared ${res.deleted} jobs — run the pipeline to fetch fresh results.`)
      refresh()
    } catch (e: unknown) {
      setPipelineMsg(e instanceof Error ? e.message : 'Clear failed')
    } finally {
      setClearing(false)
    }
  }

  return (
    <div className="max-w-5xl mx-auto">
      <PipelineStatus />
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Jobs</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {total} matching job{total !== 1 ? 's' : ''} · auto-refreshes every 10 s
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => setShowImport(previous => !previous)} className="rounded-lg border border-brand-200 px-3 py-2 text-sm text-brand-700">+ Add job manually</button>
          <button
            onClick={clearJobs}
            disabled={clearing || jobs.length === 0}
            title="Clear jobs that are not tracked as applications"
            className="px-3 py-2 border border-slate-200 text-slate-500 rounded-lg text-sm hover:border-red-300 hover:text-red-500 disabled:opacity-40 transition-colors"
          >
            {clearing ? '…' : '🗑 Clear'}
          </button>
          <button
            onClick={runPipeline}
            disabled={pipelineBusy}
            className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-60 transition-colors flex items-center gap-2"
          >
            {pipelineBusy ? (
              <><span className="animate-spin">⚙️</span> Running…</>
            ) : (
              '🚀 Run Pipeline'
            )}
          </button>
        </div>
      </div>

      {showImport && <ManualJobForm onClose={() => setShowImport(false)} onImported={() => {
        setShowImport(false)
        setActiveTab('all')
        setMinScore(0)
        setOffset(0)
        setFilters({ ...EMPTY_FILTERS, portal: 'manual', sort: 'newest' })
        void refresh()
        setPipelineMsg('Job added. Use Research to evaluate it, or Save job to shortlist it.')
      }} />}

      {/* Pipeline message */}
      {pipelineMsg && (
        <div className="mb-4 px-4 py-2 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">
          {pipelineMsg}
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-4 mb-6 flex-wrap">
        {/* Status tabs */}
        <div className="flex flex-wrap gap-1 bg-slate-100 p-1 rounded-lg">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => { setActiveTab(tab); setOffset(0) }}
              className={`px-3 py-1 rounded text-xs font-medium capitalize transition-colors ${
                activeTab === tab
                  ? 'bg-white shadow text-slate-900'
                  : 'text-slate-500 hover:text-slate-700'
              }`}
            >
              {tab}
            </button>
          ))}
        </div>

        {/* Min score filter */}
        <div className="flex items-center gap-2 text-sm text-slate-600">
          <label htmlFor="min-score">Min fit:</label>
          <input
            id="min-score"
            type="range"
            min={0}
            max={90}
            step={5}
            value={minScore}
            onChange={(event) => { setMinScore(Number(event.target.value)); setOffset(0) }}
            className="w-24"
          />
          <span className="tabular-nums w-8">{minScore}%</span>
        </div>
      </div>

      <section aria-label="Job filters" className="mb-6 space-y-3 rounded-xl border bg-white p-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {(['keyword', 'company', 'location'] as const).map(field => <label key={field} className="text-xs font-medium capitalize text-slate-600">{field === 'keyword' ? 'Keyword / company / description' : field}<input className="input mt-1" value={filters[field]} onChange={event => changeFilter(field, event.target.value)} /></label>)}
          <label className="text-xs font-medium text-slate-600">Portal<select className="input mt-1" value={filters.portal} onChange={event => changeFilter('portal', event.target.value)}><option value="">All portals</option>{['linkedin', 'remoteok', 'weworkremotely', 'hackernews', 'jobleads', 'manual'].map(portal => <option key={portal} value={portal}>{portal === 'manual' ? 'Manually added' : portal}</option>)}</select></label>
          <label className="text-xs font-medium text-slate-600">Work setting<select className="input mt-1" value={filters.remote} onChange={event => changeFilter('remote', event.target.value)}><option value="">Any</option><option value="true">Remote</option><option value="false">Not marked remote</option></select></label>
          <label className="text-xs font-medium text-slate-600">Posted within<select className="input mt-1" value={filters.posted_within_days} onChange={event => changeFilter('posted_within_days', event.target.value)}><option value="">Any date</option>{[1, 3, 7, 14, 30, 90].map(days => <option key={days} value={days}>{days} days</option>)}</select></label>
          <label className="text-xs font-medium text-slate-600">Salary from<input className="input mt-1" type="number" min="0" value={filters.salary_min} onChange={event => changeFilter('salary_min', event.target.value)} /></label>
          <label className="text-xs font-medium text-slate-600">Salary to<input className="input mt-1" type="number" min="0" value={filters.salary_max} onChange={event => changeFilter('salary_max', event.target.value)} /></label>
          <label className="text-xs font-medium text-slate-600">Salary currency<input className="input mt-1" maxLength={3} value={filters.salary_currency} onChange={event => changeFilter('salary_currency', event.target.value.toUpperCase())} /></label>
          <label className="text-xs font-medium text-slate-600">Pay period<select className="input mt-1" value={filters.salary_period} onChange={event => changeFilter('salary_period', event.target.value)}><option value="year">Year</option><option value="month">Month</option><option value="hour">Hour</option></select></label>
          <label className="text-xs font-medium text-slate-600">Sort by<select className="input mt-1" value={filters.sort} onChange={event => changeFilter('sort', event.target.value)}><option value="fit">Best fit</option><option value="newest">Recently discovered</option><option value="posted">Recently posted</option><option value="salary">Highest salary</option><option value="company">Company A–Z</option></select></label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={filters.has_salary} onChange={event => changeFilter('has_salary', event.target.checked)} /> Has salary information</label>
        </div>
        <p className="text-xs text-slate-500">Salary amounts match overlapping ranges in the selected currency and pay period; unknown amounts are excluded. Date filters exclude unknown posting dates.</p>
        <button onClick={() => { setFilters(EMPTY_FILTERS); setMinScore(0); setActiveTab('all'); setOffset(0) }} className="text-sm text-brand-700 underline">Reset filters</button>
      </section>
      {error && <p role="alert" className="mb-4 text-sm text-red-700">{error.message}</p>}

      {/* Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-48 bg-slate-100 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : jobs.length === 0 ? (
        <div className="text-center py-16 text-slate-400">
          <div className="text-4xl mb-3">💼</div>
          <p className="font-medium">{error ? 'Could not load jobs. Please try again.' : 'No jobs found'}</p>
          <p className="text-sm mt-1">
            {jobs.length === 0
              ? 'Run the pipeline to search for jobs'
              : 'Try adjusting the filters'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
            {jobs.map((job) => (
            <JobCard key={job.id} job={job} onRefresh={refresh} />
          ))}
        </div>
      )}
      <nav aria-label="Job pages" className="mt-6 flex flex-wrap items-center gap-3 text-sm">
        <button className="rounded border px-3 py-2 disabled:opacity-40" disabled={offset === 0 || isLoading} onClick={() => setOffset(previous => Math.max(0, previous - pageSize))}>Previous</button>
        <span>{total ? `${offset + 1}–${Math.min(offset + pageSize, total)} of ${total}` : '0 jobs'}</span>
        <button className="rounded border px-3 py-2 disabled:opacity-40" disabled={!hasMore || isLoading} onClick={() => setOffset(previous => previous + pageSize)}>Next</button>
        <label>Per page<select className="ml-2 rounded border p-2" value={pageSize} onChange={event => { setPageSize(Number(event.target.value)); setOffset(0) }}>{[20, 50, 100].map(size => <option key={size} value={size}>{size}</option>)}</select></label>
      </nav>
    </div>
  )
}
