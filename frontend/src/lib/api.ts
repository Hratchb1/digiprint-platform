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
    status?: string
    search?: string
    limit?: number
    offset?: number
  }) => api.get('/orders', { params }).then(r => r.data),

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
}

// ── Dashboard ─────────────────────────────────────────────────────────────
export const dashboardApi = {
  stats: (store_id?: string, period_days = 30) =>
    api.get('/dashboard/stats', { params: { store_id, period_days } }).then(r => r.data),
}
