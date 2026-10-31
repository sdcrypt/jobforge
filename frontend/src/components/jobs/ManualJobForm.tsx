'use client'

import { FormEvent, useState } from 'react'
import { api, ManualJobInput } from '@/lib/api'

export default function ManualJobForm({ onImported, onClose }: { onImported: () => void; onClose: () => void }) {
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const fields = new FormData(event.currentTarget)
    const value = (name: string) => String(fields.get(name) || '').trim()
    const data: ManualJobInput = { title: value('title'), company: value('company'), remote: fields.has('remote') }
    for (const field of ['url', 'description', 'location'] as const) {
      if (value(field)) data[field] = value(field)
    }
    if (!data.url && !data.description) { setError('Provide a listing URL or paste the description.'); return }
    if (value('posted_at')) data.posted_at = `${value('posted_at')}T00:00:00Z`
    for (const field of ['salary_min', 'salary_max'] as const) {
      if (value(field)) data[field] = Number(value(field))
    }
    if (data.salary_min !== undefined || data.salary_max !== undefined) {
      data.salary_currency = value('salary_currency')
      data.salary_period = value('salary_period')
    }
    setSaving(true)
    setError(null)
    try {
      await api.jobs.import(data)
      onImported()
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not import job.')
    } finally {
      setSaving(false)
    }
  }

  return <section aria-labelledby="import-heading" className="mb-6 rounded-xl border bg-white p-5">
    <div className="flex justify-between gap-3"><h2 id="import-heading" className="font-semibold">Add job manually</h2><button type="button" disabled={saving} onClick={onClose} className="text-sm text-slate-500">Close</button></div>
    <p className="my-3 text-sm text-slate-500">Paste a listing URL or description from any source. URLs are saved as references, not automatically fetched. Paste the requirements for meaningful AI analysis. Importing does not mark a job as applied.</p>
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">Job title<input className="input mt-1" name="title" required maxLength={255} /></label>
        <label className="text-sm">Company<input className="input mt-1" name="company" required maxLength={255} /></label>
      </div>
      <label className="block text-sm">Listing URL<input className="input mt-1" name="url" type="url" maxLength={1024} placeholder="https://…" /></label>
      <label className="block text-sm">Job description<textarea className="input mt-1 min-h-40" name="description" maxLength={50000} placeholder="Paste responsibilities, requirements, and benefits…" /></label>
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">Location<input className="input mt-1" name="location" maxLength={255} /></label>
        <label className="text-sm">Posted date (if known)<input className="input mt-1" type="date" name="posted_at" /></label>
        <label className="text-sm">Minimum salary<input className="input mt-1" type="number" min="0" step="any" name="salary_min" /></label>
        <label className="text-sm">Maximum salary<input className="input mt-1" type="number" min="0" step="any" name="salary_max" /></label>
        <label className="text-sm">Currency<input className="input mt-1" name="salary_currency" defaultValue="USD" pattern="[A-Za-z]{3}" maxLength={3} /></label>
        <label className="text-sm">Pay period<select className="input mt-1" name="salary_period"><option value="year">Year</option><option value="month">Month</option><option value="hour">Hour</option></select></label>
      </div>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="remote" /> Remote job</label>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
      <button disabled={saving} className="rounded-lg bg-brand-600 px-4 py-2 text-sm text-white disabled:opacity-50">{saving ? 'Adding…' : 'Add job'}</button>
    </form>
  </section>
}
