import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, Eye, EyeOff, Plus, Trash2 } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { apiErrorMessage, createMonitor, getMonitor, updateMonitor } from '../api/client'
import { useToast } from '../components/Toast'
import { ErrorState, LoadingSkeleton, PageHeader } from '../components/Cards'
import { parseCommaInts, parseCommaList } from '../utils/format'

const INTERVAL_OPTIONS = [
  { value: 30, label: 'Every 30 seconds' },
  { value: 60, label: 'Every 1 minute' },
  { value: 300, label: 'Every 5 minutes' },
  { value: 900, label: 'Every 15 minutes' },
  { value: 1800, label: 'Every 30 minutes' },
]

const METHOD_OPTIONS = ['GET', 'POST', 'PUT', 'DELETE']

// Headers the backend treats as secrets — their values are never returned,
// only "********". We never echo them; "********" sent back means "keep".
const MASKED_VALUE = '********'
const SECRET_HEADER_NAMES = new Set([
  'authorization',
  'x-api-key',
  'api-key',
  'cookie',
  'x-auth-token',
  'x-access-token',
])

const EMPTY_FORM = {
  name: '',
  url: '',
  method: 'GET',
  timeout_seconds: 10,
  interval_seconds: 300,
  expected_status_codes: '200',
  latency_threshold_ms: 3000,
  expected_fields: '',
  check_zero_records: false,
  max_response_size_bytes: 1048576,
  request_body: '',
  headers: [{ key: '', value: '', masked: false, show: false }],
}

function monitorToForm(m) {
  const headerEntries = Object.entries(m.headers || {})
  return {
    name: m.name || '',
    url: m.url || '',
    method: m.method || 'GET',
    timeout_seconds: m.timeout_seconds ?? 10,
    interval_seconds: m.interval_seconds ?? 300,
    expected_status_codes: (m.expected_status_codes || [200]).join(', '),
    latency_threshold_ms: m.latency_threshold_ms ?? 3000,
    expected_fields: (m.expected_fields || []).join(', '),
    check_zero_records: !!m.check_zero_records,
    max_response_size_bytes: m.max_response_size_bytes ?? 1048576,
    request_body: m.request_body || '',
    headers:
      headerEntries.length > 0
        ? headerEntries.map(([key, value]) => ({
            key,
            value: value === MASKED_VALUE ? '' : value,
            masked: value === MASKED_VALUE,
            show: false,
          }))
        : [{ key: '', value: '', masked: false, show: false }],
  }
}

function validate(form) {
  const errors = {}

  if (!form.name.trim()) errors.name = 'Name is required.'
  else if (form.name.trim().length > 200) errors.name = 'Name must be 200 characters or fewer.'

  if (!form.url.trim()) {
    errors.url = 'URL is required.'
  } else {
    try {
      const u = new URL(form.url.trim())
      if (u.protocol !== 'http:' && u.protocol !== 'https:') {
        errors.url = 'URL must use http:// or https://.'
      }
    } catch {
      errors.url = 'Enter a valid URL, e.g. https://api.example.com/health.'
    }
  }

  const timeout = Number(form.timeout_seconds)
  if (!Number.isFinite(timeout) || timeout < 1 || timeout > 120) {
    errors.timeout_seconds = 'Timeout must be between 1 and 120 seconds.'
  }

  if (!INTERVAL_OPTIONS.some((o) => o.value === Number(form.interval_seconds))) {
    errors.interval_seconds = 'Choose one of the available check intervals.'
  }

  const codes = parseCommaInts(form.expected_status_codes)
  const rawCodes = parseCommaList(form.expected_status_codes)
  if (rawCodes.length === 0) {
    errors.expected_status_codes = 'Enter at least one expected status code, e.g. 200.'
  } else if (codes.length !== rawCodes.length || codes.some((c) => c < 100 || c > 599)) {
    errors.expected_status_codes = 'Status codes must be numbers between 100 and 599, separated by commas.'
  }

  const latency = Number(form.latency_threshold_ms)
  if (!Number.isFinite(latency) || latency < 0) {
    errors.latency_threshold_ms = 'Latency threshold must be 0 or more milliseconds.'
  }

  const maxSize = Number(form.max_response_size_bytes)
  if (!Number.isFinite(maxSize) || maxSize <= 0) {
    errors.max_response_size_bytes = 'Max response size must be greater than 0 bytes.'
  }

  const seenKeys = new Set()
  form.headers.forEach((h, i) => {
    const key = h.key.trim()
    if (!key && !h.value && !h.masked) return // empty row is fine
    if (!key) {
      errors[`header_${i}`] = 'Header name is required when a value is set.'
      return
    }
    const lower = key.toLowerCase()
    if (seenKeys.has(lower)) {
      errors[`header_${i}`] = `Duplicate header "${key}".`
      return
    }
    seenKeys.add(lower)
  })

  return errors
}

