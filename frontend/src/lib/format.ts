import { format, formatDistanceToNow } from 'date-fns'

// Short timestamp for table rows, e.g. "13 Jul, 21:40"
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  try { return format(new Date(iso), 'dd MMM, HH:mm') }
  catch { return '—' }
}

// Full timestamp for detail views, e.g. "13 Jul 2026, 21:40"
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  try { return format(new Date(iso), 'd MMM yyyy, HH:mm') }
  catch { return '—' }
}

// Relative time, e.g. "3 hours ago"
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—'
  try { return formatDistanceToNow(new Date(iso), { addSuffix: true }) }
  catch { return '—' }
}

// Duration given in hours → "3.5h" under a day, otherwise "1.4d"
export function formatTurnaroundHours(hours: number | null | undefined): string {
  if (hours == null) return '—'
  return hours < 24 ? `${hours.toFixed(1)}h` : `${(hours / 24).toFixed(1)}d`
}

// Duration given in days (dashboard aggregators) → "0.8d" / "12d"
export function formatDays(days: number | null | undefined): string {
  if (days == null) return '—'
  return Number.isInteger(days) ? `${days}d` : `${days.toFixed(1)}d`
}
