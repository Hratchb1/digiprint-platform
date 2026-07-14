import { useQuery } from '@tanstack/react-query'
import { dashboardApi } from '../lib/api'

// Dashboard aggregators refresh on a 60s cadence — pipeline state moves
// on Pronto-sync (10 min) and Drive-watcher (5 min) timescales.
const REFETCH_MS = 60_000

export function useDashboardCounts() {
  return useQuery({
    queryKey: ['dashboard', 'counts'],
    queryFn: dashboardApi.counts,
    refetchInterval: REFETCH_MS,
  })
}

export function useNeedsAttention() {
  return useQuery({
    queryKey: ['dashboard', 'needs_attention'],
    queryFn: dashboardApi.needsAttention,
    refetchInterval: REFETCH_MS,
  })
}

export function useTodayActivity() {
  return useQuery({
    queryKey: ['dashboard', 'today_activity'],
    queryFn: dashboardApi.todayActivity,
    refetchInterval: REFETCH_MS,
  })
}

export function usePerformance() {
  return useQuery({
    queryKey: ['dashboard', 'performance'],
    queryFn: dashboardApi.performance,
    refetchInterval: REFETCH_MS,
  })
}

export function useWorkload() {
  return useQuery({
    queryKey: ['dashboard', 'workload'],
    queryFn: dashboardApi.workload,
    refetchInterval: REFETCH_MS,
  })
}

// Convenience bundle for DashboardPage
export function useDashboard() {
  return {
    counts: useDashboardCounts(),
    needsAttention: useNeedsAttention(),
    todayActivity: useTodayActivity(),
    performance: usePerformance(),
    workload: useWorkload(),
  }
}
