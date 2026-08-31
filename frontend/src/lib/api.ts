import axios from 'axios'

const BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

export const api = axios.create({ baseURL: BASE })

// Attach JWT automatically
api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// Auto-logout on 401
api.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

// ── Auth ──────────────────────────────────────────────────────────────────
export const authApi = {
  login: (email: string, password: string) =>
    api.post('/auth/login', { email, password }).then(r => r.data),
  me: () => api.get('/auth/me').then(r => r.data),
}

// ── Stores ────────────────────────────────────────────────────────────────
export const storesApi = {
  list: () => api.get('/stores').then(r => r.data),
}

// ── Orders ────────────────────────────────────────────────────────────────
export const ordersApi = {
  list: (params?: {
    store_id?: string
    status?: string | string[]   // single status or list (sent comma-separated)
    search?: string
    twin?: string                // exact twin-check match
    limit?: number
    offset?: number
  }) => api.get('/orders', {
    params: {
      ...params,
      status: Array.isArray(params?.status) ? params.status.join(',') : params?.status,
    },
  }).then(r => r.data),

  get: (id: string) => api.get(`/orders/${id}`).then(r => r.data),

  create: (payload: object) => api.post('/orders', payload).then(r => r.data),

  updateStatus: (id: string, status: string, notes?: string) =>
    api.patch(`/orders/${id}/status`, { status, notes }).then(r => r.data),

  setDriveLink: (id: string, url: string) =>
    api.patch(`/orders/${id}/drive-link`, { drive_order_folder_url: url }).then(r => r.data),

  markBlank: (id: string, roll_ids: string[], send_email = false) =>
    api.post(`/orders/${id}/mark-blank`, { roll_ids, send_email }).then(r => r.data),

  events: (id: string) => api.get(`/orders/${id}/events`).then(r => r.data),

  checkTwin: (store_id: string, twin_check: string) =>
    api.get('/orders/check/twin', { params: { store_id, twin_check } }).then(r => r.data),

  checkOrderNumber: (order_number: string, store_id: string) =>
    api.get('/orders/check/order-number', { params: { order_number, store_id } }).then(r => r.data),

  addRolls: (id: string, payload: object) =>
    api.post(`/orders/${id}/add-rolls`, payload).then(r => r.data),

  resetTwins: (id: string) =>
    api.post(`/orders/${id}/reset-twins`).then(r => r.data),

  retryBorder: (id: string) =>
    api.post(`/orders/${id}/retry-border`).then(r => r.data),

  discard: (id: string, reason: DiscardReason, notes?: string, operator_id?: string) =>
    api.post(`/orders/${id}/discard`, { reason, notes, operator_id }).then(r => r.data),
}

// Mirrors backend DiscardReason enum (schemas.py)
export type DiscardReason =
  | 'charge_correction'
  | 'add_on_existing'
  | 'not_film_related'
  | 'duplicate_sale'
  | 'other'

// ── Rolls ─────────────────────────────────────────────────────────────────
export const rollsApi = {
  updateTwinCheck: (rollId: string, twin_check: string) =>
    api.patch(`/rolls/${rollId}/twin-check`, { twin_check }).then(r => r.data),
}

// ── Twin checks (RollCall auto-allocation) ──────────────────────────────────
export interface TwinCheckRead {
  id: string
  store_id: string
  number: number
  twin_check: string          // zero-padded 4-digit display form
  cycle: number | null
  source: 'auto' | 'manual'
  order_id: string | null
  roll_id: string | null
  status: 'allocated' | 'printed' | 'voided'
  collision_warning: boolean
  allocated_at: string
  allocated_by: string | null
  printed_at: string | null
  voided_at: string | null
  void_reason: string | null
}

export interface AllocateResponse {
  order_id: string
  twin_checks: TwinCheckRead[]
  range_label: string | null
}

export const twinChecksApi = {
  allocate: (orderId: string): Promise<AllocateResponse> =>
    api.post(`/orders/${orderId}/twin-checks/allocate`).then(r => r.data),

  print: (orderId: string): Promise<{ print_job_id: string; status: string }> =>
    api.post(`/orders/${orderId}/twin-checks/print`).then(r => r.data),

  addRoll: (orderId: string, service_type: string, process_code?: string | null): Promise<AllocateResponse> =>
    api.post(`/orders/${orderId}/twin-checks/add-roll`, { service_type, process_code }).then(r => r.data),

  reprint: (twinCheckId: string): Promise<{ print_job_id: string; status: string }> =>
    api.post(`/twin-checks/${twinCheckId}/reprint`).then(r => r.data),

  void: (twinCheckId: string, reason: string): Promise<TwinCheckRead> =>
    api.post(`/twin-checks/${twinCheckId}/void`, { reason }).then(r => r.data),

  rescan: (orderId: string, roll_ids: string[]): Promise<AllocateResponse> =>
    api.post(`/orders/${orderId}/rescan`, { roll_ids }).then(r => r.data),
}

