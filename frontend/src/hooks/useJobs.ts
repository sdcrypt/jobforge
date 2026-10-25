'use client'

import useSWR from 'swr'
import { api, Job } from '@/lib/api'

// Backend caps list responses at 100 jobs.
export function useJobs(status = 'all') {
  const params = status === 'all' ? {} : ['new', 'ranked'].includes(status)
    ? { status } : { application_status: status }
  const { data, error, isLoading, mutate } = useSWR<Job[]>(['/api/jobs', status], () => api.jobs.list({ limit: 100, ...params }).then(result => result.jobs), {
    refreshInterval: 10_000, // auto-refresh every 10s while pipeline runs
  })

  return {
    // Exclude dismissed jobs from the default list
    jobs: (data ?? []).filter((j) => j.status !== 'dismissed'),
    allJobs: data ?? [],
    isLoading,
    error,
    refresh: mutate,
  }
}
