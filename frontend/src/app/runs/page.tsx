'use client'

import { useEffect, useState } from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { api, TaskRun } from '@/lib/api'
import { formatDate, statusLabel } from '@/lib/applications'

const RUN_KINDS = ['pipeline', 'search', 'rank', 'research', 'docgen', 'resume_parse', 'apply']
const RUN_STATUSES = ['queued', 'running', 'retrying', 'succeeded', 'partial', 'failed']

function RunBadge({ status }: { status: string }) {
  const color = status === 'failed' ? 'bg-red-50 text-red-700'
    : status === 'succeeded' ? 'bg-green-50 text-green-700'
      : status === 'partial' || status === 'retrying' ? 'bg-amber-50 text-amber-800' : 'bg-brand-50 text-brand-700'
  return <span className={`rounded px-2 py-1 text-xs font-medium ${color}`}>{status === 'partial' ? 'Completed with errors' : statusLabel(status)}</span>
}

export default function RunsPage() {
  const [kind, setKind] = useState('')
  const [status, setStatus] = useState('')
  const [offset, setOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [maxAttempts, setMaxAttempts] = useState(3)
  const [actionError, setActionError] = useState<string | null>(null)
  const { data, error, isLoading, mutate } = useSWR(['runs', kind, status, offset], () => api.runs.list({ kind, status, offset, limit: 20 }), { refreshInterval: 3000 })
  const { data: selected, mutate: refreshSelected } = useSWR(selectedId ? ['run', selectedId] : null, () => api.runs.get(selectedId!), { refreshInterval: 3000 })
  const { data: history } = useSWR(selectedId ? ['run-events', selectedId] : null, () => api.runs.events(selectedId!), { refreshInterval: 3000 })

  useEffect(() => {
    setSelectedId(Number(new URLSearchParams(window.location.search).get('run')) || null)
  }, [])

  async function retry(run: TaskRun) {
    setRetrying(true)
    setActionError(null)
    try {
      const queued = await api.runs.retry(run.id, maxAttempts)
      setSelectedId(queued.run_id)
      await mutate()
      await refreshSelected()
    } catch (cause: unknown) {
      setActionError(cause instanceof Error ? cause.message : 'Could not queue retry')
    } finally {
      setRetrying(false)
    }
  }

  return <div className="max-w-6xl mx-auto space-y-5">
    <div><h1 className="text-2xl font-bold">Runs</h1><p className="mt-1 text-sm text-slate-500">Progress and history stay here when you close the page. Updates every 3 seconds.</p></div>
    <div className="flex flex-wrap gap-3">
      <label className="text-sm">Work type<select className="input mt-1" value={kind} onChange={event => { setKind(event.target.value); setOffset(0) }}><option value="">All work</option>{RUN_KINDS.map(value => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>
      <label className="text-sm">Status<select className="input mt-1" value={status} onChange={event => { setStatus(event.target.value); setOffset(0) }}><option value="">All statuses</option>{RUN_STATUSES.map(value => <option key={value} value={value}>{statusLabel(value)}</option>)}</select></label>
    </div>
    {(error || actionError) && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{actionError || error.message}</p>}
    {isLoading ? <p role="status">Loading runs…</p> : data?.runs.length === 0 ? <p className="rounded-xl border bg-white p-8 text-center text-slate-500">No runs match these filters. Start the pipeline from Jobs or Dashboard.</p> : <div className="overflow-x-auto rounded-xl border bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-50 text-slate-500"><tr>{['Run', 'Status', 'Stage', 'Attempt', 'Created'].map(heading => <th key={heading} scope="col" className="p-3 font-medium">{heading}</th>)}</tr></thead>
        <tbody>{data?.runs.map(run => <tr key={run.id} className={`border-t ${selectedId === run.id ? 'bg-brand-50' : ''}`}>
          <td className="p-3"><button className="text-left text-brand-700 hover:underline" onClick={() => { setSelectedId(run.id); setActionError(null) }}>{statusLabel(run.kind)} · {run.id}</button>{(run.job_id || run.config_id) && <p className="mt-1 text-xs text-slate-700">{run.label}</p>}<p className="mt-1 text-xs text-slate-500">{run.trigger}{run.parent_id ? ' · part of pipeline' : ''}{run.retry_of ? ' · manual retry' : ''}</p></td>
          <td className="p-3"><RunBadge status={run.status} /></td><td className="p-3 capitalize">{run.stage}</td><td className="p-3">{run.attempts}/{run.max_attempts}</td><td className="p-3 whitespace-nowrap text-xs">{formatDate(run.created_at)}</td>
        </tr>)}</tbody>
      </table>
    </div>}
    <div className="flex items-center gap-3 text-sm"><button className="rounded border px-3 py-1 disabled:opacity-40" disabled={offset === 0} onClick={() => setOffset(previous => Math.max(0, previous - 20))}>Previous</button><span>{data?.count || 0} runs</span><button className="rounded border px-3 py-1 disabled:opacity-40" disabled={offset + 20 >= (data?.count || 0)} onClick={() => setOffset(previous => previous + 20)}>Next</button></div>
    {selected && <section className="rounded-xl border bg-white p-5 space-y-4" aria-label="Run details">
      <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-semibold">{statusLabel(selected.kind)} run</h2><p className="break-all text-xs text-slate-500">{selected.id}</p></div><RunBadge status={selected.status} /></div>
      <p className="text-xs text-slate-500">Started {formatDate(selected.started_at)} · Finished {formatDate(selected.finished_at)} · Attempt {selected.attempts}/{selected.max_attempts}</p>
      {(selected.job_id || selected.config_id) && <p className="text-sm font-medium">{selected.label}</p>}
      {Boolean(selected.result?.portal_reports) && <section className="space-y-3"><h3 className="text-sm font-semibold">Portal search reports</h3>{Object.entries(selected.result!.portal_reports as Record<string, { status: string; found: number; searches: { keyword: string; location: string; status: string; errors: string[]; excluded_old: number; unknown_date: number }[] }>).map(([portal, report]) => <div key={portal} className="rounded-lg border p-3 text-sm">
        <p className="font-medium">{portal} · {report.status} · {report.found} results before deduplication</p>
        {report.searches.map((search, index) => <div key={index} className="mt-2 text-xs text-slate-600"><p>{search.keyword} / {search.location} · {search.status} · {search.excluded_old} outside date window · {search.unknown_date} undated</p>{search.errors.map((message, errorIndex) => <p key={errorIndex} className="mt-1 text-red-700">{message}</p>)}</div>)}
      </div>)}</section>}
      {selected.status === 'queued' && <p className="text-sm text-slate-600">Waiting for a worker. You can leave this page; the run is saved.</p>}
      {selected.next_retry_at && <p className="text-sm text-amber-800">Automatic retry due {formatDate(selected.next_retry_at)}. The scheduler checks every minute.</p>}
      {selected.dispatch_error && <p className="text-sm text-amber-800">{selected.dispatch_error}</p>}
      {selected.error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">{selected.error_type}: {selected.error}</p>}
      {selected.parent_id && <button className="text-sm text-brand-700 underline" onClick={() => setSelectedId(selected.parent_id)}>View parent pipeline</button>}
      {selected.retry_of && <button className="text-sm text-brand-700 underline" onClick={() => setSelectedId(selected.retry_of)}>View original run</button>}
      {Boolean(selected.children?.length) && <section className="space-y-2"><h3 className="text-sm font-semibold">Related research tasks</h3>{selected.children?.map(child => <button key={child.id} onClick={() => setSelectedId(child.id)} className="mr-2 rounded border px-2 py-1 text-xs text-brand-700">{child.id} · {child.status}</button>)}</section>}
      <ol className="space-y-3">{selected.stages.map((entry, index) => <li key={`${entry.attempt}-${entry.name}-${index}`} className="rounded-lg border p-3 text-sm">
        <div className="flex justify-between gap-2"><span className="font-medium capitalize">{entry.name} · attempt {entry.attempt}</span><span className={entry.status === 'failed' ? 'text-red-700' : 'text-slate-500'}>{statusLabel(entry.status)}</span></div>
        <p className="mt-1 text-slate-600">{entry.message}</p>
        {entry.total > 0 && <><progress aria-label={`${entry.name} progress`} className="mt-2 w-full accent-blue-600" value={entry.completed} max={entry.total} /><p className="text-xs text-slate-500">{entry.completed}/{entry.total}</p></>}
        {entry.error && <p className="mt-1 text-red-700">{entry.error}</p>}
      </li>)}</ol>
      {selected.kind === 'resume_parse' && selected.status === 'succeeded' && <Link href={`/profile?run=${selected.id}`} className="inline-block text-sm text-brand-700 underline">Review imported resume in Profile</Link>}
      {selected.result && selected.kind !== 'resume_parse' && <details><summary className="cursor-pointer text-sm font-medium">Saved results</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words text-xs text-slate-600">{JSON.stringify(selected.result, null, 2)}</pre></details>}
      {['failed', 'partial'].includes(selected.status) && <div><div className="flex flex-wrap items-center gap-3">{selected.kind !== 'apply' && <label className="text-sm">Maximum attempts<select className="input mt-1" value={maxAttempts} onChange={event => setMaxAttempts(Number(event.target.value))}>{[1, 2, 3, 4, 5].map(count => <option key={count} value={count}>{count}{count === 1 ? ' · no automatic retries' : ''}</option>)}</select></label>}<button disabled={retrying} onClick={() => void retry(selected)} className="rounded-lg bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50">{retrying ? 'Queueing…' : 'Retry run'}</button></div><p className="mt-2 text-xs text-slate-500">Retries create a new run and preserve this history. Saved jobs are deduplicated; completed ranking and research are retained.</p></div>}
      <details><summary className="cursor-pointer text-sm font-medium">Activity history</summary><ol className="mt-3 space-y-2">{history?.events.slice().reverse().map(event => <li key={event.id} className="text-xs"><span className="text-slate-400">{formatDate(event.created_at)} · {event.agent}</span><p className={event.status === 'error' ? 'text-red-700' : 'text-slate-600'}>{event.message}</p></li>)}</ol></details>
      {selected.traceback && <details><summary className="cursor-pointer text-sm font-medium">Technical failure details</summary><pre className="mt-2 overflow-x-auto whitespace-pre-wrap break-words text-xs">{selected.traceback}</pre></details>}
    </section>}
  </div>
}
