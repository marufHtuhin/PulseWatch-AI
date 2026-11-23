import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  ArrowLeft,
  Bell,
  Clock,
  ExternalLink,
  Gauge,
  Pause,
  Pencil,
  Play,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { useApi } from '../hooks/useApi'
import {
  apiErrorMessage,
  checkMonitorNow,
  deleteMonitor,
  getDashboardHealth,
  getMonitor,
  listAlerts,
  listMonitorHistory,
  toggleMonitor,
} from '../api/client'
import { useToast } from '../components/Toast'
import { ChartCard, EmptyState, ErrorState, LoadingSkeleton, PageHeader } from '../components/Cards'
import { MethodBadge, StatusBadge } from '../components/Badges'
import { AlertRowCompact } from '../components/AlertRow'
import { ResponseTimeChart, StatusHistory } from '../components/Charts'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Pagination } from '../components/Controls'
import {
  anomalyLabel,
  formatBytes,
  formatDate,
  formatDateTime,
  formatInterval,
  formatMs,
  formatNumber,
  timeAgo,
} from '../utils/format'

const HISTORY_PAGE_SIZE = 10

export function MonitorDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const historyPage = Number(searchParams.get('page') || 1)

  const [checking, setChecking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const monitor = useApi(() => getMonitor(id), [id], { pollIntervalMs: 30000 })
  const history = useApi(
    () => listMonitorHistory(id, { page: historyPage, page_size: HISTORY_PAGE_SIZE }),
    [id, historyPage],
    { pollIntervalMs: 30000 }
  )
  // Recent history for charts/status strip (latest 40 checks, regardless of table page).
  const chartHistory = useApi(
    () => listMonitorHistory(id, { page: 1, page_size: 40 }),
    [id],
    { pollIntervalMs: 30000 }
  )
  const relatedAlerts = useApi(
    () => listAlerts({ monitor_id: id, page: 1, page_size: 10 }),
    [id],
    { pollIntervalMs: 30000 }
  )
  // Per-monitor P95 latency comes from the existing dashboard health endpoint.
  const health = useApi(getDashboardHealth, [], { pollIntervalMs: 30000 })

  const m = monitor.data
  const records = history.data?.items || []
  const chartRecords = chartHistory.data?.items || []
  const alerts = relatedAlerts.data?.items || []
  const healthItem = useMemo(
    () => (health.data?.monitors || []).find((h) => h.monitor_id === m?.id),
    [health.data, m?.id]
  )

  // Anomalies are embedded in the check-now response and in history records
  // when the backend includes them; derive the visible list from recent records.
  const anomalies = useMemo(() => {
    const seen = new Map()
    for (const r of chartRecords) {
      for (const a of r.anomalies || []) {
        if (!seen.has(a.id)) seen.set(a.id, { ...a, record: r })
      }
    }
    return [...seen.values()].sort((a, b) => new Date(b.detected_at) - new Date(a.detected_at))
  }, [chartRecords])

  const handleCheckNow = async () => {
    if (!m) return
    setChecking(true)
    try {
      const record = await checkMonitorNow(m.id)
      const anomaliesCount = record?.anomalies?.length || 0
      if (record?.is_success) {
        toast.success(
          `Check OK (${record.status_code}, ${formatMs(record.response_time_ms)})` +
            (anomaliesCount ? ` — ${anomaliesCount} anomal${anomaliesCount === 1 ? 'y' : 'ies'} detected` : '')
        )
      } else {
        toast.error(
          `Check failed${record?.status_code ? ` (${record.status_code})` : ''}${record?.error_message ? ` — ${record.error_message}` : ''}`
        )
      }
      monitor.refetch()
      history.refetch()
      chartHistory.refetch()
      relatedAlerts.refetch()
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Check failed'))
    } finally {
      setChecking(false)
    }
  }

  const handleToggle = async () => {
    if (!m) return
    setBusy(true)
    try {
      const updated = await toggleMonitor(m.id)
      toast.success(updated.is_active ? 'Monitoring resumed.' : 'Monitoring paused.')
      monitor.refetch()
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not change monitor state'))
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!m) return
    setDeleting(true)
    try {
      await deleteMonitor(m.id)
      toast.success(`Deleted monitor "${m.name}" and its history.`)
      navigate('/monitors')
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not delete monitor'))
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  if (monitor.loading && !m) {
    return (
      <div>
        <PageHeader title="Monitor" />
        <LoadingSkeleton rows={6} />
      </div>
    )
  }

  if (monitor.error) {
    return (
      <div>
        <PageHeader title="Monitor" />
        <div className="card">
          <ErrorState message={monitor.error} onRetry={monitor.refetch} />
        </div>
        <Link to="/monitors" className="btn-secondary mt-4">
          <ArrowLeft className="h-4 w-4" />
          Back to monitors
        </Link>
      </div>
    )
  }

  const headerNames = Object.keys(m.headers || {})

  // SSL certificate: only https monitors carry expiry data.
  const certDays = m.cert_days_remaining
  let sslValue = '—'
  if (m.cert_expires_at) {
    const label =
      certDays == null
        ? `Expires ${formatDate(m.cert_expires_at)}`
        : `Expires ${formatDate(m.cert_expires_at)} (${certDays} ${certDays === 1 ? 'day' : 'days'})`
    if (certDays != null && certDays < 0) {
      sslValue = <span className="font-medium text-red-600">Expired {formatDate(m.cert_expires_at)}</span>
    } else if (certDays != null && certDays < 30) {
      sslValue = <span className="font-medium text-amber-600">{label}</span>
    } else {
      sslValue = label
    }
  }

  return (
    <div>
      <PageHeader
        title={m.name}
        description={
          <span className="flex flex-wrap items-center gap-2">
            <MethodBadge method={m.method} />
            <a href={m.url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 break-all font-mono text-zinc-500 hover:text-blue-600">
              {m.url}
              <ExternalLink className="h-3 w-3 shrink-0" />
            </a>
          </span>
        }
        actions={
          <>
            <Link to="/monitors" className="btn-secondary">
              <ArrowLeft className="h-4 w-4" />
              All monitors
            </Link>
            <button className="btn-secondary" onClick={handleCheckNow} disabled={checking || busy}>
              <RefreshCw className={`h-4 w-4 ${checking ? 'animate-spin' : ''}`} />
              Check now
            </button>
            <Link to={`/monitors/${m.id}/edit`} className="btn-secondary">
              <Pencil className="h-4 w-4" />
              Edit
            </Link>
            <button className="btn-secondary" onClick={handleToggle} disabled={busy}>
              {m.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              {m.is_active ? 'Pause' : 'Resume'}
            </button>
            <button className="btn-danger" onClick={() => setConfirmDelete(true)} disabled={busy}>
              <Trash2 className="h-4 w-4" />
              Delete
            </button>
          </>
        }
      />

      {/* Status summary strip */}
      <div className="card mb-6 grid grid-cols-2 gap-4 p-4 sm:grid-cols-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">Status</p>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <StatusBadge status={m.last_status} />
            {!m.is_active && <span className="badge bg-zinc-100 text-zinc-500">Paused</span>}
          </div>
        </div>
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">Last response</p>
          <p className="mt-2 flex items-center gap-1.5 text-lg font-semibold tracking-tight text-zinc-900">
            <Gauge className="h-4 w-4 text-zinc-400" />
            <span className="font-mono tabular-nums">{formatMs(m.last_response_time_ms)}</span>
            <span className="font-mono text-sm font-normal text-zinc-400">
              {m.last_status_code ? `(${m.last_status_code})` : ''}
            </span>
          </p>
          <p className="mt-1 text-xs text-zinc-400">
            P95 <span className="font-mono tabular-nums">{formatMs(healthItem?.p95_response_time_ms)}</span>
          </p>
        </div>
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">Last checked</p>
          <p className="mt-2 flex items-center gap-1.5 text-lg font-semibold tracking-tight text-zinc-900">
            <Clock className="h-4 w-4 text-zinc-400" />
            {timeAgo(m.last_checked_at)}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">Active alerts</p>
          <p className="mt-2 flex items-center gap-1.5 text-lg font-semibold tracking-tight text-zinc-900">
            <Bell className="h-4 w-4 text-zinc-400" />
            <span className="font-mono tabular-nums">{formatNumber(alerts.filter((a) => a.status !== 'resolved').length)}</span>
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-3">
        <div className="space-y-6 xl:col-span-2">
          {/* Response time chart */}
          <ChartCard title="Response time" subtitle="Last 40 checks">
            {chartHistory.loading && !chartHistory.data ? (
              <div className="h-[280px] animate-pulse rounded-lg bg-zinc-200/50" />
            ) : chartHistory.error ? (
              <ErrorState message={chartHistory.error} onRetry={chartHistory.refetch} />
            ) : (
              <ResponseTimeChart points={chartRecords} singleSeries latencyThresholdMs={m.latency_threshold_ms} />
            )}
          </ChartCard>

          {/* Status history strip */}
          <ChartCard title="Check history" subtitle="Each bar is one check — green passed, red failed">
            {chartHistory.loading && !chartHistory.data ? (
              <div className="h-8 animate-pulse rounded bg-zinc-200/50" />
            ) : (
              <StatusHistory records={chartRecords} />
            )}
          </ChartCard>

          {/* Monitoring history table */}
          <ChartCard title="Monitoring history" subtitle="Every recorded check for this monitor">
            {history.loading && !history.data ? (
              <LoadingSkeleton rows={5} />
            ) : history.error ? (
              <ErrorState message={history.error} onRetry={history.refetch} />
            ) : records.length === 0 ? (
              <EmptyState
                title="No checks recorded yet"
                description="Run a check now or wait for the next scheduled check."
                action={
                  <button className="btn-primary" onClick={handleCheckNow} disabled={checking}>
                    <RefreshCw className={`h-4 w-4 ${checking ? 'animate-spin' : ''}`} />
                    Run a check now
                  </button>
                }
              />
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[560px] border-collapse">
                    <thead>
                      <tr className="border-b border-zinc-200">
                        <th className="th">Checked at</th>
                        <th className="th">Result</th>
                        <th className="th">Response</th>
                        <th className="th">Size</th>
                        <th className="th">Records</th>
                        <th className="th">Error</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((r) => (
                        <tr key={r.id} className="border-b border-zinc-100 last:border-0 hover:bg-zinc-50">
                          <td className="td whitespace-nowrap font-mono text-xs">{formatDateTime(r.checked_at)}</td>
                          <td className="td">
                            {r.is_success ? (
                              <span className="text-green-600">Success</span>
                            ) : (
                              <span className="text-red-600">Failed</span>
                            )}
                          </td>
                          <td className="td font-mono tabular-nums">
                            {r.status_code ?? '—'} · {formatMs(r.response_time_ms)}
                          </td>
                          <td className="td">{formatBytes(r.response_size_bytes)}</td>
                          <td className="td font-mono tabular-nums">{r.records_returned ?? '—'}</td>
                          <td className="td max-w-[220px] truncate text-zinc-400" title={r.error_message || ''}>
                            {r.error_message || '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <Pagination
                  page={historyPage}
                  pageSize={HISTORY_PAGE_SIZE}
                  total={history.data?.total ?? 0}
                  onPageChange={(p) => {
                    const next = new URLSearchParams(searchParams)
                    next.set('page', String(p))
                    setSearchParams(next, { replace: true })
                  }}
                />
              </>
            )}
          </ChartCard>
        </div>

        <div className="space-y-6">
          {/* Config summary */}
          <ChartCard title="Configuration">
            <dl className="space-y-3 text-sm">
              <ConfigRow label="Method" value={<MethodBadge method={m.method} />} />
              <ConfigRow label="Interval" value={formatInterval(m.interval_seconds)} />
              <ConfigRow label="Timeout" value={`${m.timeout_seconds}s`} />
              <ConfigRow label="Expected codes" value={(m.expected_status_codes || []).join(', ') || '—'} mono />
              <ConfigRow label="Latency threshold" value={formatMs(m.latency_threshold_ms)} />
              <ConfigRow label="Max response size" value={formatBytes(m.max_response_size_bytes)} />
              <ConfigRow
                label="Expected JSON fields"
                value={(m.expected_fields || []).length ? m.expected_fields.join(', ') : 'None'}
                mono
              />
              <ConfigRow label="Zero-records check" value={m.check_zero_records ? 'Enabled' : 'Disabled'} />
              <ConfigRow
                label="Alert after failures"
                value={`${m.alert_after_failures ?? 2} consecutive ${(m.alert_after_failures ?? 2) === 1 ? 'failure' : 'failures'}`}
              />
              <ConfigRow label="SSL certificate" value={sslValue} />
              <ConfigRow
                label="Headers"
                value={headerNames.length ? headerNames.join(', ') : 'None'}
                mono
                hint={headerNames.length ? 'Values are never displayed.' : undefined}
              />
              <ConfigRow label="Created" value={formatDateTime(m.created_at)} />
              <ConfigRow label="Updated" value={formatDateTime(m.updated_at)} />
            </dl>
          </ChartCard>

          {/* Anomalies */}
          <ChartCard title="Recent anomalies" subtitle="From the last 40 checks">
            {anomalies.length === 0 ? (
              <p className="py-2 text-sm text-zinc-500">No anomalies detected in recent checks.</p>
            ) : (
              <ul className="space-y-3">
                {anomalies.slice(0, 8).map((a) => (
                  <li key={a.id} className="rounded-md border border-zinc-200 bg-zinc-50 p-3">
                    <p className="text-sm font-medium text-zinc-900">{anomalyLabel(a.anomaly_type)}</p>
                    {a.description && <p className="mt-0.5 text-xs leading-relaxed text-zinc-500">{a.description}</p>}
                    <p className="mt-1.5 text-xs text-zinc-400">
                      {a.severity} · {timeAgo(a.detected_at)}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </ChartCard>

          {/* Related alerts */}
          <ChartCard
            title="Related alerts"
            subtitle="Alerts raised for this monitor"
            action={
              <Link to={`/alerts?monitor_id=${m.id}`} className="text-xs font-medium text-blue-600 hover:text-blue-700">
                View all →
              </Link>
            }
          >
            {relatedAlerts.loading && !relatedAlerts.data ? (
              <LoadingSkeleton rows={3} />
            ) : relatedAlerts.error ? (
              <ErrorState message={relatedAlerts.error} onRetry={relatedAlerts.refetch} />
            ) : alerts.length === 0 ? (
              <p className="py-2 text-sm text-zinc-500">No alerts for this monitor.</p>
            ) : (
              <div className="-mx-3 divide-y divide-zinc-100">
                {alerts.map((a) => (
                  <AlertRowCompact key={a.id} alert={a} />
                ))}
              </div>
            )}
          </ChartCard>
        </div>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title={`Delete "${m.name}"?`}
        message="This permanently deletes the monitor and all of its monitoring history, anomalies, and alerts. This cannot be undone."
        confirmLabel="Delete monitor"
        danger
        loading={deleting}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  )
}

function ConfigRow({ label, value, mono = false, hint }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="shrink-0 text-zinc-500">{label}</dt>
      <dd className={`text-right text-zinc-900 ${mono ? 'break-all font-mono text-xs leading-relaxed' : ''}`}>
        {value}
        {hint && <span className="mt-0.5 block text-[11px] font-sans text-zinc-400">{hint}</span>}
      </dd>
    </div>
  )
}
