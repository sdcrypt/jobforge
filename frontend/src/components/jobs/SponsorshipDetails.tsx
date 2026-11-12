import type { Job } from '@/lib/api'
import SponsorshipBadge from './SponsorshipBadge'

type SponsorshipJob = Pick<Job, 'id' | 'sponsorship_status' | 'sponsorship_checked_at' | 'sponsorship_needs_review' | 'sponsorship_evidence'>

export default function SponsorshipDetails({ job }: { job: SponsorshipJob }) {
  const assessed = Boolean(job.sponsorship_checked_at)
  const evidence = assessed ? job.sponsorship_evidence ?? [] : []
  const matchingStatement = evidence.find(entry => entry.status === job.sponsorship_status)
  // Keep conflicting statements together when no single category matches.
  const statements = matchingStatement ? [matchingStatement] : evidence

  return <section aria-labelledby={`sponsorship-heading-${job.id}`} className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 id={`sponsorship-heading-${job.id}`} className="text-sm font-semibold">Visa sponsorship</h3>
      <SponsorshipBadge job={job} />
    </div>
    {statements.length > 0
      ? statements.map((entry, index) => <p key={`${index}-${entry.status}`} className="whitespace-pre-wrap break-words text-sm leading-6 text-slate-600">{entry.quote}</p>)
      : <p className="text-sm text-slate-500">{assessed ? 'No clear sponsorship statement found.' : 'Not assessed yet.'}</p>}
  </section>
}
