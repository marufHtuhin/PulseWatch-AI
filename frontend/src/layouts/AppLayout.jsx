import { useState } from 'react'
import { Link, Outlet } from 'react-router-dom'
import { Bell, Menu, Plus, RefreshCw } from 'lucide-react'
import { Sidebar } from '../components/Sidebar'
import { useApi } from '../hooks/useApi'
import { listAlerts } from '../api/client'

export function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)

  // Active alert count for the topbar bell (polled every 30s).
  const { data: activeAlerts } = useApi(
    () => listAlerts({ status: 'active', page: 1, page_size: 1 }),
    [],
    { pollIntervalMs: 30000, initialData: { total: 0 } }
  )
  const activeCount = activeAlerts?.total ?? 0

  return (
    <div className="flex h-full">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-ink-700/60 bg-ink-950/90 px-4 py-3 backdrop-blur sm:px-6">
          <div className="flex items-center gap-2">
            <button
              className="btn-icon lg:hidden"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
            <span className="hidden text-sm text-slate-500 sm:block">
              Monitoring your APIs in real time
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              className="btn-icon"
              title="Refresh this page"
              onClick={() => window.location.reload()}
              aria-label="Refresh page"
            >
              <RefreshCw className="h-4 w-4" />
            </button>
            <Link
              to="/alerts?status=active"
              className="btn-icon relative"
              title={`${activeCount} active alert${activeCount === 1 ? '' : 's'}`}
              aria-label={`${activeCount} active alerts`}
            >
              <Bell className="h-5 w-5" />
              {activeCount > 0 && (
                <span className="absolute -right-0.5 -top-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-500 px-1 text-[10px] font-bold text-white">
                  {activeCount > 99 ? '99+' : activeCount}
                </span>
              )}
            </Link>
            <Link to="/monitors/new" className="btn-primary !py-2">
              <Plus className="h-4 w-4" />
              <span className="hidden sm:inline">New Monitor</span>
            </Link>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto px-4 py-6 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-7xl">
            <Outlet />
          </div>
        </main>
      </div>
    </div>
  )
}
