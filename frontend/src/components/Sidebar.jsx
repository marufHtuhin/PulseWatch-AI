import { NavLink, Link } from 'react-router-dom'
import { Activity, Bell, LayoutDashboard, MonitorCheck, Plus, Settings, X } from 'lucide-react'

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/monitors', label: 'Monitors', icon: MonitorCheck },
  { to: '/alerts', label: 'Alerts', icon: Bell },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Sidebar({ open, onClose }) {
  return (
    <>
      {/* Mobile overlay */}
      {open && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-64 flex-col border-r border-ink-700/60 bg-ink-900 transition-transform duration-200 lg:static lg:z-auto lg:translate-x-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center justify-between px-5 py-4">
          <Link to="/" className="flex items-center gap-2.5" onClick={onClose}>
            <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
              <Activity className="h-5 w-5" />
            </span>
            <span className="leading-tight">
              <span className="block text-base font-bold tracking-tight text-white">PulseWatch</span>
              <span className="block text-[11px] font-medium uppercase tracking-widest text-emerald-400">AI Monitor</span>
            </span>
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

        <div className="border-t border-ink-700/60 p-3">
          <Link to="/monitors/new" onClick={onClose} className="btn-primary w-full">
            <Plus className="h-4 w-4" />
            New Monitor
          </Link>
          <p className="mt-3 px-1 text-center text-[11px] leading-relaxed text-slate-600">
            Intelligent API monitoring
            <br />
            &amp; anomaly alerts
          </p>
        </div>
      </aside>
    </>
  )
}
