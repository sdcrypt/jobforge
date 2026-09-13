'use client'

import { useState, useEffect, useRef, FormEvent, DragEvent } from 'react'
import { api, UserProfile } from '@/lib/api'
import clsx from 'clsx'

// ── Types ─────────────────────────────────────────────────────────────────────
type SkillEntry = { name: string; level: string }
type ExpEntry   = { company: string; role: string; start: string; end: string; highlights: string[] }
type EduEntry   = { institution: string; degree: string; year: number }

type FormState = {
  full_name: string
  email: string
  phone: string
  location: string
  linkedin_url: string
  github_url: string
  portfolio_url: string
  headline: string
  summary: string
  target_roles: string[]
  remote_preference: string
  salary_min: number
  salary_max: number
  skills: SkillEntry[]
  experience: ExpEntry[]
  education: EduEntry[]
}

const BLANK: FormState = {
  full_name: '', email: '', phone: '', location: '',
  linkedin_url: '', github_url: '', portfolio_url: '',
  headline: '', summary: '',
  target_roles: [], remote_preference: 'hybrid',
  salary_min: 0, salary_max: 0,
  skills: [], experience: [], education: [],
}

// ── Main Component ────────────────────────────────────────────────────────────
export default function ProfilePage() {
  const [form, setForm] = useState<FormState>(BLANK)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [targetRolesRaw, setTargetRolesRaw] = useState('')

  // Resume upload state
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState<string | null>(null)
  const [dragOver, setDragOver] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  // ── Load profile on mount ──────────────────────────────────────────────────
  useEffect(() => {
    api.profile.get()
      .then((p: UserProfile) => applyProfile(p))
      .catch(() => { /* no profile yet — start blank */ })
      .finally(() => setLoading(false))
  }, [])

  function applyProfile(p: Partial<UserProfile>) {
    if (p.target_roles) {
      setTargetRolesRaw(p.target_roles.join(', '))
    }

    setForm((prev) => ({
      ...prev,
      full_name:         p.full_name         ?? prev.full_name,
      email:             p.email             ?? prev.email,
      phone:             p.phone             ?? prev.phone ?? '',
      location:          p.location          ?? prev.location ?? '',
      linkedin_url:      p.linkedin_url      ?? prev.linkedin_url ?? '',
      github_url:        (p as any).github_url      ?? prev.github_url ?? '',
      portfolio_url:     (p as any).portfolio_url   ?? prev.portfolio_url ?? '',
      headline:          p.headline          ?? prev.headline ?? '',
      summary:           p.summary           ?? prev.summary ?? '',
      target_roles:      p.target_roles      ?? prev.target_roles,
      remote_preference: p.remote_preference ?? prev.remote_preference,
      salary_min:        p.salary_min        ?? prev.salary_min,
      salary_max:        p.salary_max        ?? prev.salary_max,
      skills:            (p.skills as SkillEntry[])         ?? prev.skills,
      experience:        (p.experience as unknown as ExpEntry[]) ?? prev.experience,
      education:         (p.education as unknown as EduEntry[])  ?? prev.education,
    }))
  }

  // ── Resume upload ──────────────────────────────────────────────────────────
  async function handleFile(file: File) {
    const ext = file.name.split('.').pop()?.toLowerCase()
    if (!['pdf', 'docx'].includes(ext ?? '')) {
      setUploadMsg('⚠ Only PDF and DOCX files are supported.')
      return
    }
    setUploading(true)
    setUploadMsg(null)
    try {
      const { parsed, message } = await api.profile.parseResume(file)
      applyProfile(parsed)
      setUploadMsg(`✓ ${message}`)
    } catch (e: unknown) {
      setUploadMsg(`✗ ${e instanceof Error ? e.message : 'Upload failed'}`)
    } finally {
      setUploading(false)
    }
  }

  function onFileInput(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (file) handleFile(file)
    e.target.value = ''
  }

  function onDrop(e: DragEvent<HTMLDivElement>) {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleFile(file)
  }

  // ── Save profile ──────────────────────────────────────────────────────────
  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setSaving(true)
    setMsg(null)
    try {
      await api.profile.save({
        ...form,
        target_roles: targetRolesRaw.split(',').map((s) => s.trim()).filter(Boolean),
      })
      setMsg({ ok: true, text: 'Profile saved ✓' })
    } catch (err: unknown) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : 'Save failed' })
    } finally {
      setSaving(false)
    }
  }

  // ── Skills helpers ────────────────────────────────────────────────────────
  function addSkill()  { setForm((f) => ({ ...f, skills: [...f.skills, { name: '', level: 'intermediate' }] })) }
  function removeSkill(i: number) { setForm((f) => ({ ...f, skills: f.skills.filter((_, idx) => idx !== i) })) }
  function updateSkill(i: number, field: keyof SkillEntry, val: string) {
    setForm((f) => {
      const skills = [...f.skills]
      skills[i] = { ...skills[i], [field]: val }
      return { ...f, skills }
    })
  }

  // ── Experience helpers ────────────────────────────────────────────────────
  function addExp() {
    setForm((f) => ({
      ...f,
      experience: [...f.experience, { company: '', role: '', start: '', end: 'Present', highlights: [''] }],
    }))
  }
  function removeExp(i: number) { setForm((f) => ({ ...f, experience: f.experience.filter((_, idx) => idx !== i) })) }
  function updateExp(i: number, field: keyof Omit<ExpEntry, 'highlights'>, val: string) {
    setForm((f) => {
      const experience = [...f.experience]
      experience[i] = { ...experience[i], [field]: val }
      return { ...f, experience }
    })
  }
  function updateHighlight(expIdx: number, hIdx: number, val: string) {
    setForm((f) => {
      const experience = [...f.experience]
      const highlights = [...experience[expIdx].highlights]
      highlights[hIdx] = val
      experience[expIdx] = { ...experience[expIdx], highlights }
      return { ...f, experience }
    })
  }
  function addHighlight(expIdx: number) {
    setForm((f) => {
      const experience = [...f.experience]
      experience[expIdx] = { ...experience[expIdx], highlights: [...experience[expIdx].highlights, ''] }
      return { ...f, experience }
    })
  }
  function removeHighlight(expIdx: number, hIdx: number) {
    setForm((f) => {
      const experience = [...f.experience]
      const highlights = experience[expIdx].highlights.filter((_, i) => i !== hIdx)
      experience[expIdx] = { ...experience[expIdx], highlights }
      return { ...f, experience }
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
        Used by the Rank and DocGen agents to score jobs and create tailored documents.
      </p>

      {/* ── Resume Upload ──────────────────────────────────────────── */}
      <div className="mb-6">
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={onDrop}
          onClick={() => !uploading && fileRef.current?.click()}
          className={clsx(
            'relative border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors',
            dragOver
              ? 'border-brand-500 bg-brand-50'
              : 'border-slate-300 bg-white hover:border-brand-400 hover:bg-slate-50'
          )}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx"
            className="hidden"
            onChange={onFileInput}
          />
          {uploading ? (
            <div className="flex flex-col items-center gap-2">
              <div className="text-2xl animate-spin">⚙️</div>
              <p className="text-sm text-slate-600">AI is reading your resume…</p>
              <p className="text-xs text-slate-400">This takes 15–30 seconds</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-2">
              <div className="text-3xl">📄</div>
              <p className="font-medium text-slate-700">Drop your resume here or click to browse</p>
              <p className="text-xs text-slate-400">PDF or DOCX · Max 5 MB</p>
              <p className="text-xs text-brand-600 font-medium">
                AI will auto-fill your entire profile from it
              </p>
            </div>
          )}
        </div>

        {uploadMsg && (
          <p className={clsx(
            'mt-2 text-sm px-3 py-2 rounded-lg',
            uploadMsg.startsWith('✓')
              ? 'bg-green-50 text-green-700 border border-green-200'
              : 'bg-red-50 text-red-600 border border-red-200'
          )}>
            {uploadMsg}
          </p>
        )}
      </div>

      {/* ── Profile Form ───────────────────────────────────────────── */}
      <form onSubmit={handleSubmit} className="space-y-6">

        {/* Personal Info */}
        <Section title="Personal Info">
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
              <input className="input" placeholder="London, UK" value={form.location}
                onChange={(e) => setForm((f) => ({ ...f, location: e.target.value }))} />
            </Field>
            <Field label="LinkedIn URL" className="col-span-2">
              <input className="input" placeholder="https://linkedin.com/in/…" value={form.linkedin_url}
                onChange={(e) => setForm((f) => ({ ...f, linkedin_url: e.target.value }))} />
            </Field>
            <Field label="GitHub URL">
              <input className="input" placeholder="https://github.com/…" value={form.github_url}
                onChange={(e) => setForm((f) => ({ ...f, github_url: e.target.value }))} />
            </Field>
            <Field label="Portfolio / Website">
              <input className="input" placeholder="https://…" value={form.portfolio_url}
                onChange={(e) => setForm((f) => ({ ...f, portfolio_url: e.target.value }))} />
            </Field>
            <Field label="Professional Headline" className="col-span-2">
              <input className="input" placeholder="Senior Software Engineer · Python · 8 yrs" value={form.headline}
                onChange={(e) => setForm((f) => ({ ...f, headline: e.target.value }))} />
            </Field>
            <Field label="Professional Summary" className="col-span-2">
              <textarea rows={3} className="input resize-none" value={form.summary}
                onChange={(e) => setForm((f) => ({ ...f, summary: e.target.value }))} />
            </Field>
          </div>
        </Section>

        {/* Job Preferences */}
        <Section title="Job Preferences">
          <div className="grid grid-cols-2 gap-4">
            <Field label="Target Roles (comma separated)" className="col-span-2">
              <input className="input" placeholder="Senior Engineer, Tech Lead"
                value={targetRolesRaw}
                onChange={(e) => setTargetRolesRaw(e.target.value)}
              />
            </Field>
            <Field label="Remote Preference">
              <select className="input" value={form.remote_preference}
                onChange={(e) => setForm((f) => ({ ...f, remote_preference: e.target.value }))}>
                <option value="remote">Remote only</option>
                <option value="hybrid">Hybrid</option>
                <option value="onsite">On-site</option>
              </select>
            </Field>
            <div /> {/* spacer */}
            <Field label="Salary Min (USD)">
              <input type="number" className="input" value={form.salary_min}
                onChange={(e) => setForm((f) => ({ ...f, salary_min: Number(e.target.value) }))} />
            </Field>
            <Field label="Salary Max (USD)">
              <input type="number" className="input" value={form.salary_max}
                onChange={(e) => setForm((f) => ({ ...f, salary_max: Number(e.target.value) }))} />
            </Field>
          </div>
        </Section>

        {/* Skills */}
        <Section
          title="Skills"
          action={<button type="button" onClick={addSkill}
            className="text-xs text-brand-600 hover:underline">+ Add skill</button>}
        >
          {form.skills.length === 0 && (
            <p className="text-slate-400 text-sm">
              No skills yet — upload your resume to auto-fill, or add manually.
            </p>
          )}
          <div className="space-y-2">
            {form.skills.map((sk, i) => (
              <div key={i} className="flex gap-2 items-center">
                <input className="input flex-1" placeholder="e.g. Python"
                  value={sk.name}
                  onChange={(e) => updateSkill(i, 'name', e.target.value)} />
                <select className="input w-36" value={sk.level}
                  onChange={(e) => updateSkill(i, 'level', e.target.value)}>
                  <option value="beginner">Beginner</option>
                  <option value="intermediate">Intermediate</option>
                  <option value="expert">Expert</option>
                </select>
                <button type="button" onClick={() => removeSkill(i)}
                  className="text-slate-400 hover:text-red-500 text-xl leading-none">×</button>
              </div>
            ))}
          </div>
        </Section>

        {/* Experience */}
        <Section
          title="Work Experience"
          action={<button type="button" onClick={addExp}
            className="text-xs text-brand-600 hover:underline">+ Add role</button>}
        >
          {form.experience.length === 0 && (
            <p className="text-slate-400 text-sm">
              Upload your resume to auto-fill, or add roles manually.
            </p>
          )}
          <div className="space-y-4">
            {form.experience.map((exp, i) => (
              <div key={i} className="border border-slate-200 rounded-lg p-4 space-y-3">
                <div className="flex justify-between items-start">
                  <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                    Role {i + 1}
                  </p>
                  <button type="button" onClick={() => removeExp(i)}
                    className="text-slate-400 hover:text-red-500 text-lg leading-none">×</button>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Job Title">
                    <input className="input" placeholder="Senior Engineer" value={exp.role}
                      onChange={(e) => updateExp(i, 'role', e.target.value)} />
                  </Field>
                  <Field label="Company">
                    <input className="input" placeholder="Accenture" value={exp.company}
                      onChange={(e) => updateExp(i, 'company', e.target.value)} />
                  </Field>
                  <Field label="Start">
                    <input className="input" placeholder="Jan 2022" value={exp.start}
                      onChange={(e) => updateExp(i, 'start', e.target.value)} />
                  </Field>
                  <Field label="End">
                    <input className="input" placeholder="Present" value={exp.end}
                      onChange={(e) => updateExp(i, 'end', e.target.value)} />
                  </Field>
                </div>
                <Field label="Highlights / Bullet Points">
                  <div className="space-y-2">
                    {exp.highlights.map((h, hi) => (
                      <div key={hi} className="flex gap-2 items-center">
                        <input className="input flex-1 text-xs" placeholder="Led X, resulting in Y% improvement…"
                          value={h}
                          onChange={(e) => updateHighlight(i, hi, e.target.value)} />
                        <button type="button" onClick={() => removeHighlight(i, hi)}
                          className="text-slate-400 hover:text-red-500 text-lg leading-none">×</button>
                      </div>
                    ))}
                    <button type="button" onClick={() => addHighlight(i)}
                      className="text-xs text-brand-600 hover:underline">+ Add bullet</button>
                  </div>
                </Field>
              </div>
            ))}
          </div>
        </Section>

        {/* Education */}
        <Section
          title="Education"
          action={
            <button type="button"
              onClick={() => setForm((f) => ({
                ...f,
                education: [...f.education, { institution: '', degree: '', year: 2020 }],
              }))}
              className="text-xs text-brand-600 hover:underline">+ Add</button>
          }
        >
          <div className="space-y-3">
            {form.education.map((edu, i) => (
              <div key={i} className="flex gap-2 items-end">
                <Field label="Degree" className="flex-1">
                  <input className="input" placeholder="B.Tech Computer Science"
                    value={edu.degree}
                    onChange={(e) => {
                      const education = [...form.education]
                      education[i] = { ...education[i], degree: e.target.value }
                      setForm((f) => ({ ...f, education }))
                    }} />
                </Field>
                <Field label="Institution" className="flex-1">
                  <input className="input" placeholder="Amity University"
                    value={edu.institution}
                    onChange={(e) => {
                      const education = [...form.education]
                      education[i] = { ...education[i], institution: e.target.value }
                      setForm((f) => ({ ...f, education }))
                    }} />
                </Field>
                <Field label="Year" className="w-20">
                  <input type="number" className="input" value={edu.year}
                    onChange={(e) => {
                      const education = [...form.education]
                      education[i] = { ...education[i], year: Number(e.target.value) }
                      setForm((f) => ({ ...f, education }))
                    }} />
                </Field>
                <button type="button"
                  onClick={() => setForm((f) => ({ ...f, education: f.education.filter((_, idx) => idx !== i) }))}
                  className="text-slate-400 hover:text-red-500 text-xl leading-none mb-1">×</button>
              </div>
            ))}
          </div>
        </Section>

        {/* Message */}
        {msg && (
          <div className={clsx(
            'px-4 py-2 rounded-lg text-sm',
            msg.ok
              ? 'bg-green-50 border border-green-200 text-green-700'
              : 'bg-red-50 border border-red-200 text-red-700'
          )}>
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

// ── Small helpers ─────────────────────────────────────────────────────────────

function Section({
  title,
  action,
  children,
}: {
  title: string
  action?: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold text-slate-700">{title}</h2>
        {action}
      </div>
      {children}
    </div>
  )
}

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
