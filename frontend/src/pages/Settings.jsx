import { useEffect, useState } from 'react'
import { CheckCircle2, Eye, EyeOff, Info, Save, Send, Trash2, XCircle } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import {
  apiErrorMessage,
  changePassword,
  cleanupHistory,
  getCleanupPreview,
  getSettings,
  testNotification,
  updateSettings,
} from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../components/Toast'
import { ErrorState, LoadingSkeleton, PageHeader } from '../components/Cards'
import { formatNumber } from '../utils/format'

const INTERVAL_OPTIONS = [
  { value: 30, label: 'Every 30 seconds' },
  { value: 60, label: 'Every 1 minute' },
  { value: 300, label: 'Every 5 minutes' },
  { value: 900, label: 'Every 15 minutes' },
  { value: 1800, label: 'Every 30 minutes' },
]

const SEVERITY_OPTIONS = [
  { value: 'warning', label: 'Warning' },
  { value: 'high', label: 'High' },
  { value: 'critical', label: 'Critical' },
]

function settingsToForm(data) {
  return {
    default_interval_seconds: data.default_interval_seconds,
    default_timeout_seconds: data.default_timeout_seconds,
    default_latency_threshold_ms: data.default_latency_threshold_ms,
    max_concurrency: data.max_concurrency,
    telegram_enabled: data.telegram_enabled ?? false,
    telegram_min_severity: data.telegram_min_severity || 'warning',
    telegram_chat_id: data.telegram_chat_id || '',
    // Never pre-filled: the stored token is never returned. Empty means "keep".
    telegram_bot_token: '',
    retention_days: data.retention_days ?? 90,
    alert_retention_days: data.alert_retention_days ?? 365,
  }
}

