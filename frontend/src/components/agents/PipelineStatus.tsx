'use client'

import Link from 'next/link'
import { usePipelineRun } from '@/hooks/usePipelineRun'
import StopRunButton from './StopRunButton'

export default function PipelineStatus() {
  const { activeRun } = usePipelineRun()
  return <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-white px-3 py-2 text-sm">
    <span className="text-slate-500">{activeRun ? `${activeRun.kind}: ${activeRun.status} · ${activeRun.stage} · attempt ${activeRun.attempts}/${activeRun.max_attempts}` : 'Progress and past results are saved in Runs.'}</span>
    <div className="flex items-center gap-3">
      {activeRun && <StopRunButton run={activeRun} />}
      <Link className="text-brand-700 hover:underline" href={activeRun ? `/runs?run=${activeRun.id}` : '/runs'}>{activeRun ? 'View progress →' : 'View run history →'}</Link>
    </div>
  </div>
}
