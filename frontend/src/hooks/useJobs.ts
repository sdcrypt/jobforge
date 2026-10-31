'use client'

import useSWR from 'swr'
import { api, JobsQuery } from '@/lib/api'

export function useJobs(params: JobsQuery = {}) {
  const { data, error, isLoading, mutate } = useSWR(['jobs', params], () => api.jobs.list(params), {
    refreshInterval: 10_000,
  })

  return {
    jobs: data?.jobs ?? [],
    total: data?.total ?? 0,
    hasMore: data?.has_more ?? false,
    isLoading,
    error,
    refresh: mutate,
  }
}
