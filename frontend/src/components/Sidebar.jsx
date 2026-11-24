import { NavLink, Link } from 'react-router-dom'
import { Activity, Bell, LayoutDashboard, LogOut, MonitorCheck, Plus, Settings, X } from 'lucide-react'
import { useAuth } from '../context/AuthContext'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/monitors', label: 'Monitors', icon: MonitorCheck },
  { to: '/alerts', label: 'Alerts', icon: Bell },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Sidebar({ open, onClose }) {
  const { user, logout } = useAuth()

  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-60 flex-col border-r border-zinc-200 bg-white transition-transform duration-200 lg:static lg:z-auto lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between px-4 py-4">
          <Link to="/" className="flex items-center gap-2.5" onClick={onClose}>
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-zinc-900 text-white">
              <Activity className="h-4 w-4" />
            </span>
            <span className="text-base font-semibold tracking-tight text-zinc-900">PulseWatch</span>
          </Link>
          <button className="btn-icon lg:hidden" onClick={onClose} aria-label="Close menu">
            <X className="h-5 w-5" />
          </button>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon
            return (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                onClick={onClose}
                className={({ isActive }) => `nav-link ${isActive ? 'nav-link-active' : ''}`}
              >
                <Icon className="h-[18px] w-[18px]" />
                {item.label}
              </NavLink>
            )
          })}
        </nav>

        <div className="space-y-2 border-t border-zinc-200 p-3">
          {user && (
            <div className="flex items-center gap-2 px-1">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-100 text-xs font-semibold uppercase text-zinc-700">
                {user.email?.charAt(0) || '?'}
              </span>
              <span className="min-w-0 flex-1 truncate text-sm text-zinc-700" title={user.email}>
                {user.email}
              </span>
              <button
                className="btn-icon shrink-0"
                onClick={logout}
                title="Log out"
                aria-label="Log out"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          )}
          <Link to="/monitors/new" onClick={onClose} className="btn-primary w-full">
            <Plus className="h-4 w-4" />
            New Monitor
          </Link>
        </div>
      </aside>
    </>
  )
}
