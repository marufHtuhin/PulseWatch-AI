import { Link } from 'react-router-dom'
import { BellRing, Check, CheckCheck } from 'lucide-react'
import { AlertStatusBadge, SeverityBadge } from './Badges'
import { anomalyLabel, timeAgo, truncate } from '../utils/format'

export function AlertRow({ alert, onAcknowledge, onResolve, busy = false }) {
  return (
    <div className="flex flex-col gap-3 px-4 py-3.5 transition hover:bg-ink-850/60 sm:flex-row sm:items-center sm:gap-4">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityBadge severity={alert.severity} />
          <AlertStatusBadge status={alert.status} />
          <span className="text-xs text-slate-500">{anomalyLabel(alert.anomaly_type)}</span>
        </div>
        <Link
          to={`/alerts/${alert.id}`}
          className="mt-1.5 block truncate font-medium text-white hover:text-emerald-400"
        >
          {alert.title}
        </Link>
        <p className="mt-0.5 truncate text-sm text-slate-400">
          {truncate(alert.summary || 'No summary available.', 120)}
        </p>
        <p className="mt-1 text-xs text-slate-500">
          {alert.monitor_name ? (
            <Link to={`/monitors/${alert.monitor_id}`} className="text-slate-400 hover:text-emerald-400">
              {alert.monitor_name}
            </Link>
          ) : (
            'Unknown monitor'
          )}
          {' · '}
          {timeAgo(alert.created_at)}
          {alert.occurrence_count > 1 && (
            <> · seen {alert.occurrence_count} times (last {timeAgo(alert.last_seen_at)})</>
          )}
          {alert.ai_generated && <> · <span className="text-emerald-400/90">AI explained</span></>}
        </p>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        {alert.status === 'active' && (
          <button
            className="btn-secondary !py-1.5 text-xs"
            onClick={() => onAcknowledge?.(alert)}
            disabled={busy}
            title="Acknowledge this alert"
          >
            <Check className="h-3.5 w-3.5" />
            Acknowledge
          </button>
        )}
        {alert.status !== 'resolved' && (
          <button
            className="btn-primary !py-1.5 text-xs"
            onClick={() => onResolve?.(alert)}
            disabled={busy}
            title="Mark this alert as resolved"
          >
            <CheckCheck className="h-3.5 w-3.5" />
            Resolve
          </button>
        )}
      </div>
    </div>
  )
}

export function AlertRowCompact({ alert }) {
  return (
    <Link
      to={`/alerts/${alert.id}`}
      className="flex items-start gap-3 rounded-lg px-3 py-2.5 transition hover:bg-ink-800"
    >
      <BellRing className="mt-0.5 h-4 w-4 shrink-0 text-slate-500" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="truncate text-sm font-medium text-slate-100">{alert.title}</p>
          <SeverityBadge severity={alert.severity} />
        </div>
        <p className="mt-0.5 text-xs text-slate-500">
          {alert.monitor_name} · {timeAgo(alert.created_at)}
        </p>
      </div>
    </Link>
  )
}
