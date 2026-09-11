'use client'

import { useState, useEffect, FormEvent } from 'react'
import { api, SearchConfig } from '@/lib/api'

const PORTALS = ['linkedin', 'indeed', 'mock']

const BLANK: Partial<SearchConfig> = {
  keywords: [],
  locations: [],
  portals: ['linkedin', 'indeed', 'mock'],
  remote_only: false,
  posted_within_days: 7,
  run_every_hours: 12,
}

export default function SearchPage() {
  const [form, setForm] = useState(BLANK)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [running, setRunning] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  // Raw string state for comma-separated fields
  const [keywordsRaw, setKeywordsRaw] = useState('')
  const [locationsRaw, setLocationsRaw] = useState('')

  useEffect(() => {
    api.searchConfig.get()
      .then((c: SearchConfig) => {
        setForm(c)
        setKeywordsRaw(c.keywords?.join(', ') ?? '')
        setLocationsRaw(c.locations?.join(', ') ?? '')
      })
      .catch(() => { /* no config yet */ })
      .finally(() => setLoading(false))
  }, [])

  function parseList(raw: string) {
    return raw.split(',').map((s) => s.trim()).filter(Boolean)
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setMsg(null)
    try {
      const payload = {
        ...form,
        keywords:  parseList(keywordsRaw),
        locations: parseList(locationsRaw),
      }
      await api.searchConfig.save(payload)
      setMsg({ ok: true, text: 'Search config saved ✓' })
    } catch (err: unknown) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : 'Save failed' })
    } finally {
      setSaving(false)
    }
  }

  async function handleRunPipeline() {
    setRunning(true)
    setMsg(null)
    try {
      const res = await api.pipeline.run()
      setMsg({ ok: true, text: res.message + ' — check Jobs page for results' })
    } catch (err: unknown) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : 'Pipeline failed' })
    } finally {
      setRunning(false)
    }
  }

  function togglePortal(portal: string) {
    setForm((f) => {
      const current = f.portals ?? []
      const next = current.includes(portal)
        ? current.filter((p) => p !== portal)
        : [...current, portal]
      return { ...f, portals: next }
    })
  }

  if (loading) {
    return (
      <div className="max-w-xl mx-auto animate-pulse space-y-4 pt-10">
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="h-10 bg-slate-100 rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <div className="max-w-xl mx-auto">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">Search Config</h1>
      <p className="text-slate-500 text-sm mb-6">
        Configure what the Search Agent looks for. Save, then run the pipeline.
      </p>

      <form onSubmit={handleSave} className="space-y-6">

        {/* Keywords */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
          <h2 className="font-semibold text-slate-700">Search Terms</h2>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Keywords <span className="text-slate-400">(comma separated)</span>
            </label>
            <input
              className="input"
              placeholder="Senior Software Engineer, Backend Engineer, Tech Lead"
              value={keywordsRaw}
              onChange={(e) => setKeywordsRaw(e.target.value)}
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">
              Locations <span className="text-slate-400">(comma separated)</span>
            </label>
            <input
              className="input"
              placeholder="London, Remote, Singapore"
              value={locationsRaw}
              onChange={(e) => setLocationsRaw(e.target.value)}
            />
          </div>
        </div>

        {/* Portals */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
          <h2 className="font-semibold text-slate-700">Job Portals</h2>
          <div className="flex gap-3 flex-wrap">
            {PORTALS.map((portal) => {
              const active = form.portals?.includes(portal)
              return (
                <button
                  key={portal}
                  type="button"
                  onClick={() => togglePortal(portal)}
                  className={`px-4 py-2 rounded-lg text-sm capitalize font-medium border transition-colors ${
                    active
                      ? 'bg-brand-600 border-brand-600 text-white'
                      : 'border-slate-200 text-slate-600 hover:border-slate-400'
                  }`}
                >
                  {portal === 'linkedin' ? '🔗 LinkedIn' :
                   portal === 'indeed'   ? '🔍 Indeed' :
                   '🤖 Mock (test)'}
                </button>
              )
            })}
          </div>
          <p className="text-xs text-slate-400">
            Mock generates fake jobs — useful for testing without internet / LLM.
          </p>
        </div>

        {/* Options */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
          <h2 className="font-semibold text-slate-700">Options</h2>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Posted within (days)
              </label>
              <input
                type="number"
                className="input"
                min={1}
                max={30}
                value={form.posted_within_days ?? 7}
                onChange={(e) => setForm((f) => ({ ...f, posted_within_days: Number(e.target.value) }))}
              />
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Auto-run every (hours)
              </label>
              <input
                type="number"
                className="input"
                min={1}
                max={72}
                value={form.run_every_hours ?? 12}
                onChange={(e) => setForm((f) => ({ ...f, run_every_hours: Number(e.target.value) }))}
              />
            </div>
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700 cursor-pointer">
            <input
              type="checkbox"
              checked={form.remote_only ?? false}
              onChange={(e) => setForm((f) => ({ ...f, remote_only: e.target.checked }))}
              className="rounded"
            />
            Remote jobs only
          </label>
        </div>

        {/* Last run info */}
        {(form as SearchConfig).last_run_at && (
          <p className="text-xs text-slate-500">
            Last pipeline run: {new Date((form as SearchConfig).last_run_at!).toLocaleString()}
            {' · '}{(form as SearchConfig).last_run_found} jobs found
          </p>
        )}

        {/* Message */}
        {msg && (
          <div className={`px-4 py-2 rounded-lg text-sm ${msg.ok
            ? 'bg-green-50 border border-green-200 text-green-700'
            : 'bg-red-50 border border-red-200 text-red-700'}`}>
            {msg.text}
          </div>
        )}

        {/* Buttons */}
        <div className="flex gap-3">
          <button
            type="submit"
            disabled={saving}
            className="flex-1 py-2.5 bg-white border border-slate-300 text-slate-700 rounded-lg font-medium hover:border-slate-400 disabled:opacity-60 transition-colors"
          >
            {saving ? 'Saving…' : '💾 Save Config'}
          </button>
          <button
            type="button"
            onClick={handleRunPipeline}
            disabled={running}
            className="flex-1 py-2.5 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700 disabled:opacity-60 transition-colors flex items-center justify-center gap-2"
          >
            {running ? (
              <><span className="animate-spin">⚙️</span> Running…</>
            ) : (
              '🚀 Run Now'
            )}
          </button>
        </div>
      </form>
    </div>
  )
}
