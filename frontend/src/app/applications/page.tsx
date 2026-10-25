'use client'

import { FormEvent, useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { api, Application, ApplicationDetails, ApplicationStatus, InterviewRound } from '@/lib/api'
import { APPLICATION_STATUSES, formatDate, fromLocalInput, reminderDue, statusLabel, toLocalInput } from '@/lib/applications'

function details(application: Application): ApplicationDetails {
  return {
    applied_at: application.applied_at,
    recruiter_name: application.recruiter_name,
    recruiter_email: application.recruiter_email,
    recruiter_phone: application.recruiter_phone,
    notes: application.notes,
    preparation_notes: application.preparation_notes,
    outcome: application.outcome,
    deadline_at: application.deadline_at,
    follow_up_at: application.follow_up_at,
    follow_up_completed_at: application.follow_up_completed_at,
    interview_rounds: (application.interview_rounds || []).map((round, index) => ({
      ...round, id: round.id || `existing-${index}`, round: round.round || index + 1,
    })),
  }
}

function StatusBadge({ status }: { status: ApplicationStatus }) {
  const color = ['accepted', 'offer'].includes(status) ? 'bg-green-50 text-green-700'
    : ['rejected', 'withdrawn'].includes(status) ? 'bg-slate-100 text-slate-500'
      : 'bg-brand-50 text-brand-700'
  return <span className={`inline-block rounded px-2 py-1 text-xs font-medium ${color}`}>{statusLabel(status)}</span>
}

function ApplicationEditor({ application, onClose, onSaved }: {
  application: Application
  onClose: () => void
  onSaved: () => void
}) {
  const [current, setCurrent] = useState(application)
  const [draft, setDraft] = useState(() => details(application))
  const [statusNote, setStatusNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const dialogRef = useRef<HTMLDialogElement>(null)

  useEffect(() => {
    const dialog = dialogRef.current
    dialog?.showModal()
    return () => dialog?.close()
  }, [])

  function update<Field extends keyof ApplicationDetails>(field: Field, value: ApplicationDetails[Field]) {
    setDraft(previous => ({ ...previous, [field]: value }))
    setMessage(null)
  }

  function updateRound(index: number, values: Partial<InterviewRound>) {
    update('interview_rounds', draft.interview_rounds.map((round, roundIndex) => roundIndex === index ? { ...round, ...values } : round))
  }

  async function save(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      const saved = await api.applications.update(current.job_id, draft)
      setCurrent(saved)
      setDraft(details(saved))
      setMessage('Details saved.')
      onSaved()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not save application')
    } finally {
      setBusy(false)
    }
  }

  async function changeStatus(status: ApplicationStatus) {
    setBusy(true)
    setError(null)
    try {
      const saved = await api.applications.updateStatus(current.job_id, status, current.status, statusNote)
      setCurrent(saved)
      setDraft(previous => ({ ...previous, applied_at: previous.applied_at || saved.applied_at }))
      setStatusNote('')
      setMessage(`Moved to ${statusLabel(status)}.`)
      onSaved()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not update status')
      const latest = await api.applications.get(current.job_id).catch(() => null)
      if (latest) setCurrent(latest)
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog ref={dialogRef} onCancel={event => { event.preventDefault(); if (!busy) onClose() }} aria-labelledby="application-title"
      className="w-[min(760px,calc(100vw-2rem))] max-h-[90vh] overflow-y-auto rounded-2xl bg-white p-6 shadow-xl backdrop:bg-slate-900/40">
      <div className="flex justify-between items-start gap-4 mb-5">
        <div>
          <h2 id="application-title" className="text-xl font-semibold">{current.job.title}</h2>
          <p className="text-sm text-slate-500">{current.job.company} · {current.job.location || 'Location unspecified'}</p>
          <a href={current.job.url} target="_blank" rel="noopener noreferrer" className="text-sm text-brand-600">View job ↗</a>
        </div>
        <button type="button" disabled={busy} onClick={onClose} className="px-3 py-1 border rounded-lg disabled:opacity-50" aria-label="Close application">Close</button>
      </div>

      {error && <p role="alert" className="mb-4 rounded-lg bg-red-50 p-3 text-sm text-red-700">{error}</p>}
      {message && <p role="status" className="mb-4 text-sm text-green-700">{message}</p>}

      <section className="rounded-xl border bg-slate-50 p-4 mb-5 space-y-3" aria-labelledby="stage-title">
        <div className="flex items-center justify-between gap-3">
          <h3 id="stage-title" className="font-semibold text-sm">Application stage</h3>
          <StatusBadge status={current.status} />
        </div>
        {current.allowed_transitions.length > 0 ? <>
          <label className="block text-sm">Timeline note (optional)
            <input className="input mt-1" value={statusNote} maxLength={2000} disabled={busy} onChange={event => setStatusNote(event.target.value)} placeholder="Recruiter invited me to a technical interview" />
          </label>
          <label className="block text-sm">Move to
            <select className="input mt-1" value="" disabled={busy} onChange={event => { if (event.target.value) void changeStatus(event.target.value as ApplicationStatus) }}>
              <option value="">Choose next stage…</option>
              {current.allowed_transitions.map(status => <option key={status} value={status}>{statusLabel(status)}</option>)}
            </select>
          </label>
        </> : <p className="text-sm text-slate-500">This application is closed. You can still update its notes and outcomes.</p>}
        <p className="text-xs text-slate-500">Documents: {statusLabel(current.document_status)}. Document generation does not change a submitted application’s stage.</p>
        {current.document_error && <p className="text-xs text-red-600">{current.document_error}</p>}
        <div className="flex flex-wrap gap-3 text-xs text-brand-700">
          {current.one_pager_path && <a href={api.applications.downloadOnePager(current.job_id)}>Download resume</a>}
          {current.cover_letter_path && <a href={api.applications.downloadCoverLetter(current.job_id)}>Download cover letter</a>}
        </div>
      </section>

      <form onSubmit={save} className="space-y-6">
        <fieldset disabled={busy} className="space-y-6 disabled:opacity-60">
          <section className="space-y-3">
            <h3 className="font-semibold">Dates and reminders</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="text-sm">Application date
                <input type="datetime-local" className="input mt-1" value={toLocalInput(draft.applied_at)} onChange={event => update('applied_at', fromLocalInput(event.target.value))} />
              </label>
              <label className="text-sm">Application deadline
                <input type="datetime-local" className="input mt-1" value={toLocalInput(draft.deadline_at)} onChange={event => update('deadline_at', fromLocalInput(event.target.value))} />
              </label>
              <label className="text-sm">Follow-up reminder
                <input type="datetime-local" className="input mt-1" value={toLocalInput(draft.follow_up_at)} onChange={event => {
                  update('follow_up_at', fromLocalInput(event.target.value))
                  update('follow_up_completed_at', null)
                }} />
              </label>
              <label className="text-sm flex items-center gap-2 pt-5">
                <input type="checkbox" checked={Boolean(draft.follow_up_completed_at)} disabled={!draft.follow_up_at}
                  onChange={event => update('follow_up_completed_at', event.target.checked ? new Date().toISOString() : null)} />
                Follow-up completed
              </label>
            </div>
            <p className="text-xs text-slate-500">Dates use your local timezone. Due reminders appear on this page; email and push notifications are not enabled.</p>
          </section>

          <section className="space-y-3">
            <h3 className="font-semibold">Recruiter / contact</h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <label className="text-sm">Name<input className="input mt-1" maxLength={200} value={draft.recruiter_name || ''} onChange={event => update('recruiter_name', event.target.value || null)} /></label>
              <label className="text-sm">Email<input type="email" className="input mt-1" maxLength={320} value={draft.recruiter_email || ''} onChange={event => update('recruiter_email', event.target.value || null)} /></label>
              <label className="text-sm">Phone<input type="tel" className="input mt-1" maxLength={100} value={draft.recruiter_phone || ''} onChange={event => update('recruiter_phone', event.target.value || null)} /></label>
            </div>
          </section>

          <label className="block text-sm font-medium">Application notes
            <textarea className="input mt-1" rows={3} maxLength={20000} value={draft.notes || ''} onChange={event => update('notes', event.target.value || null)} />
          </label>
          <label className="block text-sm font-medium">Preparation notes
            <textarea className="input mt-1" rows={3} maxLength={20000} value={draft.preparation_notes || ''} onChange={event => update('preparation_notes', event.target.value || null)} />
          </label>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold">Interview rounds</h3>
              <button type="button" disabled={draft.interview_rounds.length >= 100} className="text-sm text-brand-700" onClick={() => update('interview_rounds', [...draft.interview_rounds, {
                id: crypto.randomUUID(), round: Math.min(100, Math.max(0, ...draft.interview_rounds.map(round => round.round)) + 1),
                type: 'Technical', date: null, interviewer: null, preparation_notes: null, notes: null, outcome: null,
              }])}>+ Add round</button>
            </div>
            {draft.interview_rounds.length === 0 && <p className="text-sm text-slate-500">No interviews recorded yet.</p>}
            {draft.interview_rounds.map((round, index) => <div key={round.id} className="rounded-xl border p-4 space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm font-semibold">Round {round.round}</span>
                <button type="button" className="text-xs text-red-600" onClick={() => update('interview_rounds', draft.interview_rounds.filter(entry => entry.id !== round.id))}>Remove round {round.round}</button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <label className="text-sm">Round number<input type="number" required min={1} max={100} className="input mt-1" value={round.round} onChange={event => updateRound(index, { round: Number(event.target.value) })} /></label>
                <label className="text-sm">Interview type<input required maxLength={150} className="input mt-1" value={round.type} onChange={event => updateRound(index, { type: event.target.value })} /></label>
                <label className="text-sm">Date and time<input type="datetime-local" className="input mt-1" value={toLocalInput(round.date)} onChange={event => updateRound(index, { date: fromLocalInput(event.target.value) })} /></label>
                <label className="text-sm">Interviewer<input maxLength={200} className="input mt-1" value={round.interviewer || ''} onChange={event => updateRound(index, { interviewer: event.target.value || null })} /></label>
              </div>
              <label className="block text-sm">Preparation<textarea className="input mt-1" rows={2} maxLength={20000} value={round.preparation_notes || ''} onChange={event => updateRound(index, { preparation_notes: event.target.value || null })} /></label>
              <label className="block text-sm">Interview notes<textarea className="input mt-1" rows={2} maxLength={20000} value={round.notes || ''} onChange={event => updateRound(index, { notes: event.target.value || null })} /></label>
              <label className="block text-sm">Round outcome<input className="input mt-1" maxLength={2000} value={round.outcome || ''} onChange={event => updateRound(index, { outcome: event.target.value || null })} /></label>
            </div>)}
          </section>

          <label className="block text-sm font-medium">Application outcome
            <textarea className="input mt-1" rows={3} maxLength={10000} placeholder="Offer details, decision, rejection feedback, or withdrawal reason" value={draft.outcome || ''} onChange={event => update('outcome', event.target.value || null)} />
          </label>
          <button type="submit" className="rounded-lg bg-brand-600 px-4 py-2 text-sm font-medium text-white">{busy ? 'Saving…' : 'Save details'}</button>
        </fieldset>
      </form>

      <section className="mt-6 border-t pt-5" aria-labelledby="timeline-title">
        <h3 id="timeline-title" className="font-semibold mb-3">Status timeline</h3>
        <ol className="border-l-2 border-brand-100 pl-4 space-y-4">
          {(current.status_history || []).map((entry, index) => <li key={`${entry.changed_at}-${index}`} className="text-sm">
            <p className="font-medium">{entry.from_status ? `${statusLabel(entry.from_status)} → ` : ''}{statusLabel(entry.to_status)}</p>
            <p className="text-xs text-slate-500">{formatDate(entry.changed_at)}</p>
            {entry.note && <p className="text-slate-600 mt-1 whitespace-pre-wrap">{entry.note}</p>}
          </li>)}
        </ol>
      </section>
    </dialog>
  )
}

export default function ApplicationsPage() {
  const { data, error, isLoading, mutate } = useSWR('applications', api.applications.list, { refreshInterval: 15_000 })
  const [view, setView] = useState<'board' | 'table'>('board')
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')
  const [dueOnly, setDueOnly] = useState(false)
  const [selected, setSelected] = useState<Application | null>(null)
  const applications = data?.applications || []
  const due = applications.filter(reminderDue)
  const filtered = applications.filter(application => (
    `${application.job.title} ${application.job.company} ${application.recruiter_name || ''}`.toLowerCase().includes(query.toLowerCase())
    && (statusFilter === 'all' || application.status === statusFilter)
    && (!dueOnly || reminderDue(application))
  ))

  return (
    <div className="max-w-6xl mx-auto space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div><h1 className="text-2xl font-bold">Applications</h1><p className="text-sm text-slate-500">{applications.length} tracked · from saved jobs to your next offer</p></div>
        <div className="flex gap-1 rounded-lg bg-slate-100 p-1" aria-label="Application view">
          {(['board', 'table'] as const).map(mode => <button key={mode} aria-pressed={view === mode} onClick={() => setView(mode)} className={`rounded px-4 py-1.5 text-sm capitalize ${view === mode ? 'bg-white shadow-sm' : 'text-slate-500'}`}>{mode}</button>)}
        </div>
      </div>
      {error && <p role="alert" className="rounded-lg bg-red-50 p-3 text-sm text-red-700">Could not load applications. {error.message} <button onClick={() => void mutate()} className="underline">Retry</button></p>}
      {due.length > 0 && <div className="rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800" role="status">
        {due.length} follow-up reminder{due.length === 1 ? '' : 's'} due. <button className="underline font-medium" onClick={() => { setDueOnly(true); setStatusFilter('all'); setQuery('') }}>Show due follow-ups</button>
      </div>}
      <div className="flex flex-wrap items-center gap-3">
        <input aria-label="Search applications" placeholder="Search roles, companies, contacts…" className="input sm:max-w-xs" value={query} onChange={event => setQuery(event.target.value)} />
        <select aria-label="Filter by application stage" className="input sm:w-auto" value={statusFilter} onChange={event => setStatusFilter(event.target.value)}>
          <option value="all">All stages</option>{APPLICATION_STATUSES.map(status => <option key={status} value={status}>{statusLabel(status)}</option>)}
        </select>
        <label className="text-sm flex items-center gap-2"><input type="checkbox" checked={dueOnly} onChange={event => setDueOnly(event.target.checked)} />Due follow-ups only</label>
      </div>

      {isLoading ? <p role="status" className="py-16 text-center text-slate-500">Loading applications…</p>
        : !error && applications.length === 0 ? <div className="rounded-xl border bg-white p-12 text-center space-y-3">
          <h2 className="font-semibold">Your next opportunity starts here</h2><p className="text-sm text-slate-500">Save a job or mark it applied to start tracking contacts, interviews, and follow-ups.</p>
          <Link href="/jobs" className="inline-block rounded-lg bg-brand-600 px-4 py-2 text-sm text-white">Browse jobs</Link>
        </div> : filtered.length === 0 ? <p className="py-16 text-center text-slate-500">No applications match these filters.</p>
          : view === 'board' ? <div className="overflow-x-auto pb-4" aria-label="Applications board">
            <div className="flex gap-4 items-start">
              {APPLICATION_STATUSES.filter(status => statusFilter === 'all' || status === statusFilter).map(status => {
                const entries = filtered.filter(application => application.status === status)
                return <section key={status} className="w-64 shrink-0 rounded-xl bg-slate-100 p-3" aria-label={`${statusLabel(status)} applications`}>
                  <h2 className="flex justify-between text-sm font-semibold mb-3">{statusLabel(status)}<span className="text-slate-500">{entries.length}</span></h2>
                  <div className="space-y-3">
                    {entries.map(application => <button key={application.id} onClick={() => setSelected(application)} className="w-full rounded-lg border bg-white p-4 text-left shadow-sm hover:border-brand-300 focus-visible:ring-2 focus-visible:ring-brand-500">
                      <h3 className="text-sm font-semibold">{application.job.title}</h3>
                      <p className="text-xs text-slate-500 mt-1">{application.job.company}</p>
                      {application.recruiter_name && <p className="text-xs mt-2">Contact: {application.recruiter_name}</p>}
                      {application.deadline_at && <p className="text-xs text-slate-500 mt-2">Deadline: {formatDate(application.deadline_at)}</p>}
                      {application.follow_up_at && <p className={`text-xs mt-2 ${reminderDue(application) ? 'text-amber-700 font-medium' : 'text-slate-500'}`}>
                        {application.follow_up_completed_at ? '✓ Follow-up completed' : `${reminderDue(application) ? 'Due · ' : ''}Follow up: ${formatDate(application.follow_up_at)}`}
                      </p>}
                      {application.applied_at && <p className="text-xs text-slate-500 mt-2">Applied: {formatDate(application.applied_at)}</p>}
                    </button>)}
                    {entries.length === 0 && <p className="text-xs text-slate-400 py-5 text-center">No applications</p>}
                  </div>
                </section>
              })}
            </div>
          </div> : <div className="overflow-x-auto rounded-xl border bg-white">
            <table className="w-full text-left text-sm">
              <caption className="sr-only">Tracked applications. Open a role to edit its details and status.</caption>
              <thead className="bg-slate-50 text-slate-500"><tr>{['Role / company', 'Stage', 'Applied', 'Contact', 'Deadline', 'Follow-up'].map(heading => <th key={heading} scope="col" className="p-3 whitespace-nowrap font-medium">{heading}</th>)}</tr></thead>
              <tbody>{filtered.map(application => <tr key={application.id} className="border-t">
                <td className="p-3 min-w-48"><button className="text-left text-brand-700 hover:underline" onClick={() => setSelected(application)}>{application.job.title}</button><p className="text-xs text-slate-500">{application.job.company}</p></td>
                <td className="p-3"><StatusBadge status={application.status} /></td>
                <td className="p-3 whitespace-nowrap text-xs">{formatDate(application.applied_at)}</td>
                <td className="p-3 text-xs">{application.recruiter_name || '—'}</td>
                <td className="p-3 whitespace-nowrap text-xs">{formatDate(application.deadline_at)}</td>
                <td className={`p-3 whitespace-nowrap text-xs ${reminderDue(application) ? 'text-amber-700 font-medium' : ''}`}>{application.follow_up_completed_at ? 'Completed' : formatDate(application.follow_up_at)}</td>
              </tr>)}</tbody>
            </table>
          </div>}
      {selected && <ApplicationEditor key={selected.id} application={selected} onClose={() => setSelected(null)} onSaved={() => { void mutate() }} />}
    </div>
  )
}