export function MonitorForm() {
  const { id } = useParams()
  const isEdit = Boolean(id)
  const navigate = useNavigate()
  const toast = useToast()

  const [form, setForm] = useState(EMPTY_FORM)
  const [errors, setErrors] = useState({})
  const [serverError, setServerError] = useState(null)
  const [saving, setSaving] = useState(false)
  const [loaded, setLoaded] = useState(!isEdit)

  const existing = useApi(
    () => (isEdit ? getMonitor(id) : Promise.resolve(null)),
    [id],
    { initialData: null }
  )

  useEffect(() => {
    if (isEdit && existing.data && !loaded) {
      setForm(monitorToForm(existing.data))
      setLoaded(true)
    }
  }, [isEdit, existing.data, loaded])

  const showBody = form.method === 'POST' || form.method === 'PUT'

  const set = (field) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [field]: value }))
    setErrors((prev) => ({ ...prev, [field]: undefined }))
  }

  const setHeader = (index, field, value) => {
    setForm((f) => {
      const headers = f.headers.map((h, i) => (i === index ? { ...h, [field]: value } : h))
      return { ...f, headers }
    })
    setErrors((prev) => ({ ...prev, [`header_${index}`]: undefined }))
  }

  const addHeaderRow = () => {
    setForm((f) => ({ ...f, headers: [...f.headers, { key: '', value: '', masked: false, show: false }] }))
  }

  const removeHeaderRow = (index) => {
    setForm((f) => ({ ...f, headers: f.headers.filter((_, i) => i !== index) }))
  }

  const payload = useMemo(() => {
    const headers = {}
    for (const h of form.headers) {
      const key = h.key.trim()
      if (!key) continue
      // Masked secret: empty input means "keep existing" — send "********".
      // A typed value replaces it.
      headers[key] = h.masked && !h.value ? MASKED_VALUE : h.value
    }
    return {
      name: form.name.trim(),
      url: form.url.trim(),
      method: form.method,
      headers,
      request_body: showBody && form.request_body.trim() ? form.request_body : null,
      timeout_seconds: Number(form.timeout_seconds),
      interval_seconds: Number(form.interval_seconds),
      expected_status_codes: parseCommaInts(form.expected_status_codes),
      expected_fields: parseCommaList(form.expected_fields),
      check_zero_records: form.check_zero_records,
      latency_threshold_ms: Number(form.latency_threshold_ms),
      max_response_size_bytes: Number(form.max_response_size_bytes),
    }
  }, [form, showBody])

  const handleSubmit = async (e) => {
    e.preventDefault()
    const validationErrors = validate(form)
    setErrors(validationErrors)
    if (Object.keys(validationErrors).length > 0) {
      toast.error('Please fix the highlighted fields.')
      return
    }
    setServerError(null)
    setSaving(true)
    try {
      if (isEdit) {
        await updateMonitor(id, payload)
        toast.success(`Monitor "${payload.name}" updated.`)
      } else {
        const created = await createMonitor(payload)
        toast.success(`Monitor "${created.name}" created — first check runs on schedule.`)
      }
      navigate('/monitors')
    } catch (err) {
      const msg = apiErrorMessage(err, 'Could not save the monitor')
      setServerError(msg)
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  if (isEdit && existing.loading && !loaded) {
    return (
      <div>
        <PageHeader title="Edit monitor" />
        <LoadingSkeleton rows={6} />
      </div>
    )
  }

  if (isEdit && existing.error) {
    return (
      <div>
        <PageHeader title="Edit monitor" />
        <div className="card">
          <ErrorState
            message={existing.error}
            onRetry={existing.refetch}
          />
        </div>
        <Link to="/monitors" className="btn-secondary mt-4">
          <ArrowLeft className="h-4 w-4" />
          Back to monitors
        </Link>
      </div>
    )
  }

  const fieldError = (field) =>
    errors[field] ? <p className="mt-1 text-xs text-red-400">{errors[field]}</p> : null

  return (
    <div>
      <PageHeader
        title={isEdit ? 'Edit monitor' : 'Add monitor'}
        description={
          isEdit
            ? `Update the configuration for "${existing.data?.name || ''}"`
            : 'Configure a new API endpoint for PulseWatch to monitor'
        }
        actions={
          <Link to="/monitors" className="btn-secondary">
            <ArrowLeft className="h-4 w-4" />
            Back to monitors
          </Link>
        }
      />

      {serverError && (
        <div className="mb-5 rounded-xl border border-red-500/40 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          {serverError}
        </div>
      )}

      <form onSubmit={handleSubmit} className="space-y-6" noValidate>
        {/* Basics */}
        <section className="card p-5">
          <h2 className="mb-4 text-sm font-semibold text-white">Endpoint</h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div className="md:col-span-1">
              <label className="label" htmlFor="name">
                Name *
              </label>
              <input
                id="name"
                className="input"
                placeholder="e.g. JSONPlaceholder Posts"
                value={form.name}
                onChange={set('name')}
                maxLength={200}
              />
              {fieldError('name')}
            </div>
            <div className="md:col-span-1">
              <label className="label" htmlFor="method">
                HTTP method
              </label>
              <select id="method" className="input" value={form.method} onChange={set('method')}>
                {METHOD_OPTIONS.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
            </div>
            <div className="md:col-span-2">
              <label className="label" htmlFor="url">
                URL *
              </label>
              <input
                id="url"
                type="url"
                className="input font-mono"
                placeholder="https://api.example.com/health"
                value={form.url}
                onChange={set('url')}
              />
              {fieldError('url')}
              <p className="mt-1 text-xs text-slate-500">
                Only http/https URLs are accepted. Private and loopback addresses are blocked unless the server allows local URLs.
              </p>
            </div>
            {showBody && (
              <div className="md:col-span-2">
                <label className="label" htmlFor="request_body">
                  Request body
                </label>
                <textarea
                  id="request_body"
                  className="input min-h-[96px] font-mono"
                  placeholder='{"key": "value"}'
                  value={form.request_body}
                  onChange={set('request_body')}
                />
                <p className="mt-1 text-xs text-slate-500">Sent as-is with the request. Leave empty for no body.</p>
              </div>
            )}
          </div>
        </section>

        {/* Headers */}
        <section className="card p-5">
          <h2 className="mb-1 text-sm font-semibold text-white">Request headers</h2>
          <p className="mb-4 text-xs text-slate-500">
            Optional. Secret values (Authorization, API keys, cookies) are stored server-side and never shown back — a masked value means “keep the existing secret”.
          </p>
          <div className="space-y-2.5">
            {form.headers.map((h, i) => {
              const isSecretName = SECRET_HEADER_NAMES.has(h.key.trim().toLowerCase())
              const hideValue = h.masked || isSecretName
              return (
                <div key={i} className="flex flex-col gap-2 sm:flex-row sm:items-start">
                  <input
                    className="input sm:w-56"
                    placeholder="Header name"
                    value={h.key}
                    onChange={(e) => setHeader(i, 'key', e.target.value)}
                    aria-label={`Header ${i + 1} name`}
                  />
                  <div className="relative flex-1">
                    <input
                      className="input pr-10 font-mono"
                      type={hideValue && !h.show ? 'password' : 'text'}
                      placeholder={h.masked ? '•••••••• (unchanged — type to replace)' : 'Header value'}
                      value={h.value}
                      onChange={(e) => setHeader(i, 'value', e.target.value)}
                      aria-label={`Header ${i + 1} value`}
                    />
                    {hideValue && (
                      <button
                        type="button"
                        className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-slate-500 hover:text-slate-200"
                        onClick={() => setHeader(i, 'show', !h.show)}
                        aria-label={h.show ? 'Hide value' : 'Show value'}
                        title={h.show ? 'Hide value' : 'Show value'}
                      >
                        {h.show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                      </button>
                    )}
                  </div>
                  <button
                    type="button"
                    className="btn-icon shrink-0"
                    onClick={() => removeHeaderRow(i)}
                    disabled={form.headers.length === 1}
                    aria-label={`Remove header ${i + 1}`}
                    title="Remove header"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                  {errors[`header_${i}`] && (
                    <p className="text-xs text-red-400 sm:hidden">{errors[`header_${i}`]}</p>
                  )}
                </div>
              )
            })}
            {form.headers.some((_, i) => errors[`header_${i}`]) && (
              <p className="hidden text-xs text-red-400 sm:block">
                {Object.entries(errors)
                  .filter(([k]) => k.startsWith('header_'))
                  .map(([, v]) => v)
                  .join(' ')}
              </p>
            )}
          </div>
          <button type="button" className="btn-secondary mt-3 !py-1.5 text-xs" onClick={addHeaderRow}>
            <Plus className="h-3.5 w-3.5" />
            Add header
          </button>
        </section>

        {/* Schedule & thresholds */}
        <section className="card p-5">
          <h2 className="mb-4 text-sm font-semibold text-white">Schedule &amp; thresholds</h2>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <div>
              <label className="label" htmlFor="interval_seconds">
                Check interval
              </label>
              <select id="interval_seconds" className="input" value={form.interval_seconds} onChange={set('interval_seconds')}>
                {INTERVAL_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              {fieldError('interval_seconds')}
            </div>
            <div>
              <label className="label" htmlFor="timeout_seconds">
                Timeout (seconds)
              </label>
              <input
                id="timeout_seconds"
                type="number"
                min={1}
                max={120}
                step={1}
                className="input"
                value={form.timeout_seconds}
                onChange={set('timeout_seconds')}
              />
              {fieldError('timeout_seconds')}
            </div>
            <div>
              <label className="label" htmlFor="latency_threshold_ms">
                Latency threshold (ms)
              </label>
              <input
                id="latency_threshold_ms"
                type="number"
                min={0}
                step={100}
                className="input"
                value={form.latency_threshold_ms}
                onChange={set('latency_threshold_ms')}
              />
              {fieldError('latency_threshold_ms')}
              <p className="mt-1 text-xs text-slate-500">Slower responses raise an anomaly.</p>
            </div>
            <div>
              <label className="label" htmlFor="max_response_size_bytes">
                Max response size (bytes)
              </label>
              <input
                id="max_response_size_bytes"
                type="number"
                min={1}
                step={1024}
                className="input"
                value={form.max_response_size_bytes}
                onChange={set('max_response_size_bytes')}
              />
              {fieldError('max_response_size_bytes')}
            </div>
          </div>
        </section>

        {/* Response expectations */}
        <section className="card p-5">
          <h2 className="mb-4 text-sm font-semibold text-white">Response expectations</h2>
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <div>
              <label className="label" htmlFor="expected_status_codes">
                Expected status codes *
              </label>
              <input
                id="expected_status_codes"
                className="input font-mono"
                placeholder="200, 201"
                value={form.expected_status_codes}
                onChange={set('expected_status_codes')}
              />
              {fieldError('expected_status_codes')}
              <p className="mt-1 text-xs text-slate-500">Comma-separated. Any other code raises an anomaly.</p>
            </div>
            <div>
              <label className="label" htmlFor="expected_fields">
                Expected JSON fields
              </label>
              <input
                id="expected_fields"
                className="input font-mono"
                placeholder="id, title"
                value={form.expected_fields}
                onChange={set('expected_fields')}
              />
              <p className="mt-1 text-xs text-slate-500">Comma-separated. Missing fields raise an anomaly.</p>
            </div>
            <label className="flex cursor-pointer items-start gap-2.5 md:col-span-2">
              <input
                type="checkbox"
                checked={form.check_zero_records}
                onChange={set('check_zero_records')}
                className="mt-0.5 h-4 w-4 rounded border-ink-700 bg-ink-800 accent-emerald-500"
              />
              <span>
                <span className="block text-sm font-medium text-slate-200">Alert when zero records are returned</span>
                <span className="block text-xs text-slate-500">
                  For list endpoints: raise an anomaly when the JSON array is empty.
                </span>
              </span>
            </label>
          </div>
        </section>

        <div className="flex flex-wrap items-center justify-end gap-2">
          <Link to="/monitors" className="btn-secondary">
            Cancel
          </Link>
          <button type="submit" className="btn-primary" disabled={saving}>
            {saving ? 'Saving…' : isEdit ? 'Save changes' : 'Create monitor'}
          </button>
        </div>
      </form>
    </div>
  )
}
