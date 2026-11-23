import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { MonitorCheck, Plus, RefreshCw } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import { apiErrorMessage, checkMonitorNow, deleteMonitor, listMonitors, toggleMonitor } from '../api/client'
import { useToast } from '../components/Toast'
import { EmptyState, ErrorState, PageHeader } from '../components/Cards'
import { MonitorCard, MonitorRowSkeleton } from '../components/MonitorCard'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Pagination, SearchInput } from '../components/Controls'
import { debounce, formatMs } from '../utils/format'

const PAGE_SIZE = 12

export function Monitors() {
  const toast = useToast()
  const [searchParams, setSearchParams] = useSearchParams()
  const [searchInput, setSearchInput] = useState(searchParams.get('search') || '')
  const [checkingId, setCheckingId] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)

  const page = Number(searchParams.get('page') || 1)
  const search = searchParams.get('search') || ''
  const status = searchParams.get('status') || ''
  const isActive = searchParams.get('is_active') || ''

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
      ...(status ? { status } : {}),
      ...(isActive ? { is_active: isActive } : {}),
    }),
    [page, search, status, isActive]
  )

  const monitors = useApi(() => listMonitors(params), [page, search, status, isActive], {
    pollIntervalMs: 30000,
  })
  const items = monitors.data?.items || []
  const total = monitors.data?.total ?? 0

  const handleCheckNow = async (monitor) => {
    setCheckingId(monitor.id)
    try {
      const record = await checkMonitorNow(monitor.id)
      const anomalies = record?.anomalies?.length || 0
      const alerts = record?.alerts_created?.length || 0
      if (record?.is_success) {
        toast.success(
          `${monitor.name}: OK (${record.status_code}, ${formatMs(record.response_time_ms)})` +
            (anomalies ? ` — ${anomalies} anomal${anomalies === 1 ? 'y' : 'ies'} detected` : '') +
            (alerts ? `, ${alerts} alert${alerts === 1 ? '' : 's'} created` : '')
        )
      } else {
        toast.error(
          `${monitor.name}: check failed${record?.status_code ? ` (${record.status_code})` : ''}${record?.error_message ? ` — ${record.error_message}` : ''}`
        )
      }
      monitors.refetch()
    } catch (err) {
      toast.error(apiErrorMessage(err, `Check failed for ${monitor.name}`))
    } finally {
      setCheckingId(null)
    }
  }

  const handleToggle = async (monitor) => {
    setBusyId(monitor.id)
    try {
      const updated = await toggleMonitor(monitor.id)
      toast.success(
        updated.is_active
          ? `${monitor.name} resumed — scheduled checks are on.`
          : `${monitor.name} paused — scheduled checks are off.`
      )
      monitors.refetch()
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not change monitor state'))
    } finally {
      setBusyId(null)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteMonitor(deleteTarget.id)
      toast.success(`Deleted monitor "${deleteTarget.name}" and its history.`)
      setDeleteTarget(null)
      monitors.refetch()
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not delete monitor'))
    } finally {
      setDeleting(false)
    }
  }

  const isFiltered = Boolean(search || status || isActive)

  return (
    <div>
      <PageHeader
        title="Monitors"
        actions={
          <>
            <button className="btn-secondary" onClick={monitors.refetch} disabled={monitors.loading}>
              <RefreshCw className={`h-4 w-4 ${monitors.loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
            <Link to="/monitors/new" className="btn-primary">
              <Plus className="h-4 w-4" />
              Add Monitor
            </Link>
          </>
        }
      />

      {/* Filters */}
      <div className="mb-5 flex flex-col gap-3 sm:flex-row sm:items-center">
        <SearchInput
          value={searchInput}
          onChange={(v) => {
            setSearchInput(v)
            debouncedSearch(v)
          }}
          placeholder="Search monitors by name or URL…"
          className="flex-1"
        />
        <div className="flex gap-2">
          <select
            value={status}
            onChange={(e) => updateParams({ status: e.target.value })}
            className="input !w-auto"
            aria-label="Filter by status"
          >
            <option value="">All statuses</option>
            <option value="up">Up</option>
            <option value="down">Down</option>
            <option value="unknown">Unknown</option>
          </select>
          <select
            value={isActive}
            onChange={(e) => updateParams({ is_active: e.target.value })}
            className="input !w-auto"
            aria-label="Filter by active state"
          >
            <option value="">Active &amp; paused</option>
            <option value="true">Active only</option>
            <option value="false">Paused only</option>
          </select>
        </div>
      </div>

      {monitors.loading && !monitors.data ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <MonitorRowSkeleton key={i} />
          ))}
        </div>
      ) : monitors.error ? (
        <div className="card">
          <ErrorState message={monitors.error} onRetry={monitors.refetch} />
        </div>
      ) : items.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={MonitorCheck}
            title={isFiltered ? 'No monitors match these filters' : 'No monitors yet'}
            description={
              isFiltered
                ? 'Try a different search or clear the filters.'
                : 'Add your first monitor to start tracking an API endpoint.'
            }
            action={
              isFiltered ? (
                <button
                  className="btn-secondary"
                  onClick={() => {
                    setSearchInput('')
                    setSearchParams({}, { replace: true })
                  }}
                >
                  Clear filters
                </button>
              ) : (
                <Link to="/monitors/new" className="btn-primary">
                  <Plus className="h-4 w-4" />
                  Add your first monitor
                </Link>
              )
            }
          />
        </div>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {items.map((m) => (
              <MonitorCard
                key={m.id}
                monitor={m}
                onCheck={handleCheckNow}
                onToggle={handleToggle}
                onDelete={setDeleteTarget}
                checking={checkingId === m.id}
                busy={busyId === m.id}
              />
            ))}
          </div>
          <div className="card mt-4">
            <Pagination
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              onPageChange={(p) => updateParams({ page: String(p) })}
            />
          </div>
        </>
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        title={`Delete "${deleteTarget?.name}"?`}
        message="This permanently deletes the monitor and all of its monitoring history, anomalies, and alerts. This cannot be undone."
        confirmLabel="Delete monitor"
        danger
        loading={deleting}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
