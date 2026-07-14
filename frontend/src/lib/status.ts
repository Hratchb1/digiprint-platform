// Order status vocabulary — mirrors backend OrderStatus enum (schemas.py).
// "archived" is intentionally excluded: it is an internal roll-level status only.

export const ORDER_STATUSES = [
  'inbound',
  'booked_in',
  'scanning',
  'delivered',
  'cancelled',
  'discarded',
] as const

export type OrderStatus = (typeof ORDER_STATUSES)[number]

// Orders still moving through the lab — default view on the Orders page.
export const ACTIVE_STATUSES: OrderStatus[] = ['inbound', 'booked_in', 'scanning']

// Terminal states — hidden by default, rendered line-through when shown.
export const TERMINAL_STATUSES: OrderStatus[] = ['delivered', 'cancelled', 'discarded']

export const STATUS_LABELS: Record<OrderStatus, string> = {
  inbound:   'Inbound',
  booked_in: 'Booked in',
  scanning:  'Scanning',
  delivered: 'Delivered',
  cancelled: 'Cancelled',
  discarded: 'Discarded',
}

// Pill styling per order status (dark theme)
export const STATUS_STYLES: Record<OrderStatus, string> = {
  inbound:   'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  booked_in: 'bg-blue-500/10 text-blue-400 border-blue-500/20',
  scanning:  'bg-purple-500/10 text-purple-400 border-purple-500/20',
  delivered: 'bg-green-500/10 text-green-400 border-green-500/20',
  cancelled: 'bg-[#1a1a1a] text-[#555] border-[#2a2a2a]',
  discarded: 'bg-red-500/10 text-red-400 border-red-500/20',
}

export const FALLBACK_STATUS_STYLE = 'bg-[#1a1a1a] text-[#555] border-[#2a2a2a]'

// Manual transitions offered in the Order Detail "Update Status" panel.
// inbound → booked_in happens via the intake flow, and discarding goes
// through POST /orders/:id/discard — neither is offered here.
export const NEXT_STATUSES: Record<OrderStatus, OrderStatus[]> = {
  inbound:   ['cancelled'],
  booked_in: ['scanning', 'delivered', 'cancelled'],
  scanning:  ['delivered', 'cancelled'],
  delivered: [],
  cancelled: [],
  discarded: [],
}

export function statusLabel(status: string): string {
  return STATUS_LABELS[status as OrderStatus] ?? status.replace(/_/g, ' ')
}

export function statusStyle(status: string): string {
  return STATUS_STYLES[status as OrderStatus] ?? FALLBACK_STATUS_STYLE
}

export function isTerminal(status: string): boolean {
  return TERMINAL_STATUSES.includes(status as OrderStatus)
}

// ── Roll-level statuses ────────────────────────────────────────────────────
// Rolls keep the old vocabulary (migration 003 was orders-only).

export const ROLL_STATUS_STYLES: Record<string, string> = {
  booked:      'bg-yellow-500/10 text-yellow-400 border-yellow-500/20',
  processing:  'bg-blue-500/10 text-blue-400 border-blue-500/20',
  scanned:     'bg-purple-500/10 text-purple-400 border-purple-500/20',
  delivered:   'bg-green-500/10 text-green-400 border-green-500/20',
  blank:       'bg-red-500/10 text-red-400 border-red-500/20',
  archived:    'bg-green-500/10 text-green-400 border-green-500/20',
}

// Archived rolls read as "delivered" to staff — archived is internal
// bookkeeping for released twin checks.
export function displayRollStatus(status: string): string {
  return status === 'archived' ? 'delivered' : status
}

export function rollStatusStyle(status: string): string {
  return ROLL_STATUS_STYLES[status] ?? FALLBACK_STATUS_STYLE
}
