import { Activity } from 'lucide-react'

export function StatCard({ title, value, subtitle, icon: Icon = Activity, accent = 'text-emerald-400', loading = false }) {
  return (
    <div className="card p-4 sm:p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="truncate text-xs font-medium uppercase tracking-wide text-slate-400">{title}</p>
          {loading ? (
            <div className="mt-2 h-8 w-24 animate-pulse rounded bg-ink-700/60" />
          ) : (
            <p className="mt-1.5 text-2xl font-semibold tracking-tight text-white sm:text-3xl">{value}</p>
          )}
          {subtitle && <p className="mt-1 text-xs text-slate-500">{subtitle}</p>}
        </div>
        <div className={`rounded-lg bg-ink-800 p-2.5 ${accent}`}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  )
}

export function ChartCard({ title, subtitle, action, children, className = '' }) {
  return (
    <div className={`card p-4 sm:p-5 ${className}`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-white">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
        </div>
        {action}
      </div>
      {children}
    </div>
  )
}

export function EmptyState({ icon: Icon, title, description, action }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      {Icon && (
        <div className="rounded-full bg-ink-800 p-3 text-slate-500">
          <Icon className="h-6 w-6" />
        </div>
      )}
      <h3 className="mt-4 text-sm font-semibold text-white">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function LoadingSkeleton({ rows = 4, className = '' }) {
  return (
    <div className={`space-y-3 ${className}`} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-12 animate-pulse rounded-lg bg-ink-800/70" />
      ))}
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="rounded-full bg-red-500/10 p-3 text-red-400">
        <Activity className="h-6 w-6" />
      </div>
      <h3 className="mt-4 text-sm font-semibold text-white">Couldn&apos;t load this data</h3>
      <p className="mt-1 max-w-sm text-sm text-slate-500">{message || 'An unexpected error occurred.'}</p>
      {onRetry && (
        <button onClick={onRetry} className="btn-secondary mt-5">
          Try again
        </button>
      )}
    </div>
  )
}

export function PageHeader({ title, description, actions }) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-white sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
