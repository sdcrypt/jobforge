'use client'

import useSWR from 'swr'
import { api, Job } from '@/lib/api'

// Fetch up to 200 jobs (dismissed ones are hidden in the jobs page filter)
const fetcher = () => api.jobs.list({ limit: 200 }).then((r) => r.jobs)

export function useJobs() {
  const { data, error, isLoading, mutate } = useSWR<Job[]>('/api/jobs', fetcher, {
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
