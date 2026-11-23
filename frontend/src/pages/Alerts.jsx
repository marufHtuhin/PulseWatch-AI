import { useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Bell, CheckCircle2, RefreshCw } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import {
  acknowledgeAlert,
  apiErrorMessage,
  listAlerts,
  listAlertHistory,
  listMonitors,
  resolveAlert,
} from '../api/client'
import { useToast } from '../components/Toast'
import { EmptyState, ErrorState, LoadingSkeleton, PageHeader } from '../components/Cards'
import { AlertRow } from '../components/AlertRow'
import { Pagination, SearchInput } from '../components/Controls'
import { debounce } from '../utils/format'

const PAGE_SIZE = 15

export function Alerts() {
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const [searchInput, setSearchInput] = useState(searchParams.get('search') || '')
  const [busyId, setBusyId] = useState(null)

  const page = Number(searchParams.get('page') || 1)
  const search = searchParams.get('search') || ''
  const severity = searchParams.get('severity') || ''
  const status = searchParams.get('status') || ''
  const monitorId = searchParams.get('monitor_id') || ''
  const showHistory = searchParams.get('view') === 'history'

  const updateParams = (patch) => {
    const next = new URLSearchParams(searchParams)
    for (const [k, v] of Object.entries(patch)) {
      if (v === '' || v === null || v === undefined) next.delete(k)
      else next.set(k, v)
    }
    if (!('page' in patch)) next.set('page', '1')
    setSearchParams(next, { replace: true })
  }

  const debouncedSearch = useMemo(
    () =>
      debounce((value) => {
        updateParams({ search: value })
      }, 350),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [searchParams]
  )

  const params = useMemo(
    () => ({
      page,
      page_size: PAGE_SIZE,
      ...(search ? { search } : {}),
      ...(severity ? { severity } : {}),
      // History view lists resolved alerts; the /alerts/history endpoint
      // already scopes to resolved, so don't pass a conflicting status.
      ...(showHistory ? {} : status ? { status } : {}),
      ...(monitorId ? { monitor_id: monitorId } : {}),
    }),
    [page, search, severity, status, monitorId, showHistory]
  )

  const alerts = useApi(
    () => (showHistory ? listAlertHistory(params) : listAlerts(params)),
    [page, search, severity, status, monitorId, showHistory],
    { pollIntervalMs: 30000 }
  )
  const monitors = useApi(() => listMonitors({ page: 1, page_size: 100 }), [], {
    initialData: { items: [] },
  })

  const items = alerts.data?.items || []
  const total = alerts.data?.total ?? 0
  const monitorOptions = monitors.data?.items || []

  const handleAction = async (alert, action) => {
    setBusyId(alert.id)
    try {
      if (action === 'acknowledge') {
        await acknowledgeAlert(alert.id)
        toast.success(`Alert acknowledged: ${alert.title}`)
      } else {
        await resolveAlert(alert.id)
        toast.success(`Alert resolved: ${alert.title}`)
      }
      alerts.refetch()
    } catch (err) {
      toast.error(apiErrorMessage(err, `Could not ${action} the alert`))
    } finally {
      setBusyId(null)
    }
  }

  const isFiltered = Boolean(search || severity || status || monitorId)

  return (
    <div>
      <PageHeader
        title={showHistory ? 'Alert history' : 'Alerts'}
        description={showHistory ? 'Resolved alerts, most recent first' : undefined}
        actions={
          <>
            <div className="flex rounded-md border border-zinc-200 bg-zinc-100 p-0.5" role="tablist" aria-label="Alert view">
              <button
                className={`rounded px-3 py-1.5 text-sm font-medium transition ${!showHistory ? 'bg-white text-zinc-900 shadow-sm' : 'text-zinc-500 hover:text-zinc-900'}`}
                onClick={() => updateParams({ view: '', status: '' })}
                role="tab"
                aria-selected={!showHistory}
              >
                Open alerts
              </button>
              <button
                className={`rounded px-3 py-1.5 text-sm font-medium transition ${showHistory ? 'bg-white text-zinc-900 shadow-sm' : 'text-zinc-500 hover:text-zinc-900'}`}
                onClick={() => updateParams({ view: 'history', status: '' })}
                role="tab"
                aria-selected={showHistory}
              >
                History
              </button>
            </div>
            <button className="btn-secondary" onClick={alerts.refetch} disabled={alerts.loading}>
              <RefreshCw className={`h-4 w-4 ${alerts.loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </>
        }
      />

      {/* Filters */}
      <div className="mb-5 flex flex-col gap-3 lg:flex-row lg:items-center">
        <SearchInput
          value={searchInput}
          onChange={(v) => {
            setSearchInput(v)
            debouncedSearch(v)
          }}
          placeholder="Search alerts by title or summary…"
          className="flex-1"
        />
        <div className="flex flex-wrap gap-2">
          <select
            value={severity}
            onChange={(e) => updateParams({ severity: e.target.value })}
            className="input !w-auto"
            aria-label="Filter by severity"
          >
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
          {!showHistory && (
            <select
              value={status}
              onChange={(e) => updateParams({ status: e.target.value })}
              className="input !w-auto"
              aria-label="Filter by status"
            >
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="acknowledged">Acknowledged</option>
              <option value="resolved">Resolved</option>
            </select>
          )}
          <select
            value={monitorId}
            onChange={(e) => updateParams({ monitor_id: e.target.value })}
            className="input !w-auto max-w-[220px]"
            aria-label="Filter by monitor"
          >
            <option value="">All monitors</option>
            {monitorOptions.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="card">
        {alerts.loading && !alerts.data ? (
          <div className="p-4">
            <LoadingSkeleton rows={5} />
          </div>
        ) : alerts.error ? (
          <ErrorState message={alerts.error} onRetry={alerts.refetch} />
        ) : items.length === 0 ? (
          <EmptyState
            icon={showHistory ? Bell : CheckCircle2}
            title={
              isFiltered
                ? 'No alerts match these filters'
                : showHistory
                  ? 'No resolved alerts yet'
                  : 'No alerts'
            }
            description={
              isFiltered
                ? 'Try a different search or clear the filters.'
                : showHistory
                  ? 'Alerts you resolve will appear here.'
                  : 'When an anomaly is detected, its alert will appear here.'
            }
            action={
              isFiltered ? (
                <button
                  className="btn-secondary"
                  onClick={() => {
                    setSearchInput('')
                    setSearchParams(showHistory ? { view: 'history' } : {}, { replace: true })
                  }}
                >
                  Clear filters
                </button>
              ) : undefined
            }
          />
        ) : (
          <>
            <div className="divide-y divide-zinc-100">
              {items.map((a) => (
                <AlertRow
                  key={a.id}
                  alert={a}
                  onAcknowledge={(alert) => handleAction(alert, 'acknowledge')}
                  onResolve={(alert) => handleAction(alert, 'resolve')}
                  busy={busyId === a.id}
                />
              ))}
            </div>
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              onPageChange={(p) => updateParams({ page: String(p) })}
            />
          </>
        )}
      </div>
    </div>
  )
}