// ── Twin check sequences (admin) ────────────────────────────────────────────
export interface TwinCheckSequence {
  store_id: string
  current_value: number
  cycle: number
  min_value: number
  max_value: number
  auto_enabled: boolean
  updated_at: string
}

export const twinCheckSequencesApi = {
  list: (): Promise<TwinCheckSequence[]> =>
    api.get('/twin-check-sequences').then(r => r.data),
  update: (storeId: string, auto_enabled: boolean): Promise<TwinCheckSequence> =>
    api.patch(`/twin-check-sequences/${storeId}`, { auto_enabled }).then(r => r.data),
  // Non-admin — any authenticated user can check their own store's mode.
  // Used by IntakePage to decide which twin-check UI to render.
  getMode: (storeId: string): Promise<{ store_id: string; auto_enabled: boolean }> =>
    api.get(`/twin-check-sequences/${storeId}/mode`).then(r => r.data),
}

// ── Emails ────────────────────────────────────────────────────────────────
export const emailsApi = {
  send: (orderId: string, payload: object = {}) =>
    api.post(`/emails/send/${orderId}`, payload).then(r => r.data),
  resend: (orderId: string) =>
    api.post(`/emails/resend/${orderId}`).then(r => r.data),
  log: (orderId: string) =>
    api.get(`/emails/log/${orderId}`).then(r => r.data),
}

// ── Drive ─────────────────────────────────────────────────────────────────
export const driveApi = {
  logForOrder: (orderId: string) =>
    api.get(`/drive/log/order/${orderId}`).then(r => r.data),
  clearLogEntry: (folderId: string) =>
    api.delete(`/drive/log/${folderId}`).then(r => r.data),
  sync: (): Promise<{ status: 'completed' | 'already_running'; message: string }> =>
    api.post('/drive/sync').then(r => r.data),
}

// ── Dashboard (Phase 3 aggregators) ───────────────────────────────────────
export interface DashboardCounts {
  inbound_orders: number
  booked_orders: number
  inbound_rolls: number
  booked_rolls: number
}

export interface NeedsAttention {
  overdue_count: number
  overdue_order_ids: string[]
  stuck_in_scanning_count: number
  stuck_in_scanning_order_ids: string[]
  missing_email_count: number
  missing_email_order_ids: string[]
  inbound_aging_count: number
  inbound_aging_order_ids: string[]
}

export interface TodayActivity {
  orders_received: number
  orders_booked_in: number
  orders_delivered: number
}

export interface DashboardPerformance {
  avg_turnaround_days: number
  rolls_today: number
  pending_rolls: number
  pending_orders: number
  overdue_count: number
}

export interface DashboardWorkload {
  avg_pending_age_days: number
  oldest_pending_days: number
  missing_email_count: number
}

export const dashboardApi = {
  // Legacy 30-day stats (pre-Phase 3) — still served at /api/dashboard/stats
  stats: (store_id?: string, period_days = 30) =>
    api.get('/dashboard/stats', { params: { store_id, period_days } }).then(r => r.data),

  counts: (): Promise<DashboardCounts> =>
    api.get('/dashboard/counts').then(r => r.data),
  needsAttention: (): Promise<NeedsAttention> =>
    api.get('/dashboard/needs_attention').then(r => r.data),
  todayActivity: (): Promise<TodayActivity> =>
    api.get('/dashboard/today_activity').then(r => r.data),
  performance: (): Promise<DashboardPerformance> =>
    api.get('/dashboard/performance').then(r => r.data),
  workload: (): Promise<DashboardWorkload> =>
    api.get('/dashboard/workload').then(r => r.data),
}

// ── Refund warnings ───────────────────────────────────────────────────────
export interface RefundWarning {
  id: string
  status: string
  created_at: string
  [key: string]: any
}

export const refundWarningsApi = {
  list: (): Promise<RefundWarning[]> =>
    api.get('/refund-warnings').then(r => r.data),
  resolve: (warningId: string, order_id: string, notes?: string, operator_id?: string) =>
    api.post(`/refund-warnings/${warningId}/resolve`, { order_id, notes, operator_id }).then(r => r.data),
  ignore: (warningId: string, notes?: string, operator_id?: string) =>
    api.post(`/refund-warnings/${warningId}/ignore`, { notes, operator_id }).then(r => r.data),
}
