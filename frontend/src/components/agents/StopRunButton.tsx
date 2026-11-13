'use client'

import { useState } from 'react'
import { useSWRConfig } from 'swr'
import { api, TaskRun } from '@/lib/api'

export default function StopRunButton({ run }: { run: TaskRun }) {
  const [stopping, setStopping] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const { mutate } = useSWRConfig()
  if (!['queued', 'running', 'retrying'].includes(run.status)) return null

  async function stop() {
    setStopping(true)
    setError(null)
    try {
      await api.runs.stop(run.id)
      // Refresh every visible run view, including the shared pipeline banner.
      await mutate(key => key === 'pipeline-runs' || (Array.isArray(key) && ['runs', 'run', 'run-events'].includes(key[0])))
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : 'Could not stop this run.')
    } finally {
      setStopping(false)
    }
  }

  return <span className="inline-flex flex-col items-start gap-1">
    <button type="button" onClick={() => void stop()} disabled={stopping}
      className="rounded-lg border border-red-200 bg-white px-3 py-2 text-sm font-medium text-red-700 hover:bg-red-50 disabled:opacity-50">
      {stopping ? 'Stopping…' : 'Stop run'}
    </button>
    {error && <span role="alert" className="text-xs text-red-700">{error}</span>}
  </span>
}
