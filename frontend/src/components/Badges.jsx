// Subtle status badges: a small colored dot + text on a light tinted
// background. Color is used only for actual status, never as decoration.

function Dot({ className }) {
  return <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${className}`} />
}

const STATUS_STYLES = {
  up: { cls: 'bg-green-50 text-green-700', dot: 'bg-green-600', label: 'Up' },
  down: { cls: 'bg-red-50 text-red-700', dot: 'bg-red-600', label: 'Down' },
  unknown: { cls: 'bg-zinc-100 text-zinc-500', dot: 'bg-zinc-400', label: 'Unknown' },
}

export function StatusBadge({ status }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.unknown
  return (
    <span className={`badge ${s.cls}`}>
      <Dot className={s.dot} />
      {s.label}
    </span>
  )
}

const SEVERITY_STYLES = {
  critical: { cls: 'bg-red-50 text-red-700', dot: 'bg-red-600', label: 'Critical' },
  high: { cls: 'bg-orange-50 text-orange-700', dot: 'bg-orange-600', label: 'High' },
  warning: { cls: 'bg-amber-50 text-amber-700', dot: 'bg-amber-600', label: 'Warning' },
  info: { cls: 'bg-zinc-100 text-zinc-600', dot: 'bg-zinc-400', label: 'Info' },
}

export function SeverityBadge({ severity }) {
  const s = SEVERITY_STYLES[severity] || SEVERITY_STYLES.info
  return (
    <span className={`badge ${s.cls}`}>
      <Dot className={s.dot} />
      {s.label}
    </span>
  )
}

const ALERT_STATUS_STYLES = {
  active: { cls: 'bg-red-50 text-red-700', dot: 'bg-red-600', label: 'Active' },
  acknowledged: { cls: 'bg-amber-50 text-amber-700', dot: 'bg-amber-600', label: 'Acknowledged' },
  resolved: { cls: 'bg-green-50 text-green-700', dot: 'bg-green-600', label: 'Resolved' },
}

export function AlertStatusBadge({ status }) {
  const s = ALERT_STATUS_STYLES[status] || { cls: 'bg-zinc-100 text-zinc-500', dot: 'bg-zinc-400', label: status || '—' }
  return (
    <span className={`badge ${s.cls}`}>
      <Dot className={s.dot} />
      {s.label}
    </span>
  )
}

export function MethodBadge({ method }) {
  return <span className="badge border border-zinc-200 bg-zinc-50 font-mono text-zinc-600">{method || '—'}</span>
}
