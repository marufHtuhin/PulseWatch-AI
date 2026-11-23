import { useEffect, useState } from 'react'
import { CheckCircle2, Info, Save, XCircle } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { apiErrorMessage, getSettings, updateSettings } from '../api/client'
import { useToast } from '../components/Toast'
import { ErrorState, LoadingSkeleton, PageHeader } from '../components/Cards'

const INTERVAL_OPTIONS = [
  { value: 30, label: 'Every 30 seconds' },
  { value: 60, label: 'Every 1 minute' },
  { value: 300, label: 'Every 5 minutes' },
  { value: 900, label: 'Every 15 minutes' },
  { value: 1800, label: 'Every 30 minutes' },
]

export function Settings() {
  const toast = useToast()
  const settings = useApi(getSettings, [], { initialData: null })
  const [form, setForm] = useState(null)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (settings.data && !form) {
      setForm({
        default_interval_seconds: settings.data.default_interval_seconds,
        default_timeout_seconds: settings.data.default_timeout_seconds,
        default_latency_threshold_ms: settings.data.default_latency_threshold_ms,
        max_concurrency: settings.data.max_concurrency,
      })
    }
  }, [settings.data, form])

  const set = (field) => (e) => {
    setForm((f) => ({ ...f, [field]: e.target.value }))
    setErrors((prev) => ({ ...prev, [field]: undefined }))
  }

  const handleSave = async (e) => {
    e.preventDefault()
    const errs = {}
    const timeout = Number(form.default_timeout_seconds)
    if (!Number.isFinite(timeout) || timeout < 1 || timeout > 120) {
      errs.default_timeout_seconds = 'Timeout must be between 1 and 120 seconds.'
    }
    const latency = Number(form.default_latency_threshold_ms)
    if (!Number.isFinite(latency) || latency < 0) {
      errs.default_latency_threshold_ms = 'Latency threshold must be 0 or more milliseconds.'
    }
    const concurrency = Number(form.max_concurrency)
    if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 100) {
      errs.max_concurrency = 'Max concurrency must be a whole number between 1 and 100.'
    }
    if (!INTERVAL_OPTIONS.some((o) => o.value === Number(form.default_interval_seconds))) {
      errs.default_interval_seconds = 'Choose one of the available intervals.'
    }
    setErrors(errs)
    if (Object.keys(errs).length > 0) {
      toast.error('Please fix the highlighted fields.')
      return
    }

    setSaving(true)
    try {
      const updated = await updateSettings({
        default_interval_seconds: Number(form.default_interval_seconds),
        default_timeout_seconds: timeout,
        default_latency_threshold_ms: latency,
        max_concurrency: concurrency,
      })
      setForm({
        default_interval_seconds: updated.default_interval_seconds,
        default_timeout_seconds: updated.default_timeout_seconds,
        default_latency_threshold_ms: updated.default_latency_threshold_ms,
        max_concurrency: updated.max_concurrency,
      })
      toast.success('Settings saved.')
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not save settings'))
    } finally {
      setSaving(false)
    }
  }

  if (settings.loading && !settings.data) {
    return (
      <div>
        <PageHeader title="Settings" description="Defaults applied to new monitors" />
        <LoadingSkeleton rows={5} />
      </div>
    )
  }

  if (settings.error) {
    return (
      <div>
        <PageHeader title="Settings" description="Defaults applied to new monitors" />
        <div className="card">
          <ErrorState message={settings.error} onRetry={settings.refetch} />
        </div>
      </div>
    )
  }

  const s = settings.data
  const fieldError = (field) =>
    errors[field] ? <p className="mt-1 text-xs text-red-600">{errors[field]}</p> : null

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Defaults applied to new monitors, plus server status"
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <form onSubmit={handleSave} className="xl:col-span-2" noValidate>
          <div className="card p-5">
            <h2 className="mb-1 text-sm font-semibold text-zinc-900">Monitor defaults</h2>
            <p className="mb-5 text-xs text-zinc-500">
              These values pre-fill the form when you create a new monitor. Existing monitors are not changed.
            </p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="label" htmlFor="default_interval_seconds">
                  Default check interval
                </label>
                <select
                  id="default_interval_seconds"
                  className="input"
                  value={form?.default_interval_seconds ?? 300}
                  onChange={set('default_interval_seconds')}
                >
                  {INTERVAL_OPTIONS.map((o) => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </select>
                {fieldError('default_interval_seconds')}
              </div>
              <div>
                <label className="label" htmlFor="default_timeout_seconds">
                  Default timeout (seconds)
                </label>
                <input
                  id="default_timeout_seconds"
                  type="number"
                  min={1}
                  max={120}
                  step={1}
                  className="input"
                  value={form?.default_timeout_seconds ?? 10}
                  onChange={set('default_timeout_seconds')}
                />
                {fieldError('default_timeout_seconds')}
              </div>
              <div>
                <label className="label" htmlFor="default_latency_threshold_ms">
                  Default latency threshold (ms)
                </label>
                <input
                  id="default_latency_threshold_ms"
                  type="number"
                  min={0}
                  step={100}
                  className="input"
                  value={form?.default_latency_threshold_ms ?? 3000}
                  onChange={set('default_latency_threshold_ms')}
                />
                {fieldError('default_latency_threshold_ms')}
                <p className="mt-1 text-xs text-zinc-500">Responses slower than this raise an anomaly.</p>
              </div>
              <div>
                <label className="label" htmlFor="max_concurrency">
                  Max concurrent checks
                </label>
                <input
                  id="max_concurrency"
                  type="number"
                  min={1}
                  max={100}
                  step={1}
                  className="input"
                  value={form?.max_concurrency ?? 10}
                  onChange={set('max_concurrency')}
                />
                {fieldError('max_concurrency')}
                <p className="mt-1 text-xs text-zinc-500">Upper bound for simultaneous scheduled checks.</p>
              </div>
            </div>
            <div className="mt-6 flex justify-end">
              <button type="submit" className="btn-primary" disabled={saving}>
                <Save className="h-4 w-4" />
                {saving ? 'Saving…' : 'Save settings'}
              </button>
            </div>
          </div>
        </form>

        {/* Server status (read-only) */}
        <div className="card h-fit p-5">
          <h2 className="mb-4 text-sm font-semibold text-zinc-900">Server status</h2>
          <dl className="space-y-4 text-sm">
            <div className="flex items-start justify-between gap-3">
              <dt className="shrink-0 whitespace-nowrap text-zinc-500">Gemini AI</dt>
              <dd className="text-right">
                {s.gemini_configured ? (
                  <span className="inline-flex items-center gap-1.5 font-medium text-green-600">
                    <CheckCircle2 className="h-4 w-4" />
                    Configured
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 font-medium text-amber-600">
                    <XCircle className="h-4 w-4" />
                    Not configured
                  </span>
                )}
                <span className="mt-0.5 block text-[11px] text-zinc-400">
                  {s.gemini_configured
                    ? 'Alerts include AI-generated explanations.'
                    : 'Alerts use deterministic templates until a Gemini key is set.'}
                </span>
              </dd>
            </div>
            <div className="flex items-start justify-between gap-3">
              <dt className="shrink-0 whitespace-nowrap text-zinc-500">Local URLs allowed</dt>
              <dd className="text-right">
                {s.allow_local_urls ? (
                  <span className="inline-flex items-center gap-1.5 font-medium text-amber-600">
                    <Info className="h-4 w-4" />
                    Yes (dev only)
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1.5 font-medium text-green-600">
                    <CheckCircle2 className="h-4 w-4" />
                    No — SSRF protected
                  </span>
                )}
              </dd>
            </div>
            <div className="flex items-start justify-between gap-3">
              <dt className="shrink-0 whitespace-nowrap text-zinc-500">Environment</dt>
              <dd>
                <span className="badge border border-zinc-200 bg-zinc-50 font-mono text-zinc-600">
                  {s.app_env || '—'}
                </span>
              </dd>
            </div>
          </dl>
          <p className="mt-5 border-t border-zinc-200 pt-4 text-xs leading-relaxed text-zinc-400">
            These values are read from the server environment and can&apos;t be changed here.
          </p>
        </div>
      </div>
    </div>
  )
}
