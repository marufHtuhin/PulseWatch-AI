import { Fragment, useEffect, useMemo, useState } from 'react'
import { ChevronDown, MonitorCheck, RefreshCw, Users } from 'lucide-react'
import { useApi } from '../hooks/useApi'
import {
  apiErrorMessage,
  deleteAdminUser,
  getAdminStats,
  getAdminUser,
  listAdminMonitors,
  listAdminUsers,
  updateAdminUser,
} from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../components/Toast'
import {
  EmptyState,
  ErrorState,
  LoadingSkeleton,
  PageHeader,
  StatsStrip,
} from '../components/Cards'
import { StatusBadge } from '../components/Badges'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { Pagination, SearchInput } from '../components/Controls'
import { debounce, formatDate, formatNumber, truncate } from '../utils/format'

const PAGE_SIZE = 15

function UserStatusBadge({ isActive }) {
  return isActive ? (
    <span className="badge bg-green-50 text-green-700">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-green-600" />
      Active
    </span>
  ) : (
    <span className="badge bg-zinc-100 text-zinc-500">
      <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-zinc-400" />
      Deactivated
    </span>
  )
}

export function Admin() {
  const toast = useToast()
  const { user: currentUser } = useAuth()
  const [tab, setTab] = useState('users')

  // ---- Stats ----
  const stats = useApi(getAdminStats, [], { initialData: null })

  // ---- Users tab ----
  const [usersPage, setUsersPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [query, setQuery] = useState('')
  const [expandedId, setExpandedId] = useState(null)
  const [detail, setDetail] = useState(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [toggleTarget, setToggleTarget] = useState(null)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [actionLoading, setActionLoading] = useState(false)

  const debouncedSearch = useMemo(
    () =>
      debounce((value) => {
        setQuery(value)
        setUsersPage(1)
      }, 350),
    []
  )

  const userParams = useMemo(
    () => ({
      skip: (usersPage - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      ...(query ? { q: query } : {}),
    }),
    [usersPage, query]
  )
  const users = useApi(() => listAdminUsers(userParams), [usersPage, query])
  const userItems = users.data?.items || []
  const userTotal = users.data?.total ?? 0

  // ---- Monitors tab ----
  const [monitorsPage, setMonitorsPage] = useState(1)
  const [filterUserId, setFilterUserId] = useState('')
  // Dropdown options are fetched lazily the first time the monitors tab opens.
  const [userOptions, setUserOptions] = useState(null)
  useEffect(() => {
    if (tab !== 'monitors' || userOptions) return
    let cancelled = false
    listAdminUsers({ skip: 0, limit: 100 })
      .then((data) => {
        if (!cancelled) setUserOptions(data.items || [])
      })
      .catch(() => {
        if (!cancelled) setUserOptions([])
      })
    return () => {
      cancelled = true
    }
  }, [tab, userOptions])

  const monitorParams = useMemo(
    () => ({
      skip: (monitorsPage - 1) * PAGE_SIZE,
      limit: PAGE_SIZE,
      ...(filterUserId ? { user_id: filterUserId } : {}),
    }),
    [monitorsPage, filterUserId]
  )
  const monitors = useApi(() => listAdminMonitors(monitorParams), [monitorsPage, filterUserId])
  const monitorItems = monitors.data?.items || []
  const monitorTotal = monitors.data?.total ?? 0

  const refreshAll = () => {
    stats.refetch()
    users.refetch()
    monitors.refetch()
  }

  const handleToggleDetail = async (u) => {
    if (expandedId === u.id) {
      setExpandedId(null)
      setDetail(null)
      return
    }
    setExpandedId(u.id)
    setDetail(null)
    setDetailLoading(true)
    try {
      setDetail(await getAdminUser(u.id))
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not load user details'))
      setExpandedId(null)
    } finally {
      setDetailLoading(false)
    }
  }

  const handleToggleActive = async () => {
    if (!toggleTarget) return
    setActionLoading(true)
    try {
      const updated = await updateAdminUser(toggleTarget.id, {
        is_active: !toggleTarget.is_active,
      })
      toast.success(
        updated.is_active
          ? `${toggleTarget.email} activated — they can sign in again.`
          : `${toggleTarget.email} deactivated — they can no longer sign in.`
      )
      setToggleTarget(null)
      users.refetch()
      stats.refetch()
      // Keep the open detail row in sync if it shows this user.
      if (expandedId === toggleTarget.id) {
        try {
          setDetail(await getAdminUser(toggleTarget.id))
        } catch {
          // Detail refresh failed; the list refresh above covers the change.
        }
      }
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not update user'))
    } finally {
      setActionLoading(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setActionLoading(true)
    try {
      await deleteAdminUser(deleteTarget.id)
      toast.success(`Deleted ${deleteTarget.email} and all of their data.`)
      setDeleteTarget(null)
      if (expandedId === deleteTarget.id) {
        setExpandedId(null)
        setDetail(null)
      }
      users.refetch()
      stats.refetch()
      monitors.refetch()
    } catch (err) {
      toast.error(apiErrorMessage(err, 'Could not delete user'))
    } finally {
      setActionLoading(false)
    }
  }

  // The API rejects changes to yourself or another admin (400) — disable
  // those actions in the UI too, with the reason on hover.
  const isProtected = (u) => u.id === currentUser?.id || u.is_admin
  const protectedTitle = (u) =>
    u.id === currentUser?.id
      ? 'You cannot change your own account here'
      : 'Admin accounts cannot be changed here'

  const statItems = [
    { title: 'Total users', value: formatNumber(stats.data?.total_users), subtitle: 'Registered accounts' },
    { title: 'Total monitors', value: formatNumber(stats.data?.total_monitors), subtitle: 'Across all users' },
    { title: 'Active monitors', value: formatNumber(stats.data?.active_monitors), subtitle: 'Currently checking' },
    { title: 'Active alerts', value: formatNumber(stats.data?.active_alerts), subtitle: 'Unresolved, all users' },
  ]

  return (
    <div>
      <PageHeader
        title="Admin"
        description="Users and monitors across the platform"
        actions={
          <>
            <div
              className="flex rounded-md border border-zinc-200 bg-zinc-100 p-0.5"
              role="tablist"
              aria-label="Admin view"
            >
              <button
                className={`rounded px-3 py-1.5 text-sm font-medium transition ${tab === 'users' ? 'bg-white text-zinc-900 shadow-sm' : 'text-zinc-500 hover:text-zinc-900'}`}
                onClick={() => setTab('users')}
                role="tab"
                aria-selected={tab === 'users'}
              >
                Users
              </button>
              <button
                className={`rounded px-3 py-1.5 text-sm font-medium transition ${tab === 'monitors' ? 'bg-white text-zinc-900 shadow-sm' : 'text-zinc-500 hover:text-zinc-900'}`}
                onClick={() => setTab('monitors')}
                role="tab"
                aria-selected={tab === 'monitors'}
              >
                All monitors
              </button>
            </div>
            <button className="btn-secondary" onClick={refreshAll} disabled={stats.loading}>
              <RefreshCw className={`h-4 w-4 ${stats.loading ? 'animate-spin' : ''}`} />
              Refresh
            </button>
          </>
        }
      />

      <div className="mb-6">
        {stats.error ? (
          <div className="card">
            <ErrorState message={stats.error} onRetry={stats.refetch} />
          </div>
        ) : (
          <StatsStrip stats={statItems} loading={stats.loading && !stats.data} />
        )}
      </div>

      {tab === 'users' ? (
        <div>
          <div className="mb-5">
            <SearchInput
              value={searchInput}
              onChange={(v) => {
                setSearchInput(v)
                debouncedSearch(v)
              }}
              placeholder="Search users by email…"
              className="max-w-md"
            />
          </div>

          <div className="card">
            {users.loading && !users.data ? (
              <div className="p-4">
                <LoadingSkeleton rows={5} />
              </div>
            ) : users.error ? (
              <ErrorState message={users.error} onRetry={users.refetch} />
            ) : userItems.length === 0 ? (
              <EmptyState
                icon={Users}
                title={query ? 'No users match this search' : 'No users yet'}
                description={
                  query ? 'Try a different email search.' : 'Registered users will appear here.'
                }
                action={
                  query ? (
                    <button
                      className="btn-secondary"
                      onClick={() => {
                        setSearchInput('')
                        setQuery('')
                        setUsersPage(1)
                      }}
                    >
                      Clear search
                    </button>
                  ) : undefined
                }
              />
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse">
                    <thead>
                      <tr className="border-b border-zinc-100">
                        <th className="th">Email</th>
                        <th className="th">Status</th>
                        <th className="th">Role</th>
                        <th className="th">Monitors</th>
                        <th className="th">Alerts</th>
                        <th className="th">Created</th>
                        <th className="th text-right">Actions</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-100">
                      {userItems.map((u) => (
                        <Fragment key={u.id}>
                          <tr className="hover:bg-zinc-50/60">
                            <td className="td max-w-60 truncate font-medium text-zinc-900" title={u.email}>
                              {u.email}
                            </td>
                            <td className="td">
                              <UserStatusBadge isActive={u.is_active} />
                            </td>
                            <td className="td">
                              {u.is_admin ? (
                                <span className="badge border border-zinc-200 bg-zinc-50 text-zinc-600">
                                  Admin
                                </span>
                              ) : (
                                <span className="text-zinc-400">—</span>
                              )}
                            </td>
                            <td className="td tabular-nums">{formatNumber(u.monitor_count)}</td>
                            <td className="td tabular-nums">{formatNumber(u.alert_count)}</td>
                            <td className="td whitespace-nowrap text-zinc-500">
                              {formatDate(u.created_at)}
                            </td>
                            <td className="td">
                              <div className="flex items-center justify-end gap-3 whitespace-nowrap">
                                <button
                                  className="inline-flex items-center gap-1 text-sm font-medium text-zinc-700 hover:text-zinc-900 hover:underline"
                                  onClick={() => handleToggleDetail(u)}
                                  aria-expanded={expandedId === u.id}
                                >
                                  View
                                  <ChevronDown
                                    className={`h-4 w-4 transition-transform ${expandedId === u.id ? 'rotate-180' : ''}`}
                                  />
                                </button>
                                <button
                                  className="text-sm font-medium text-zinc-700 hover:text-zinc-900 hover:underline disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:no-underline"
                                  onClick={() => setToggleTarget(u)}
                                  disabled={isProtected(u)}
                                  title={isProtected(u) ? protectedTitle(u) : undefined}
                                >
                                  {u.is_active ? 'Deactivate' : 'Activate'}
                                </button>
                                <button
                                  className="text-sm font-medium text-red-600 hover:text-red-700 hover:underline disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:no-underline"
                                  onClick={() => setDeleteTarget(u)}
                                  disabled={isProtected(u)}
                                  title={isProtected(u) ? protectedTitle(u) : undefined}
                                >
                                  Delete
                                </button>
                              </div>
                            </td>
                          </tr>
                          {expandedId === u.id && (
                            <tr key={`${u.id}-detail`} className="bg-zinc-50/60">
                              <td colSpan={7} className="px-4 py-4">
                                {detailLoading || !detail ? (
                                  <LoadingSkeleton rows={2} />
                                ) : (
                                  <div>
                                    <p className="text-xs font-medium uppercase tracking-wider text-zinc-400">
                                      {detail.email} — {formatNumber(detail.monitor_count)}{' '}
                                      monitor{detail.monitor_count === 1 ? '' : 's'} ·{' '}
                                      {formatNumber(detail.alert_count)} alert
                                      {detail.alert_count === 1 ? '' : 's'} (
                                      {formatNumber(detail.active_alert_count)} active)
                                    </p>
                                    {detail.monitors?.length ? (
                                      <ul className="mt-3 divide-y divide-zinc-100 rounded-md border border-zinc-200 bg-white">
                                        {detail.monitors.map((m) => (
                                          <li
                                            key={m.id}
                                            className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5"
                                          >
                                            <div className="min-w-0">
                                              <p className="truncate text-sm font-medium text-zinc-900">
                                                {m.name}
                                              </p>
                                              <a
                                                href={m.url}
                                                target="_blank"
                                                rel="noreferrer"
                                                className="block max-w-md truncate font-mono text-xs text-zinc-500 hover:text-zinc-900 hover:underline"
                                                title={m.url}
                                              >
                                                {m.url}
                                              </a>
                                            </div>
                                            <div className="flex items-center gap-2">
                                              {!m.is_active && (
                                                <span className="badge bg-zinc-100 text-zinc-500">
                                                  Paused
                                                </span>
                                              )}
                                              <StatusBadge status={m.status} />
                                            </div>
                                          </li>
                                        ))}
                                      </ul>
                                    ) : (
                                      <p className="mt-3 text-sm text-zinc-500">
                                        This user has no monitors yet.
                                      </p>
                                    )}
                                  </div>
                                )}
                              </td>
                            </tr>
                          )}
                        </Fragment>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="border-t border-zinc-100">
                  <Pagination
                    page={usersPage}
                    pageSize={PAGE_SIZE}
                    total={userTotal}
                    onPageChange={setUsersPage}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      ) : (
        <div>
          <div className="mb-5 flex flex-wrap items-center gap-2">
            <select
              value={filterUserId}
              onChange={(e) => {
                setFilterUserId(e.target.value)
                setMonitorsPage(1)
              }}
              className="input !w-auto max-w-xs"
              aria-label="Filter by user"
            >
              <option value="">All users</option>
              {(userOptions || []).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.email}
                </option>
              ))}
            </select>
            {filterUserId && (
              <button
                className="btn-secondary"
                onClick={() => {
                  setFilterUserId('')
                  setMonitorsPage(1)
                }}
              >
                Clear filter
              </button>
            )}
          </div>

          <div className="card">
            {monitors.loading && !monitors.data ? (
              <div className="p-4">
                <LoadingSkeleton rows={5} />
              </div>
            ) : monitors.error ? (
              <ErrorState message={monitors.error} onRetry={monitors.refetch} />
            ) : monitorItems.length === 0 ? (
              <EmptyState
                icon={MonitorCheck}
                title={filterUserId ? 'No monitors for this user' : 'No monitors yet'}
                description={
                  filterUserId
                    ? 'This user has not created any monitors.'
                    : 'Monitors created by any user will appear here.'
                }
              />
            ) : (
              <>
                <div className="overflow-x-auto">
                  <table className="w-full border-collapse">
                    <thead>
                      <tr className="border-b border-zinc-100">
                        <th className="th">Monitor</th>
                        <th className="th">URL</th>
                        <th className="th">Owner</th>
                        <th className="th">Status</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-100">
                      {monitorItems.map((m) => (
                        <tr key={m.id} className="hover:bg-zinc-50/60">
                          <td className="td max-w-60 truncate font-medium text-zinc-900" title={m.name}>
                            {m.name}
                          </td>
                          <td className="td max-w-xs">
                            <a
                              href={m.url}
                              target="_blank"
                              rel="noreferrer"
                              className="block truncate font-mono text-xs text-zinc-500 hover:text-zinc-900 hover:underline"
                              title={m.url}
                            >
                              {truncate(m.url, 60)}
                            </a>
                          </td>
                          <td className="td max-w-60 truncate" title={m.owner_email}>
                            {m.owner_email}
                          </td>
                          <td className="td">
                            <div className="flex items-center gap-2">
                              {!m.is_active && (
                                <span className="badge bg-zinc-100 text-zinc-500">Paused</span>
                              )}
                              <StatusBadge status={m.status} />
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="border-t border-zinc-100">
                  <Pagination
                    page={monitorsPage}
                    pageSize={PAGE_SIZE}
                    total={monitorTotal}
                    onPageChange={setMonitorsPage}
                  />
                </div>
              </>
            )}
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!toggleTarget}
        title={
          toggleTarget?.is_active
            ? `Deactivate ${toggleTarget?.email}?`
            : `Activate ${toggleTarget?.email}?`
        }
        message={
          toggleTarget?.is_active
            ? 'This user will be unable to sign in until reactivated. Their monitors, alerts, and data are kept.'
            : 'This user will be able to sign in again.'
        }
        confirmLabel={toggleTarget?.is_active ? 'Deactivate' : 'Activate'}
        loading={actionLoading}
        onConfirm={handleToggleActive}
        onCancel={() => setToggleTarget(null)}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        title={`Delete ${deleteTarget?.email}?`}
        message="This permanently deletes the user and ALL of their data — monitors, check history, anomalies, alerts, and settings. This cannot be undone."
        confirmLabel="Delete user"
        danger
        loading={actionLoading}
        onConfirm={handleDelete}
        onCancel={() => setDeleteTarget(null)}
      />
    </div>
  )
}
