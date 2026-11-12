import type { Job, SponsorshipStatus } from '@/lib/api'

const BADGES: Record<SponsorshipStatus, { label: string; color: string; explanation: string }> = {
  mentioned: {
    label: 'Sponsorship mentioned',
    color: 'border-emerald-200 bg-emerald-50 text-emerald-800',
    explanation: 'The listing explicitly mentions a sponsorship offer.',
  },
  conditional: {
    label: 'Conditional sponsorship',
    color: 'border-amber-200 bg-amber-50 text-amber-800',
    explanation: 'Sponsorship has conditions or is limited, for example to visa transfers.',
  },
  not_available: {
    label: 'No sponsorship',
    color: 'border-rose-200 bg-rose-50 text-rose-800',
    explanation: 'The listing explicitly states that sponsorship is unavailable.',
  },
  not_specified: {
    label: 'Sponsorship unclear',
    color: 'border-slate-200 bg-slate-100 text-slate-600',
    explanation: 'The listing does not clearly confirm or rule out visa sponsorship.',
  },
}

export default function SponsorshipBadge({ job }: { job: Pick<Job, 'sponsorship_status' | 'sponsorship_checked_at' | 'sponsorship_needs_review'> }) {
  // A default category alone does not mean that the description has been assessed.
  const badge = job.sponsorship_checked_at && job.sponsorship_status
    ? BADGES[job.sponsorship_status]
    : undefined
  const label = badge?.label ?? 'Not assessed'
  const explanation = badge?.explanation ?? 'This job has not been assessed for visa sponsorship yet.'
  const review = badge && job.sponsorship_needs_review ? ' Review needed.' : ''

  return <span
    className={`rounded border px-2 py-0.5 text-xs ${badge?.color ?? 'border-dashed border-slate-300 bg-white text-slate-500'}`}
    title={`${explanation}${review}`}
    aria-label={`Visa sponsorship: ${label}.${review}`}
  >{label}</span>
}
