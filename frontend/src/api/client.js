import axios from 'axios'

// In dev, Vite proxies /api -> http://127.0.0.1:8000 (see vite.config.js).
// In production builds, VITE_API_BASE_URL can point at the backend origin.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || '/api',
  timeout: 30000,
})

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

// ---- Health ----
export const getHealth = () => api.get('/health').then((r) => r.data)

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

export default api