export function Settings() {
  const toast = useToast()
  const { updateToken } = useAuth()
  const settings = useApi(getSettings, [], { initialData: null })
  const preview = useApi(getCleanupPreview, [], { initialData: null })
  const [form, setForm] = useState(null)
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [cleaning, setCleaning] = useState(false)

  // Change password form (independent of the settings form).
  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmNewPassword, setConfirmNewPassword] = useState('')
  const [showCurrentPassword, setShowCurrentPassword] = useState(false)
  const [showNewPassword, setShowNewPassword] = useState(false)
  const [showConfirmNewPassword, setShowConfirmNewPassword] = useState(false)
  const [passwordError, setPasswordError] = useState(null)
  const [changingPassword, setChangingPassword] = useState(false)

  // Delayed skeleton: only show the loading placeholder if the fetch takes
  // longer than ~250ms, so fast loads render straight into content with no
  // flash, while genuinely slow loads still show feedback.
  const [showSkeleton, setShowSkeleton] = useState(false)
  useEffect(() => {
    if (!settings.loading || settings.data) {
      setShowSkeleton(false)
      return
    }
    const t = setTimeout(() => setShowSkeleton(true), 250)
    return () => clearTimeout(t)
  }, [settings.loading, settings.data])

  useEffect(() => {
    if (settings.data && !form) {
      setForm(settingsToForm(settings.data))
    }
  }, [settings.data, form])

  const set = (field) => (e) => {
    const value = e.target.type === 'checkbox' ? e.target.checked : e.target.value
    setForm((f) => ({ ...f, [field]: value }))
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
    const retention = Number(form.retention_days)
    if (!Number.isInteger(retention) || retention < 7 || retention > 365) {
      errs.retention_days = 'Check history retention must be a whole number between 7 and 365 days.'
    }
    const alertRetention = Number(form.alert_retention_days)
    if (!Number.isInteger(alertRetention) || alertRetention < 30 || alertRetention > 1095) {
      errs.alert_retention_days = 'Resolved alert retention must be a whole number between 30 and 1095 days.'
    }
    if (!SEVERITY_OPTIONS.some((o) => o.value === form.telegram_min_severity)) {
      errs.telegram_min_severity = 'Choose one of the available severities.'
    }
    setErrors(errs)
    if (Object.keys(errs).length > 0) {
      toast.error('Please fix the highlighted fields.')
      return
    }

    setSaving(true)
    try {
      const payload = {
        default_interval_seconds: Number(form.default_interval_seconds),
        default_timeout_seconds: timeout,
        default_latency_threshold_ms: latency,
        max_concurrency: concurrency,
        telegram_enabled: !!form.telegram_enabled,
        telegram_min_severity: form.telegram_min_severity,
        telegram_chat_id: form.telegram_chat_id.trim(),
        retention_days: retention,
        alert_retention_days: alertRetention,
      }
      // Only send a token the user actually typed; an empty field keeps the stored one.
      if (form.telegram_bot_token) {
        payload.telegram_bot_token = form.telegram_bot_token
      }
      const updated = await updateSettings(payload)
      setForm(settingsToForm(updated))
      settings.refetch()
      preview.refetch()
      toast.success('Settings saved.')
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not save settings'))
    } finally {
      setSaving(false)
    }
  }

  const handleTestNotification = async () => {
    setTesting(true)
    try {
      const result = await testNotification()
      if (result?.success) {
        toast.success(result.detail || 'Test notification sent.')
      } else {
        toast.error(result?.detail || 'Test notification failed.')
      }
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not send test notification'))
    } finally {
      setTesting(false)
    }
  }

  const handleCleanup = async () => {
    setCleaning(true)
    try {
      const result = await cleanupHistory()
      toast.success(
        `Deleted ${formatNumber(result.records_deleted ?? 0)} records, ` +
          `${formatNumber(result.alerts_deleted ?? 0)} alerts, ` +
          `${formatNumber(result.anomalies_deleted ?? 0)} anomalies.`
      )
      preview.refetch()
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not clean up history'))
    } finally {
      setCleaning(false)
    }
  }

  const handleChangePassword = async (e) => {
    e.preventDefault()
    setPasswordError(null)
    if (newPassword.length < 8) {
      setPasswordError('New password must be at least 8 characters.')
      return
    }
    if (newPassword !== confirmNewPassword) {
      setPasswordError('Passwords do not match.')
      return
    }
    setChangingPassword(true)
    try {
      // The API returns a fresh token (the old one is invalidated
      // server-side) — swap it in so the session stays alive.
      const result = await changePassword({
        current_password: currentPassword,
        new_password: newPassword,
      })
      if (result?.access_token) updateToken(result.access_token)
      setCurrentPassword('')
      setNewPassword('')
      setConfirmNewPassword('')
      toast.success('Password changed successfully. Other sessions have been signed out.')
    } catch (err) {
      // A 401 here means the current password was wrong — the session
      // itself is fine (the 401 interceptor skips this endpoint).
      if (err?.response?.status === 401) {
        setPasswordError('Current password is incorrect.')
      } else {
        setPasswordError(apiErrorMessage(err, 'Could not change your password — please try again.'))
      }
    } finally {
      setChangingPassword(false)
    }
  }

  if (settings.loading && !settings.data) {
    return (
      <div>
        <PageHeader title="Settings" description="Defaults applied to new monitors" />
        {showSkeleton && <LoadingSkeleton rows={5} />}
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
  const telegramConfigured = !!s.telegram_configured
  const fieldError = (field) =>
    errors[field] ? <p className="mt-1 text-xs text-red-600">{errors[field]}</p> : null

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Monitor defaults, notifications, and data retention"
      />

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <form onSubmit={handleSave} className="xl:col-span-2" noValidate>
          <div className="space-y-6">
            {/* Monitor defaults */}
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
            </div>

            {/* Telegram notifications */}
            <div className="card p-5">
              <h2 className="mb-1 text-sm font-semibold text-zinc-900">Telegram notifications</h2>
              <p className="mb-5 text-xs text-zinc-500">
                Send alert notifications to a Telegram chat.
              </p>
              <div className="space-y-4">
                <label className="flex cursor-pointer items-start gap-2.5">
                  <input
                    type="checkbox"
                    checked={form?.telegram_enabled ?? false}
                    onChange={set('telegram_enabled')}
                    className="mt-0.5 h-4 w-4 rounded border-zinc-300 accent-zinc-900"
                  />
                  <span>
                    <span className="block text-sm font-medium text-zinc-900">Enable Telegram notifications</span>
                    <span className="block text-xs text-zinc-500">
                      Alerts are sent to the configured chat when enabled.
                    </span>
                  </span>
                </label>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label className="label" htmlFor="telegram_bot_token">
                      Bot token
                    </label>
                    <input
                      id="telegram_bot_token"
                      type="password"
                      className="input font-mono"
                      placeholder="123456:ABC-DEF…"
                      value={form?.telegram_bot_token ?? ''}
                      onChange={set('telegram_bot_token')}
                      autoComplete="off"
                    />
                    <p className="mt-1 flex items-center gap-1.5 text-xs text-zinc-500">
                      {telegramConfigured ? (
                        <>
                          <CheckCircle2 className="h-3.5 w-3.5 text-green-600" />
                          Configured — leave empty to keep the stored token.
                        </>
                      ) : (
                        'The stored token is never shown.'
                      )}
                    </p>
                  </div>
                  <div>
                    <label className="label" htmlFor="telegram_chat_id">
                      Chat ID
                    </label>
                    <input
                      id="telegram_chat_id"
                      type="text"
                      className="input font-mono"
                      placeholder="123456789"
                      value={form?.telegram_chat_id ?? ''}
                      onChange={set('telegram_chat_id')}
                      autoComplete="off"
                    />
                    <p className="mt-1 text-xs text-zinc-500">
                      The chat or group that receives notifications.
                    </p>
                  </div>
                  <div>
                    <label className="label" htmlFor="telegram_min_severity">
                      Minimum severity
                    </label>
                    <select
                      id="telegram_min_severity"
                      className="input"
                      value={form?.telegram_min_severity ?? 'warning'}
                      onChange={set('telegram_min_severity')}
                    >
                      {SEVERITY_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                    {fieldError('telegram_min_severity')}
                    <p className="mt-1 text-xs text-zinc-500">
                      Only alerts at or above this severity send a notification.
                    </p>
                  </div>
                </div>
                <p className="text-xs text-zinc-500">
                  Create a bot with @BotFather, message it once, then get your chat ID from getUpdates.
                </p>
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    type="button"
                    className="btn-secondary"
                    onClick={handleTestNotification}
                    disabled={testing || !telegramConfigured}
                  >
                    <Send className="h-4 w-4" />
                    {testing ? 'Sending…' : 'Send test notification'}
                  </button>
                  {!telegramConfigured && (
                    <p className="text-xs text-zinc-500">
                      Save a bot token and chat ID first to enable the test.
                    </p>
                  )}
                </div>
              </div>
            </div>

            {/* Data retention */}
            <div className="card p-5">
              <h2 className="mb-1 text-sm font-semibold text-zinc-900">Data retention</h2>
              <p className="mb-5 text-xs text-zinc-500">
                Old data is deleted automatically after the retention period.
              </p>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <div>
                  <label className="label" htmlFor="retention_days">
                    Check history retention (days)
                  </label>
                  <input
                    id="retention_days"
                    type="number"
                    min={7}
                    max={365}
                    step={1}
                    className="input"
                    value={form?.retention_days ?? 90}
                    onChange={set('retention_days')}
                  />
                  {fieldError('retention_days')}
                  <p className="mt-1 text-xs text-zinc-500">
                    Check records and their anomalies older than this are deleted.
                  </p>
                </div>
                <div>
                  <label className="label" htmlFor="alert_retention_days">
                    Resolved alert retention (days)
                  </label>
                  <input
                    id="alert_retention_days"
                    type="number"
                    min={30}
                    max={1095}
                    step={1}
                    className="input"
                    value={form?.alert_retention_days ?? 365}
                    onChange={set('alert_retention_days')}
                  />
                  {fieldError('alert_retention_days')}
                  <p className="mt-1 text-xs text-zinc-500">
                    Resolved alerts older than this are deleted. Active alerts are kept.
                  </p>
                </div>
              </div>
              <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-zinc-100 pt-5">
                <button
                  type="button"
                  className="btn-secondary"
                  onClick={handleCleanup}
                  disabled={cleaning}
                >
                  <Trash2 className="h-4 w-4" />
                  {cleaning ? 'Cleaning up…' : 'Clean up now'}
                </button>
                {preview.data && (
                  <p className="text-xs text-zinc-500">
                    Ready to delete: {formatNumber(preview.data.records_deleted ?? 0)} records,{' '}
                    {formatNumber(preview.data.alerts_deleted ?? 0)} alerts,{' '}
                    {formatNumber(preview.data.anomalies_deleted ?? 0)} anomalies.
                  </p>
                )}
              </div>
            </div>

            <div className="flex justify-end">
              <button type="submit" className="btn-primary" disabled={saving}>
                <Save className="h-4 w-4" />
                {saving ? 'Saving…' : 'Save settings'}
              </button>
            </div>
          </div>
        </form>

        <div className="space-y-6">
          {/* Security */}
          <div className="card h-fit p-5" id="security">
            <h2 className="mb-1 text-sm font-semibold text-zinc-900">Security</h2>
            <p className="mb-5 text-xs text-zinc-500">
              Change your password. Other sessions are signed out when you do.
            </p>
            <form onSubmit={handleChangePassword} className="space-y-4" noValidate>
              {passwordError && (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                  {passwordError}
                </div>
              )}
              <div>
                <label className="label" htmlFor="current_password">
                  Current password
                </label>
                <div className="relative">
                  <input
                    id="current_password"
                    type={showCurrentPassword ? 'text' : 'password'}
                    className="input pr-10"
                    value={currentPassword}
                    onChange={(e) => setCurrentPassword(e.target.value)}
                    required
                    autoComplete="current-password"
                  />
                  <button
                    type="button"
                    className="absolute inset-y-0 right-0 flex items-center px-3 text-zinc-400 hover:text-zinc-700"
                    onClick={() => setShowCurrentPassword((v) => !v)}
                    aria-label={showCurrentPassword ? 'Hide password' : 'Show password'}
                    tabIndex={-1}
                  >
                    {showCurrentPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <div>
                <label className="label" htmlFor="new_password">
                  New password
                </label>
                <div className="relative">
                  <input
                    id="new_password"
                    type={showNewPassword ? 'text' : 'password'}
                    className="input pr-10"
                    value={newPassword}
                    onChange={(e) => setNewPassword(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="absolute inset-y-0 right-0 flex items-center px-3 text-zinc-400 hover:text-zinc-700"
                    onClick={() => setShowNewPassword((v) => !v)}
                    aria-label={showNewPassword ? 'Hide password' : 'Show password'}
                    tabIndex={-1}
                  >
                    {showNewPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
                <p className="mt-1 text-xs text-zinc-500">At least 8 characters.</p>
              </div>
              <div>
                <label className="label" htmlFor="confirm_new_password">
                  Confirm new password
                </label>
                <div className="relative">
                  <input
                    id="confirm_new_password"
                    type={showConfirmNewPassword ? 'text' : 'password'}
                    className="input pr-10"
                    value={confirmNewPassword}
                    onChange={(e) => setConfirmNewPassword(e.target.value)}
                    required
                    minLength={8}
                    autoComplete="new-password"
                  />
                  <button
                    type="button"
                    className="absolute inset-y-0 right-0 flex items-center px-3 text-zinc-400 hover:text-zinc-700"
                    onClick={() => setShowConfirmNewPassword((v) => !v)}
                    aria-label={showConfirmNewPassword ? 'Hide password' : 'Show password'}
                    tabIndex={-1}
                  >
                    {showConfirmNewPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </div>
              <div className="flex justify-end">
                <button type="submit" className="btn-primary" disabled={changingPassword}>
                  {changingPassword ? 'Changing…' : 'Change password'}
                </button>
              </div>
            </form>
          </div>

          {/* Server status (read-only) */}
          <div className="card h-fit p-5">
            <h2 className="mb-4 text-sm font-semibold text-zinc-900">Server status</h2>
            <dl className="space-y-4 text-sm">
              <div className="flex items-start justify-between gap-3">
                <dt className="shrink-0 whitespace-nowrap text-zinc-500">AI explanations</dt>
                <dd className="text-right">
                  {s.ai_configured ? (
                    <span className="inline-flex items-center gap-1.5 font-medium text-green-600">
                      <CheckCircle2 className="h-4 w-4" />
                      Configured ({s.ai_provider === 'gemini' ? 'Gemini' : 'OpenRouter'})
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1.5 font-medium text-amber-600">
                      <XCircle className="h-4 w-4" />
                      Not configured
                    </span>
                  )}
                  <span className="mt-0.5 block text-[11px] text-zinc-400">
                    {s.ai_configured
                      ? 'Alerts include AI-generated explanations.'
                      : 'Alerts use deterministic templates until an AI provider key is set.'}
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
    </div>
  )
}
