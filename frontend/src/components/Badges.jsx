import { AlertTriangle, CheckCircle2, HelpCircle, XCircle } from 'lucide-react'

const STATUS_STYLES = {
  up: { cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30', Icon: CheckCircle2, label: 'Up' },
  down: { cls: 'bg-red-500/10 text-red-400 border border-red-500/30', Icon: XCircle, label: 'Down' },
  unknown: { cls: 'bg-slate-500/10 text-slate-400 border border-slate-500/30', Icon: HelpCircle, label: 'Unknown' },
}

export function StatusBadge({ status }) {
  const s = STATUS_STYLES[status] || STATUS_STYLES.unknown
  const Icon = s.Icon
  return (
    <span className={`badge ${s.cls}`}>
      <Icon className="h-3.5 w-3.5" />
      {s.label}
    </span>
  )
}

const SEVERITY_STYLES = {
  critical: { cls: 'bg-red-500/10 text-red-400 border border-red-500/30', Icon: XCircle, label: 'Critical' },
  high: { cls: 'bg-orange-500/10 text-orange-400 border border-orange-500/30', Icon: AlertTriangle, label: 'High' },
  warning: { cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/30', Icon: AlertTriangle, label: 'Warning' },
  info: { cls: 'bg-sky-500/10 text-sky-400 border border-sky-500/30', Icon: HelpCircle, label: 'Info' },
}

export function SeverityBadge({ severity }) {
  const s = SEVERITY_STYLES[severity] || SEVERITY_STYLES.info
  const Icon = s.Icon
  return (
    <span className={`badge ${s.cls}`}>
      <Icon className="h-3.5 w-3.5" />
      {s.label}
    </span>
  )
}

const ALERT_STATUS_STYLES = {
  active: { cls: 'bg-red-500/10 text-red-400 border border-red-500/30', label: 'Active' },
  acknowledged: { cls: 'bg-amber-500/10 text-amber-400 border border-amber-500/30', label: 'Acknowledged' },
  resolved: { cls: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30', label: 'Resolved' },
}

export function AlertStatusBadge({ status }) {
  const s = ALERT_STATUS_STYLES[status] || { cls: 'bg-slate-500/10 text-slate-400 border border-slate-500/30', label: status || '—' }
  return <span className={`badge ${s.cls}`}>{s.label}</span>
}

const METHOD_STYLES = {
  GET: 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/30',
  POST: 'bg-sky-500/10 text-sky-400 border border-sky-500/30',
  PUT: 'bg-amber-500/10 text-amber-400 border border-amber-500/30',
  DELETE: 'bg-red-500/10 text-red-400 border border-red-500/30',
}

export function MethodBadge({ method }) {
  const cls = METHOD_STYLES[method] || 'bg-slate-500/10 text-slate-400 border border-slate-500/30'
  return <span className={`badge font-mono ${cls}`}>{method || '—'}</span>
}
