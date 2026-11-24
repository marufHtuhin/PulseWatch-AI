import axios from 'axios'

// In dev, Vite proxies /api -> http://127.0.0.1:8000 (see vite.config.js).
// In production builds, VITE_API_BASE_URL must point at the backend
// origin INCLUDING the /api prefix, e.g.
// https://pulsewatch-api.onrender.com/api — all API routes live under /api.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  // Render free tier can take ~30-60s to cold-start after idling, so
  // the default 30s timeout would fail the first request after sleep.
  timeout: 60000,
})

/** localStorage key for the JWT access token. */
export const TOKEN_KEY = 'pulsewatch_token'

// Attach the JWT to every request when one is stored.
api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY)
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// An expired/invalid token anywhere means the session is dead: clear it
// and send the user to /login. Guarded so we never redirect-loop while
// already on an auth page (a failed login attempt is a 401 too, and the
// form needs to show that error instead of navigating away).
//
// Exception: a 401 from POST /auth/change-password only means the current
// password was wrong — the session is still valid, so the token must NOT
// be cleared and the user must NOT be redirected; the form shows the error.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error?.response?.status === 401) {
      const requestUrl = error.config?.url || ''
      if (!requestUrl.includes('/auth/change-password')) {
        localStorage.removeItem(TOKEN_KEY)
        const path = window.location.pathname
        if (
          path !== '/login' &&
          path !== '/register' &&
          path !== '/forgot-password' &&
          path !== '/reset-password'
        ) {
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(error)
  }
)

/** Extract a human-readable message from an axios error. */
export function apiErrorMessage(err, fallback = 'Something went wrong') {
  if (!err) return fallback
  const detail = err.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d) => (typeof d === 'string' ? d : d?.msg || JSON.stringify(d)))
      .join('; ')
  }
  if (err.code === 'ECONNABORTED') return 'Request timed out'
  if (!err.response) return 'Cannot reach the backend — is it running?'
  return err.message || fallback
}

export function isNotFound(err) {
  return err?.response?.status === 404
}

// ---- Auth (password management) ----
export const changePassword = (payload) =>
  api.post('/auth/change-password', payload).then((r) => r.data)

export const forgotPassword = (payload) =>
  api.post('/auth/forgot-password', payload).then((r) => r.data)

export const resetPassword = (payload) =>
  api.post('/auth/reset-password', payload).then((r) => r.data)

// ---- Monitors ----
export const listMonitors = (params = {}) =>
  api.get('/monitors', { params }).then((r) => r.data)

export const getMonitor = (id) => api.get(`/monitors/${id}`).then((r) => r.data)

export const createMonitor = (payload) =>
  api.post('/monitors', payload).then((r) => r.data)

export const updateMonitor = (id, payload) =>
  api.put(`/monitors/${id}`, payload).then((r) => r.data)

export const toggleMonitor = (id) =>
  api.patch(`/monitors/${id}/toggle`).then((r) => r.data)

export const deleteMonitor = (id) => api.delete(`/monitors/${id}`)

export const checkMonitorNow = (id) =>
  api.post(`/monitors/${id}/check`).then((r) => r.data)

// ---- Monitoring history ----
export const listHistory = (params = {}) =>
  api.get('/monitoring/history', { params }).then((r) => r.data)

export const listMonitorHistory = (monitorId, params = {}) =>
  api.get(`/monitoring/history/${monitorId}`, { params }).then((r) => r.data)

export const batchCheck = (monitorIds) =>
  api.post('/monitoring/batch', { monitor_ids: monitorIds }).then((r) => r.data)

// ---- Alerts ----
export const listAlerts = (params = {}) =>
  api.get('/alerts', { params }).then((r) => r.data)

export const listAlertHistory = (params = {}) =>
  api.get('/alerts/history', { params }).then((r) => r.data)

export const getAlert = (id) => api.get(`/alerts/${id}`).then((r) => r.data)

export const acknowledgeAlert = (id) =>
  api.patch(`/alerts/${id}/acknowledge`).then((r) => r.data)

export const resolveAlert = (id) =>
  api.patch(`/alerts/${id}/resolve`).then((r) => r.data)

// ---- Dashboard ----
export const getDashboardSummary = () =>
  api.get('/dashboard/summary').then((r) => r.data)

export const getDashboardPerformance = (params = {}) =>
  api.get('/dashboard/performance', { params }).then((r) => r.data)

export const getDashboardHealth = () =>
  api.get('/dashboard/health').then((r) => r.data)

// ---- Settings ----
export const getSettings = () => api.get('/settings').then((r) => r.data)

export const updateSettings = (payload) =>
  api.put('/settings', payload).then((r) => r.data)

export const testNotification = () =>
  api.post('/settings/test-notification').then((r) => r.data)

export const getCleanupPreview = () =>
  api.get('/settings/cleanup-preview').then((r) => r.data)

export const cleanupHistory = () =>
  api.post('/settings/cleanup').then((r) => r.data)

// ---- Admin (admin-only endpoints under /api/admin) ----
export const getAdminStats = () => api.get('/admin/stats').then((r) => r.data)

export const listAdminUsers = (params = {}) =>
  api.get('/admin/users', { params }).then((r) => r.data)

export const getAdminUser = (id) => api.get(`/admin/users/${id}`).then((r) => r.data)

export const updateAdminUser = (id, payload) =>
  api.patch(`/admin/users/${id}`, payload).then((r) => r.data)

export const deleteAdminUser = (id) => api.delete(`/admin/users/${id}`)

export const listAdminMonitors = (params = {}) =>
  api.get('/admin/monitors', { params }).then((r) => r.data)

export default api
