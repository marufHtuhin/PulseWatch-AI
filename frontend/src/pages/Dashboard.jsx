import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity,
  AlarmClock,
  Bell,
  CheckCircle2,
  Clock,
  Gauge,
  MonitorCheck,
  Plus,
  XCircle,
} from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { getDashboardHealth, getDashboardPerformance, getDashboardSummary, listAlerts, listHistory } from '../api/client'
import { ChartCard, EmptyState, ErrorState, LoadingSkeleton, PageHeader, StatCard } from '../components/Cards'
import { ResponseTimeChart } from '../components/Charts'
import { AlertRowCompact } from '../components/AlertRow'
import { StatusBadge } from '../components/Badges'
import { formatMs, formatNumber, formatTimeOnly, formatUptime, timeAgo } from '../utils/format'

const POLL_MS = 30000

const HOUR_OPTIONS = [
  { value: 1, label: 'Last hour' },
  { value: 6, label: 'Last 6 hours' },
  { value: 24, label: 'Last 24 hours' },
  { value: 168, label: 'Last 7 days' },
]

export function Dashboard() {
  const [hours, setHours] = useState(24)

  const summary = useApi(getDashboardSummary, [], { pollIntervalMs: POLL_MS })
  const health = useApi(getDashboardHealth, [], { pollIntervalMs: POLL_MS })
  const performance = useApi(
    () => getDashboardPerformance({ hours }),
    [hours],
    { pollIntervalMs: POLL_MS }
  )
  const recentAlerts = useApi(
    () => listAlerts({ status: 'active', page: 1, page_size: 6 }),
    [],
    { pollIntervalMs: POLL_MS }
  )
  const recentActivity = useApi(
    () => listHistory({ page: 1, page_size: 8 }),
    [],
    { pollIntervalMs: POLL_MS }
  )

  const s = summary.data
  const healthMonitors = useMemo(() => health.data?.monitors || [], [health.data])
  const alerts = useMemo(() => recentAlerts.data?.items || [], [recentAlerts.data])
  const activity = useMemo(() => recentActivity.data?.items || [], [recentActivity.data])
  // Monitoring records carry monitor_id only — resolve names from health data.
  const monitorNameById = useMemo(() => {
    const map = new Map()
    for (const m of healthMonitors) map.set(m.monitor_id, m.name)
    return map
  }, [healthMonitors])

  if (summary.loading && health.loading) {
    return (
      <div>
        <PageHeader title="Dashboard" description="Overview of your API monitoring" />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-[104px] animate-pulse rounded-xl bg-ink-900" />
          ))}
        </div>
        <LoadingSkeleton rows={5} className="mt-6" />
      </div>
    )
  }

  if (summary.error && !s) {
    return (
      <div>
        <PageHeader title="Dashboard" description="Overview of your API monitoring" />
        <div className="card">
          <ErrorState message={summary.error} onRetry={summary.refetch} />
        </div>
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description="Overview of your API monitoring — refreshes every 30 seconds"
        actions={
          <Link to="/monitors/new" className="btn-primary">
            <Plus className="h-4 w-4" />
            Add Monitor
          </Link>
        }
      />

      {/* Stat cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard
          title="Monitors"
          value={formatNumber(s?.total_monitors ?? 0)}
          subtitle={`${formatNumber(s?.active_monitors ?? 0)} active · ${formatNumber(s?.healthy_monitors ?? 0)} healthy · ${formatNumber(s?.unhealthy_monitors ?? 0)} unhealthy`}
          icon={MonitorCheck}
          accent="text-emerald-400"
          loading={summary.loading}
        />
        <StatCard
          title="Overall uptime"
          value={formatUptime(s?.overall_uptime_pct)}
          subtitle={`${formatNumber(s?.total_checks_24h ?? 0)} checks in 24h · ${formatNumber(s?.failed_checks_24h ?? 0)} failed`}
          icon={CheckCircle2}
          accent="text-sky-400"
          loading={summary.loading}
        />
        <StatCard
          title="Avg response time"
          value={formatMs(s?.avg_response_time_ms)}
          subtitle="Across all monitors"
          icon={Gauge}
          accent="text-violet-400"
          loading={summary.loading}
        />
        <StatCard
          title="Active alerts"
          value={formatNumber(s?.active_alerts ?? 0)}
          subtitle={`${formatNumber(s?.critical_alerts ?? 0)} critical right now`}
          icon={Bell}
          accent={(s?.active_alerts ?? 0) > 0 ? 'text-red-400' : 'text-emerald-400'}
          loading={summary.loading}
        />
      </div>

      {/* Response time trend */}
      <ChartCard
        title="Response time trend"
        subtitle="Average response time per monitor over the selected window"
        className="mt-6"
        action={
          <select
            value={hours}
            onChange={(e) => setHours(Number(e.target.value))}
            className="input !w-auto !py-1.5 text-xs"
            aria-label="Time range"
          >
            {HOUR_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        }
      >
        {performance.loading && !performance.data ? (
          <div className="h-[280px] animate-pulse rounded-lg bg-ink-800/50" />
        ) : performance.error ? (
          <ErrorState message={performance.error} onRetry={performance.refetch} />
        ) : (
          <ResponseTimeChart points={performance.data?.points || []} />
        )}
      </ChartCard>

      <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-5">
        {/* Per-monitor health */}
        <ChartCard
          title="Monitor health"
          subtitle="Uptime and latency per monitor"
          className="xl:col-span-3"
          action={
            <Link to="/monitors" className="text-xs font-medium text-emerald-400 hover:text-emerald-300">
              View all →
            </Link>
          }
        >
          {health.loading && !health.data ? (
            <LoadingSkeleton rows={4} />
          ) : health.error ? (
            <ErrorState message={health.error} onRetry={health.refetch} />
          ) : healthMonitors.length === 0 ? (
            <EmptyState
              icon={MonitorCheck}
              title="No monitors yet"
              description="Add your first monitor to start tracking uptime and response times."
              action={
                <Link to="/monitors/new" className="btn-primary">
                  <Plus className="h-4 w-4" />
                  Add your first monitor
                </Link>
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[520px] border-collapse">
                <thead>
                  <tr className="border-b border-ink-700/60">
                    <th className="th">Monitor</th>
                    <th className="th">Status</th>
                    <th className="th">Uptime</th>
                    <th className="th">Avg latency</th>
                    <th className="th">Last code</th>
                    <th className="th">Alerts</th>
                  </tr>
                </thead>
                <tbody>
                  {healthMonitors.map((m) => (
                    <tr key={m.monitor_id} className="border-b border-ink-700/40 last:border-0 hover:bg-ink-850/50">
                      <td className="td">
                        <Link to={`/monitors/${m.monitor_id}`} className="font-medium text-white hover:text-emerald-400">
                          {m.name}
                        </Link>
                        <p className="text-xs text-slate-500">Checked {timeAgo(m.last_checked_at)}</p>
                      </td>
                      <td className="td">
                        <StatusBadge status={m.status} />
                      </td>
                      <td className="td">{formatUptime(m.uptime_pct)}</td>
                      <td className="td">{formatMs(m.avg_response_time_ms)}</td>
                      <td className="td font-mono">{m.last_status_code ?? '—'}</td>
                      <td className="td">
                        {m.active_alerts > 0 ? (
                          <Link
                            to={`/alerts?monitor_id=${m.monitor_id}&status=active`}
                            className="inline-flex items-center gap-1 font-medium text-red-400 hover:text-red-300"
                          >
                            <AlarmClock className="h-3.5 w-3.5" />
                            {m.active_alerts}
                          </Link>
                        ) : (
                          <span className="text-slate-500">0</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </ChartCard>

        {/* Recent alerts */}
        <ChartCard
          title="Recent alerts"
          subtitle="Active alerts, most recent first"
          className="xl:col-span-2"
          action={
            <Link to="/alerts" className="text-xs font-medium text-emerald-400 hover:text-emerald-300">
              View all →
            </Link>
          }
        >
          {recentAlerts.loading && !recentAlerts.data ? (
            <LoadingSkeleton rows={3} />
          ) : recentAlerts.error ? (
            <ErrorState message={recentAlerts.error} onRetry={recentAlerts.refetch} />
          ) : alerts.length === 0 ? (
            <div className="flex flex-col items-center py-8 text-center">
              <CheckCircle2 className="h-8 w-8 text-emerald-400" />
              <p className="mt-3 text-sm font-medium text-white">All quiet</p>
              <p className="mt-1 text-xs text-slate-500">No active alerts right now.</p>
            </div>
          ) : (
            <div className="-mx-3 divide-y divide-ink-700/40">
              {alerts.map((a) => (
                <AlertRowCompact key={a.id} alert={a} />
              ))}
            </div>
          )}
        </ChartCard>
      </div>

      {/* Recent monitoring activity */}
      <ChartCard title="Recent monitoring activity" subtitle="Latest checks across all monitors" className="mt-6">
        {recentActivity.loading && !recentActivity.data ? (
          <LoadingSkeleton rows={4} />
        ) : recentActivity.error ? (
          <ErrorState message={recentActivity.error} onRetry={recentActivity.refetch} />
        ) : activity.length === 0 ? (
          <EmptyState
            icon={Activity}
            title="No checks yet"
            description="Once monitors run — on schedule or via Check Now — their results will appear here."
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse">
              <thead>
                <tr className="border-b border-ink-700/60">
                  <th className="th">Monitor</th>
                  <th className="th">Result</th>
                  <th className="th">Response</th>
                  <th className="th">Size</th>
                  <th className="th">Checked</th>
                </tr>
              </thead>
              <tbody>
                {activity.map((r) => (
                  <tr key={r.id} className="border-b border-ink-700/40 last:border-0 hover:bg-ink-850/50">
                    <td className="td">
                      <Link to={`/monitors/${r.monitor_id}`} className="font-medium text-white hover:text-emerald-400">
                        {monitorNameById.get(r.monitor_id) || `Monitor #${r.monitor_id}`}
                      </Link>
                    </td>
                    <td className="td">
                      {r.is_success ? (
                        <span className="inline-flex items-center gap-1.5 text-emerald-400">
                          <CheckCircle2 className="h-4 w-4" /> Success
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1.5 text-red-400">
                          <XCircle className="h-4 w-4" /> Failed
                        </span>
                      )}
                    </td>
                    <td className="td font-mono">
                      {r.status_code ?? '—'} · {formatMs(r.response_time_ms)}
                    </td>
                    <td className="td">{r.records_returned != null ? `${formatNumber(r.records_returned)} records` : '—'}</td>
                    <td className="td">
                      <span className="inline-flex items-center gap-1.5 text-slate-400">
                        <Clock className="h-3.5 w-3.5" />
                        {formatTimeOnly(r.checked_at)} · {timeAgo(r.checked_at)}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </ChartCard>
    </div>
  )
}
