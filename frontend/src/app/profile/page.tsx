'use client'

import { useState, useEffect, FormEvent } from 'react'
import { api, UserProfile } from '@/lib/api'

type SkillEntry = { name: string; level: string }
type ExpEntry   = { company: string; role: string; start: string; end: string; highlights: string[] }
type EduEntry   = { institution: string; degree: string; year: number }

const BLANK_PROFILE = {
  full_name: '',
  email: '',
  phone: '',
  location: '',
  linkedin_url: '',
  headline: '',
  summary: '',
  target_roles: [] as string[],
  remote_preference: 'hybrid',
  salary_min: 0,
  salary_max: 0,
  skills: [] as SkillEntry[],
  experience: [] as ExpEntry[],
  education: [] as EduEntry[],
}

export default function ProfilePage() {
  const [form, setForm] = useState(BLANK_PROFILE)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  // ── Load existing profile ──────────────────────────────────────────────────
  useEffect(() => {
    api.profile.get()
      .then((p: UserProfile) => {
        setForm({
          full_name:         p.full_name        ?? '',
          email:             p.email            ?? '',
          phone:             p.phone            ?? '',
          location:          p.location         ?? '',
          linkedin_url:      p.linkedin_url     ?? '',
          headline:          p.headline         ?? '',
          summary:           p.summary          ?? '',
          target_roles:      p.target_roles     ?? [],
          remote_preference: p.remote_preference ?? 'hybrid',
          salary_min:        p.salary_min       ?? 0,
          salary_max:        p.salary_max       ?? 0,
          skills:            p.skills           ?? [],
          experience:        p.experience       ?? [],
          education:         p.education        ?? [],
        })
      })
      .catch(() => { /* first run — no profile yet */ })
      .finally(() => setLoading(false))
  }, [])

  // ── Save ──────────────────────────────────────────────────────────────────
  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setMsg(null)
    try {
      await api.profile.save(form)
      setMsg({ ok: true, text: 'Profile saved ✓' })
    } catch (err: unknown) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : 'Save failed' })
    } finally {
      setSaving(false)
    }
  }

  // ── Skills helpers ─────────────────────────────────────────────────────────
  function addSkill()  { setForm((f) => ({ ...f, skills: [...f.skills, { name: '', level: 'intermediate' }] })) }
  function removeSkill(i: number) { setForm((f) => ({ ...f, skills: f.skills.filter((_, idx) => idx !== i) })) }
  function updateSkill(i: number, field: keyof SkillEntry, val: string) {
    setForm((f) => {
      const skills = [...f.skills]
      skills[i] = { ...skills[i], [field]: val }
      return { ...f, skills }
    })
  }

  if (loading) {
    return (
      <div className="max-w-2xl mx-auto animate-pulse space-y-4 pt-10">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-10 bg-slate-100 rounded-lg" />
        ))}
      </div>
    )
  }

  return (
    <div className="max-w-2xl mx-auto">
      <h1 className="text-2xl font-bold text-slate-900 mb-1">My Profile</h1>
      <p className="text-slate-500 text-sm mb-6">
        This profile is used by the Rank and DocGen agents to score jobs and create tailored documents.
      </p>

      <form onSubmit={handleSubmit} className="space-y-8">

        {/* ── Personal ─────────────────────────────────────────────────── */}
        <section className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
          <h2 className="font-semibold text-slate-700">Personal Info</h2>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Full Name" required>
              <input className="input" value={form.full_name}
                onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} />
            </Field>
            <Field label="Email" required>
              <input type="email" className="input" value={form.email}
                onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))} />
            </Field>
            <Field label="Phone">
              <input className="input" value={form.phone}
                onChange={(e) => setForm((f) => ({ ...f, phone: e.target.value }))} />
            </Field>
            <Field label="Location">
              <input className="input" placeholder="City, Country" value={form.location}
                onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))} />
            </Field>
            <Field label="LinkedIn URL" className="col-span-2">
              <input className="input" placeholder="https://linkedin.com/in/…" value={form.linkedin_url}
                onChange={(e) => setForm((f) => ({ ...f, linkedin_url: e.target.value }))} />
            </Field>
            <Field label="Headline" className="col-span-2">
              <input className="input" placeholder="Senior Software Engineer · Full-Stack · 8 yrs" value={form.headline}
                onChange={(e) => setForm((f) => ({ ...f, headline: e.target.value }))} />
            </Field>
            <Field label="Summary" className="col-span-2">
              <textarea rows={3} className="input resize-none" value={form.summary}
                onChange={(e) => setForm((f) => ({ ...f, summary: e.target.value }))} />
            </Field>
          </div>
        </section>

        {/* ── Job Preferences ──────────────────────────────────────────── */}
        <section className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
          <h2 className="font-semibold text-slate-700">Job Preferences</h2>
          <div className="grid grid-cols-2 gap-4">
            <Field label="Target Roles (comma separated)" className="col-span-2">
              <input className="input" placeholder="Senior Engineer, Tech Lead"
                value={form.target_roles.join(', ')}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    target_roles: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                  }))
                }
              />
            </Field>
            <Field label="Remote Preference">
              <select className="input"
                value={form.remote_preference}
                onChange={(e) => setForm((f) => ({ ...f, remote_preference: e.target.value }))}>
                <option value="remote">Remote only</option>
                <option value="hybrid">Hybrid</option>
                <option value="onsite">On-site</option>
              </select>
            </Field>
            <Field label="Salary Min (USD)">
              <input type="number" className="input" value={form.salary_min}
                onChange={(e) => setForm((f) => ({ ...f, salary_min: Number(e.target.value) }))} />
            </Field>
            <Field label="Salary Max (USD)">
              <input type="number" className="input" value={form.salary_max}
                onChange={(e) => setForm((f) => ({ ...f, salary_max: Number(e.target.value) }))} />
            </Field>
          </div>
        </section>

        {/* ── Skills ──────────────────────────────────────────────────── */}
        <section className="bg-white rounded-xl border border-slate-200 p-5 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold text-slate-700">Skills</h2>
            <button type="button" onClick={addSkill}
              className="text-xs text-brand-600 hover:underline">+ Add skill</button>
          </div>
          {form.skills.length === 0 && (
            <p className="text-slate-400 text-sm">No skills yet. Add at least 3 for best ranking results.</p>
          )}
          {form.skills.map((sk, i) => (
            <div key={i} className="flex gap-2 items-center">
              <input className="input flex-1" placeholder="e.g. Python"
                value={sk.name}
                onChange={(e) => updateSkill(i, 'name', e.target.value)} />
              <select className="input w-36"
                value={sk.level}
                onChange={(e) => updateSkill(i, 'level', e.target.value)}>
                <option value="beginner">Beginner</option>
                <option value="intermediate">Intermediate</option>
                <option value="expert">Expert</option>
              </select>
              <button type="button" onClick={() => removeSkill(i)}
                className="text-slate-400 hover:text-red-500 text-lg leading-none">×</button>
            </div>
          ))}
        </section>

        {/* ── Save ─────────────────────────────────────────────────────── */}
        {msg && (
          <div className={`px-4 py-2 rounded-lg text-sm ${msg.ok
            ? 'bg-green-50 border border-green-200 text-green-700'
            : 'bg-red-50 border border-red-200 text-red-700'}`}>
            {msg.text}
          </div>
        )}

        <button
          type="submit"
          disabled={saving}
          className="w-full py-2.5 bg-brand-600 text-white rounded-lg font-medium hover:bg-brand-700 disabled:opacity-60 transition-colors"
        >
          {saving ? 'Saving…' : 'Save Profile'}
        </button>
      </form>
    </div>
  )
}

// ── Small helper ──────────────────────────────────────────────────────────────
function Field({
  label,
  required,
  className,
  children,
}: {
  label: string
  required?: boolean
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={className}>
      <label className="block text-xs font-medium text-slate-600 mb-1">
        {label}{required && <span className="text-red-400 ml-0.5">*</span>}
      </label>
      {children}
    </div>
  )
}
