'use client'

import useSWR from 'swr'
import { api, Job } from '@/lib/api'

const fetcher = () => api.jobs.list({ limit: 100 }).then((r) => r.jobs)

export function useJobs() {
  const { data, error, isLoading, mutate } = useSWR<Job[]>('/api/jobs', fetcher, {
    refreshInterval: 10_000, // auto-refresh every 10s while pipeline runs
  })

  return {
    jobs: data ?? [],
    isLoading,
    error,
    refresh: mutate,
  }
}
