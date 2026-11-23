import { Link } from 'react-router-dom'
import { ExternalLink, Pause, Play, Pencil, RefreshCw, Trash2 } from 'lucide-react'
import { MethodBadge, StatusBadge } from './Badges'
import { formatMs, timeAgo, truncate } from '../utils/format'

export function MonitorCard({ monitor, onCheck, onToggle, onDelete, checking = false, busy = false }) {
  return (
    <div className="card p-4 transition hover:border-ink-600 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/monitors/${monitor.id}`}
              className="truncate text-base font-semibold text-white hover:text-emerald-400"
            >
              {monitor.name}
            </Link>
            <StatusBadge status={monitor.last_status} />
            {!monitor.is_active && (
              <span className="badge border border-slate-500/30 bg-slate-500/10 text-slate-400">Paused</span>
            )}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <MethodBadge method={monitor.method} />
            <a
              href={monitor.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex max-w-full items-center gap-1 truncate font-mono text-xs text-slate-400 hover:text-emerald-400"
              title={monitor.url}
            >
              {truncate(monitor.url, 60)}
              <ExternalLink className="h-3 w-3 shrink-0" />
            </a>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          <button
            className="btn-icon"
            title="Run a check now"
            onClick={() => onCheck?.(monitor)}
            disabled={checking || busy}
            aria-label={`Check ${monitor.name} now`}
          >
            <RefreshCw className={`h-4 w-4 ${checking ? 'animate-spin' : ''}`} />
          </button>
          <Link to={`/monitors/${monitor.id}/edit`} className="btn-icon" title="Edit monitor" aria-label={`Edit ${monitor.name}`}>
            <Pencil className="h-4 w-4" />
          </Link>
          <button
            className="btn-icon"
            title={monitor.is_active ? 'Pause monitoring' : 'Resume monitoring'}
            onClick={() => onToggle?.(monitor)}
            disabled={busy}
            aria-label={monitor.is_active ? `Pause ${monitor.name}` : `Resume ${monitor.name}`}
          >
            {monitor.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </button>
          <button
            className="btn-icon hover:!bg-red-500/10 hover:!text-red-400"
            title="Delete monitor"
            onClick={() => onDelete?.(monitor)}
            disabled={busy}
            aria-label={`Delete ${monitor.name}`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-ink-700/60 pt-4 text-sm sm:grid-cols-4">
        <div>
          <p className="text-xs text-slate-500">Last response</p>
          <p className="mt-0.5 font-medium text-slate-200">{formatMs(monitor.last_response_time_ms)}</p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Status code</p>
          <p className="mt-0.5 font-medium text-slate-200">
            {monitor.last_status_code ?? '—'}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Interval</p>
          <p className="mt-0.5 font-medium text-slate-200">
            {monitor.interval_seconds < 60 ? `${monitor.interval_seconds}s` : `${monitor.interval_seconds / 60}m`}
          </p>
        </div>
        <div>
          <p className="text-xs text-slate-500">Last checked</p>
          <p className="mt-0.5 font-medium text-slate-200">{timeAgo(monitor.last_checked_at)}</p>
        </div>
      </div>
    </div>
  )
}

export function MonitorRowSkeleton() {
  return <div className="h-[132px] animate-pulse rounded-xl bg-ink-900" />
}
