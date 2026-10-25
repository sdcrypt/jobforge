'use client'

import useSWR from 'swr'
import { api } from '@/lib/api'

export function usePipelineRun() {
  const { data, mutate } = useSWR('pipeline-runs', () => api.runs.list({ kind: 'discovery', status: 'active', limit: 1 }), { refreshInterval: 3000 })
  const activeRun = data?.runs.find(run => ['pipeline', 'search', 'rank'].includes(run.kind) && ['queued', 'running', 'retrying'].includes(run.status))
  return { activeRun, refreshRuns: mutate }
}
