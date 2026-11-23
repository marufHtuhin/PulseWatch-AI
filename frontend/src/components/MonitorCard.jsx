import { Link } from 'react-router-dom'
import { ExternalLink, Pause, Play, Pencil, RefreshCw, Trash2 } from 'lucide-react'
import { MethodBadge, StatusBadge } from './Badges'
import { formatMs, timeAgo, truncate } from '../utils/format'

export function MonitorCard({ monitor, onCheck, onToggle, onDelete, checking = false, busy = false }) {
  return (
    <div className="card p-4 transition hover:border-zinc-300">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Link
              to={`/monitors/${monitor.id}`}
              className="truncate text-base font-semibold tracking-tight text-zinc-900 hover:text-blue-600"
            >
              {monitor.name}
            </Link>
            <StatusBadge status={monitor.last_status} />
            {!monitor.is_active && (
              <span className="badge bg-zinc-100 text-zinc-500">Paused</span>
            )}
          </div>
          <div className="mt-1.5 flex flex-wrap items-center gap-2">
            <MethodBadge method={monitor.method} />
            <a
              href={monitor.url}
              target="_blank"
              rel="noreferrer"
              className="inline-flex max-w-full items-center gap-1 truncate font-mono text-xs text-zinc-500 hover:text-blue-600"
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
            className="btn-icon hover:!bg-red-50 hover:!text-red-600"
            title="Delete monitor"
            onClick={() => onDelete?.(monitor)}
            disabled={busy}
            aria-label={`Delete ${monitor.name}`}
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="mt-4 grid grid-cols-2 gap-3 border-t border-zinc-100 pt-4 text-sm sm:grid-cols-4">
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">Last response</p>
          <p className="mt-0.5 font-mono font-medium tabular-nums text-zinc-900">{formatMs(monitor.last_response_time_ms)}</p>
        </div>
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">Status code</p>
          <p className="mt-0.5 font-mono font-medium tabular-nums text-zinc-900">
            {monitor.last_status_code ?? '—'}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">Interval</p>
          <p className="mt-0.5 font-mono font-medium tabular-nums text-zinc-900">
            {monitor.interval_seconds < 60 ? `${monitor.interval_seconds}s` : `${monitor.interval_seconds / 60}m`}
          </p>
        </div>
        <div>
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">Last checked</p>
          <p className="mt-0.5 font-medium text-zinc-900">{timeAgo(monitor.last_checked_at)}</p>
        </div>
      </div>
    </div>
  )
}

export function MonitorRowSkeleton() {
  return <div className="h-[132px] animate-pulse rounded-lg bg-zinc-200/70" />
}
