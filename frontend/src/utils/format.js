/** Format helpers — all display-only, no fake data anywhere. */

export function formatMs(ms) {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)} ms`
  return `${(ms / 1000).toFixed(2)} s`
}

export function formatUptime(pct) {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return '—'
  return `${Number(pct).toFixed(1)}%`
}

export function formatBytes(bytes) {
  if (bytes === null || bytes === undefined || Number.isNaN(bytes)) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`
}

export function formatNumber(n) {
  if (n === null || n === undefined || Number.isNaN(n)) return '—'
  return Number(n).toLocaleString()
}

export function formatInterval(seconds) {
  if (seconds === null || seconds === undefined) return '—'
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  return `${Math.round(seconds / 3600)}h`
}

export function formatDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Date only, e.g. "Dec 12, 2026". */
export function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function formatTimeOnly(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
}

/** "3m ago" style relative time. */
export function timeAgo(iso) {
  if (!iso) return 'never'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  const diffMs = Date.now() - d.getTime()
  if (diffMs < 0) return 'just now'
  const seconds = Math.floor(diffMs / 1000)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 30) return `${days}d ago`
  return d.toLocaleDateString()
}

export function truncate(str, max = 80) {
  if (!str) return ''
  return str.length > max ? `${str.slice(0, max - 1)}…` : str
}

/** Human label for an anomaly_type enum value. */
const ANOMALY_LABELS = {
  HIGH_RESPONSE_TIME: 'High response time',
  HTTP_ERROR: 'HTTP error',
  TIMEOUT: 'Timeout',
  ZERO_RECORDS: 'Zero records returned',
  INVALID_RESPONSE: 'Invalid response',
  MISSING_FIELDS: 'Missing expected fields',
  LARGE_RESPONSE: 'Response too large',
  UNEXPECTED_STATUS: 'Unexpected status code',
  HISTORICAL_ANOMALY: 'Historical anomaly',
}

export function anomalyLabel(type) {
  if (!type) return '—'
  return ANOMALY_LABELS[type] || type.replace(/_/g, ' ').toLowerCase()
}

/** Severity ordering for display/sorting (highest first). */
export const SEVERITY_ORDER = { critical: 0, high: 1, warning: 2, info: 3 }

/** Parse a comma-separated string into a trimmed, non-empty string array. */
export function parseCommaList(str) {
  if (!str) return []
  return str
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean)
}

/** Parse a comma-separated string into an array of integers (drops invalid). */
export function parseCommaInts(str) {
  return parseCommaList(str)
    .map((s) => Number.parseInt(s, 10))
    .filter((n) => Number.isInteger(n))
}

/** Debounce helper for search inputs. */
export function debounce(fn, wait = 300) {
  let t = null
  return (...args) => {
    if (t) clearTimeout(t)
    t = setTimeout(() => fn(...args), wait)
  }
}
