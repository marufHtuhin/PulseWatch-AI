import { useEffect, useRef, useState } from 'react'
import { Link, Outlet } from 'react-router-dom'
import { Bell, ChevronDown, KeyRound, LogOut, Menu, RefreshCw } from 'lucide-react'
import { Sidebar } from '../components/Sidebar'
import { useApi } from '../hooks/useApi'
import { listAlerts } from '../api/client'
import { useAuth } from '../context/AuthContext'

export function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  const { user, logout } = useAuth()

  // Header user menu — closes on outside click and on Escape.
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)
  useEffect(() => {
    if (!menuOpen) return
    const onPointerDown = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setMenuOpen(false)
      }
    }
    const onKeyDown = (e) => {
      if (e.key === 'Escape') setMenuOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [menuOpen])

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
        <header className="sticky top-0 z-20 flex items-center justify-between gap-3 border-b border-zinc-200 bg-white/90 px-4 py-3 backdrop-blur sm:px-6">
          <div className="flex items-center gap-2">
            <button
              className="btn-icon lg:hidden"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>
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
                <span className="absolute -right-0.5 -top-0.5 flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
                  {activeCount > 99 ? '99+' : activeCount}
                </span>
              )}
            </Link>

            {/* User menu — the one place for account actions. */}
            {user && (
              <div className="relative" ref={menuRef}>
                <button
                  className="flex items-center gap-2 rounded-md px-1.5 py-1 text-sm text-zinc-700 transition hover:bg-zinc-100"
                  onClick={() => setMenuOpen((v) => !v)}
                  aria-haspopup="menu"
                  aria-expanded={menuOpen}
                  aria-label="Account menu"
                >
                  <span className="flex h-7 w-7 items-center justify-center rounded-full bg-zinc-100 text-xs font-semibold uppercase text-zinc-700">
                    {user.email?.charAt(0) || '?'}
                  </span>
                  <ChevronDown className={`h-4 w-4 text-zinc-400 transition-transform ${menuOpen ? 'rotate-180' : ''}`} />
                </button>
                {menuOpen && (
                  <div
                    className="absolute right-0 top-full z-30 mt-1 w-60 overflow-hidden rounded-lg border border-zinc-200 bg-white py-1 shadow-lg"
                    role="menu"
                  >
                    <div className="border-b border-zinc-100 px-3 py-2">
                      <p className="text-[11px] font-medium uppercase tracking-wider text-zinc-400">
                        Signed in as
                      </p>
                      <p className="truncate text-sm font-medium text-zinc-900" title={user.email}>
                        {user.email}
                      </p>
                    </div>
                    <Link
                      to="/settings"
                      onClick={() => setMenuOpen(false)}
                      className="flex items-center gap-2 px-3 py-2 text-sm text-zinc-700 transition hover:bg-zinc-50"
                      role="menuitem"
                    >
                      <KeyRound className="h-4 w-4 text-zinc-400" />
                      Change password
                    </Link>
                    <button
                      onClick={logout}
                      className="flex w-full items-center gap-2 px-3 py-2 text-sm text-red-600 transition hover:bg-red-50"
                      role="menuitem"
                    >
                      <LogOut className="h-4 w-4" />
                      Log out
                    </button>
                  </div>
                )}
              </div>
            )}
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
