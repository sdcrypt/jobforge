'use client'

import { useState } from 'react'
import { useJobs } from '@/hooks/useJobs'
import JobCard from '@/components/jobs/JobCard'
import { api } from '@/lib/api'

const STATUS_TABS = ['all', 'new', 'reviewed', 'applied', 'rejected'] as const
type StatusTab = typeof STATUS_TABS[number]

export default function JobsPage() {
  const { jobs, isLoading, refresh } = useJobs()
  const [activeTab, setActiveTab] = useState<StatusTab>('all')
  const [minScore, setMinScore] = useState(0)
  const [runningPipeline, setRunningPipeline] = useState(false)
  const [pipelineMsg, setPipelineMsg] = useState<string | null>(null)

  const filtered = jobs
    .filter((j) => activeTab === 'all' || j.status === activeTab)
    .filter((j) => j.fit_score == null || j.fit_score >= minScore)
    .sort((a, b) => (b.fit_score ?? 0) - (a.fit_score ?? 0))

  async function runPipeline() {
    setRunningPipeline(true)
    setPipelineMsg(null)
    try {
      const res = await api.pipeline.run()
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

  return (
    <div className="max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Ranked Jobs</h1>
          <p className="text-slate-500 text-sm mt-0.5">
            {jobs.length} job{jobs.length !== 1 ? 's' : ''} found · auto-refreshes every 10 s
          </p>
        </div>
        <button
          onClick={runPipeline}
          disabled={runningPipeline}
          className="px-4 py-2 bg-brand-600 text-white rounded-lg text-sm font-medium hover:bg-brand-700 disabled:opacity-60 transition-colors flex items-center gap-2"
        >
          {runningPipeline ? (
            <>
              <span className="animate-spin">⚙️</span> Running…
            </>
          ) : (
            '🚀 Run Pipeline'
          )}
        </button>
      </div>

      {/* Pipeline message */}
      {pipelineMsg && (
        <div className="mb-4 px-4 py-2 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm">
          {pipelineMsg}
        </div>
      )}

      {/* Filters */}
      <div className="flex items-center gap-4 mb-6 flex-wrap">
        {/* Status tabs */}
        <div className="flex gap-1 bg-slate-100 p-1 rounded-lg">
          {STATUS_TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
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
            onChange={(e) => setMinScore(Number(e.target.value))}
            className="w-24"
          />
          <span className="tabular-nums w-8">{minScore}%</span>
        </div>
      </div>

      {/* Grid */}
      {isLoading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-48 bg-slate-100 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-slate-400">
          <div className="text-4xl mb-3">💼</div>
          <p className="font-medium">No jobs found</p>
          <p className="text-sm mt-1">
            {jobs.length === 0
              ? 'Run the pipeline to search for jobs'
              : 'Try adjusting the filters'}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((job) => (
            <JobCard key={job.id} job={job} onRefresh={refresh} />
          ))}
        </div>
      )}
    </div>
  )
}
