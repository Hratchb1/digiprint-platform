import { useQuery } from '@tanstack/react-query'
import { ordersApi } from '../lib/api'

export interface OrderListFilters {
  storeId?: string
  statuses?: string[]   // empty/undefined = all statuses
  search?: string
  twin?: string         // exact twin-check match
  limit?: number
}

export function useOrders({ storeId, statuses, search, twin, limit = 200 }: OrderListFilters) {
  return useQuery({
    queryKey: ['orders', storeId ?? '', statuses ?? [], search ?? '', twin ?? ''],
    queryFn: () => ordersApi.list({
      store_id: storeId || undefined,
      status: statuses && statuses.length > 0 ? statuses : undefined,
      search: search || undefined,
      twin: twin || undefined,
      limit,
    }),
    placeholderData: (prev: any) => prev,
  })
}

export function useOrder(id: string | undefined) {
  return useQuery({
    queryKey: ['order', id],
    queryFn: () => ordersApi.get(id!),
    enabled: !!id,
  })
}

export function useOrderEvents(id: string | undefined) {
  return useQuery({
    queryKey: ['order-events', id],
    queryFn: () => ordersApi.events(id!),
    enabled: !!id,
  })
}
