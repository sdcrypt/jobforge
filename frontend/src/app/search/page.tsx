'use client'

import { useState, useEffect, FormEvent } from 'react'
import { api, SearchConfig } from '@/lib/api'

const PORTALS: { id: string; label: string; note: string }[] = [
  { id: 'linkedin',       label: '🔗 LinkedIn',         note: 'Public guest API — works well' },
  { id: 'remoteok',       label: '🌍 RemoteOK',          note: 'Free JSON API — remote tech jobs with salary' },
  { id: 'weworkremotely', label: '🏠 We Work Remotely',  note: 'RSS feed — senior remote roles' },
  { id: 'hackernews',     label: '🟠 HackerNews Hiring', note: 'Monthly thread — startup & founding roles' },
]
const SUPPORTED_PORTAL_IDS = new Set(PORTALS.map((p) => p.id))

const BLANK: Partial<SearchConfig> = {
  keywords: [],
  locations: [],
  portals: ['linkedin', 'remoteok', 'weworkremotely', 'hackernews'],
  remote_only: false,
  posted_within_days: 7,
  run_every_hours: 12,
  max_results_per_search: 15,
  linkedin_pages: 1,
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
        setForm({
          ...c,
          portals: (c.portals ?? []).filter((portal) => SUPPORTED_PORTAL_IDS.has(portal)),
        })
        setKeywordsRaw(c.keywords?.join(', ') ?? '')
        setLocationsRaw(c.locations?.join(', ') ?? '')
      })
      .catch(() => { /* no config yet */ })
      .finally(() => setLoading(false))
  }, [])

  function parseList(raw: string) {
    return raw.split(',').map((s) => s.trim()).filter(Boolean)
  }

  function buildPayload() {
    return {
      ...form,
      keywords: parseList(keywordsRaw),
      locations: parseList(locationsRaw),
      portals: (form.portals ?? []).filter((portal) => SUPPORTED_PORTAL_IDS.has(portal)),
    }
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setMsg(null)
    try {
      await api.searchConfig.save(buildPayload())
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
      await api.searchConfig.save(buildPayload())
      const res = await api.pipeline.run()
      setMsg({ ok: true, text: 'Search config saved and pipeline started — check Jobs page for results' })
    } catch (err: unknown) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : 'Pipeline failed' })
    } finally {
      setRunning(false)
    }
  }

  function togglePortal(portalId: string) {
    setForm((f) => {
      const current = f.portals ?? []
      const next = current.includes(portalId)
        ? current.filter((p) => p !== portalId)
        : [...current, portalId]
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
          <div className="grid grid-cols-2 gap-2">
            {PORTALS.map(({ id, label, note }) => {
              const active = form.portals?.includes(id)
              return (
                <button
                  key={id}
                  type="button"
                  onClick={() => togglePortal(id)}
                  className={`text-left px-3 py-2.5 rounded-lg border transition-colors ${
                    active
                      ? 'bg-brand-600 border-brand-600 text-white'
                      : 'border-slate-200 text-slate-700 hover:border-slate-400 bg-white'
                  }`}
                >
                  <div className="text-sm font-medium">{label}</div>
                  {note && (
                    <div className={`text-xs mt-0.5 ${active ? 'text-blue-200' : 'text-slate-400'}`}>
                      {note}
                    </div>
                  )}
                </button>
              )
            })}
          </div>
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

        {/* Search Depth */}
        <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
          <div>
            <h2 className="font-semibold text-slate-700">Search Depth</h2>
            <p className="text-xs text-slate-400 mt-0.5">
              More results = more jobs found, but slower pipeline runs and slightly higher block risk on LinkedIn.
            </p>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                Results per search
                <span className="text-slate-400 font-normal"> (per keyword × location × portal)</span>
              </label>
              <input
                type="number"
                className="input"
                min={5}
                max={100}
                step={5}
                value={form.max_results_per_search ?? 15}
                onChange={(e) => setForm((f) => ({ ...f, max_results_per_search: Number(e.target.value) }))}
              />
              <p className="text-xs text-slate-400 mt-1">Default 15 · safe up to ~50</p>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">
                LinkedIn pages
                <span className="text-slate-400 font-normal"> (each page ≈ 25 more jobs)</span>
              </label>
              <input
                type="number"
                className="input"
                min={1}
                max={4}
                value={form.linkedin_pages ?? 1}
                onChange={(e) => setForm((f) => ({ ...f, linkedin_pages: Number(e.target.value) }))}
              />
              <p className="text-xs text-slate-400 mt-1">Default 1 · max 4 before LinkedIn may block</p>
            </div>
          </div>
          {/* Depth summary */}
          {(() => {
            const results = form.max_results_per_search ?? 15
            const pages = form.linkedin_pages ?? 1
            const kw = 1  // placeholder — actual keywords count not known here
            const liMax = pages * 25
            return (
              <p className="text-xs text-slate-500 bg-slate-50 rounded-lg px-3 py-2">
                LinkedIn: up to <strong>{liMax}</strong> results per keyword+location
                ({pages} page{pages !== 1 ? 's' : ''} × 25) ·
                Other portals: up to <strong>{results}</strong> results each
              </p>
            )
          })()}
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
