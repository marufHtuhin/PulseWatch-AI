import { Activity } from 'lucide-react'

/**
 * One white strip divided into sections with hairline dividers.
 * stats: [{ title, value, subtitle }]
 */
export function StatsStrip({ stats, loading = false }) {
  return (
    <div className="card grid grid-cols-1 divide-y divide-zinc-100 sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4 lg:divide-x">
      {stats.map((stat, i) => (
        <div key={stat.title} className={`p-4 ${i % 2 === 1 ? 'sm:border-l sm:border-zinc-100' : ''} ${i >= 2 ? 'max-lg:border-t max-lg:border-zinc-100' : ''}`}>
          <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">{stat.title}</p>
          {loading ? (
            <div className="mt-2 h-8 w-24 animate-pulse rounded bg-zinc-200/70" />
          ) : (
            <p className="mt-1.5 font-mono text-2xl font-semibold tabular-nums tracking-tight text-zinc-900">
              {stat.value}
            </p>
          )}
          {stat.subtitle && <p className="mt-1 text-xs text-zinc-500">{stat.subtitle}</p>}
        </div>
      ))}
    </div>
  )
}

export function ChartCard({ title, subtitle, action, children, className = '' }) {
  return (
    <div className={`card p-4 ${className}`}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold tracking-tight text-zinc-900">{title}</h3>
          {subtitle && <p className="mt-0.5 text-xs text-zinc-500">{subtitle}</p>}
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
        <div className="rounded-full bg-zinc-100 p-3 text-zinc-400">
          <Icon className="h-6 w-6" />
        </div>
      )}
      <h3 className="mt-4 text-sm font-semibold text-zinc-900">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-zinc-500">{description}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function LoadingSkeleton({ rows = 4, className = '' }) {
  return (
    <div className={`space-y-3 ${className}`} aria-busy="true" aria-label="Loading">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-12 animate-pulse rounded-lg bg-zinc-200/70" />
      ))}
    </div>
  )
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 text-center">
      <div className="rounded-full bg-red-50 p-3 text-red-600">
        <Activity className="h-6 w-6" />
      </div>
      <h3 className="mt-4 text-sm font-semibold text-zinc-900">Couldn&apos;t load this data</h3>
      <p className="mt-1 max-w-sm text-sm text-zinc-500">{message || 'An unexpected error occurred.'}</p>
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
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900 sm:text-2xl">{title}</h1>
        {description && <p className="mt-1 text-sm text-zinc-500">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}
