import { createBrowserRouter, Navigate, Outlet, RouterProvider } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import { ToastProvider } from './components/Toast'
import { AuthProvider, useAuth } from './context/AuthContext'
import { Dashboard } from './pages/Dashboard'
import { Monitors } from './pages/Monitors'
import { MonitorForm } from './pages/MonitorForm'
import { MonitorDetail } from './pages/MonitorDetail'
import { Alerts } from './pages/Alerts'
import { AlertDetail } from './pages/AlertDetail'
import { Settings } from './pages/Settings'
import { Admin } from './pages/Admin'
import { Login } from './pages/Login'
import { Register } from './pages/Register'
import { ForgotPassword } from './pages/ForgotPassword'
import { ResetPassword } from './pages/ResetPassword'
import { NotFound } from './pages/NotFound'

/**
 * ProtectedRoute — renders the app only for signed-in users. While the
 * initial /auth/me check is still running, show a minimal loading state
 * instead of flashing the login page on refresh.
 */
function ProtectedRoute() {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center" aria-busy="true" aria-label="Loading">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-zinc-300 border-t-zinc-900" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <Outlet />
}

/**
 * AdminRoute — nested inside ProtectedRoute, so `user` is guaranteed set.
 * Non-admins are sent back to the dashboard.
 */
function AdminRoute() {
  const { user } = useAuth()
  if (!user?.is_admin) return <Navigate to="/dashboard" replace />
  return <Outlet />
}

const router = createBrowserRouter([
  // Public auth pages — no app layout, /login is the entry point.
  { path: '/login', element: <Login /> },
  { path: '/register', element: <Register /> },
  { path: '/forgot-password', element: <ForgotPassword /> },
  { path: '/reset-password', element: <ResetPassword /> },
  {
    element: <ProtectedRoute />,
    children: [
      {
        path: '/',
        element: <AppLayout />,
        children: [
          { index: true, element: <Dashboard /> },
          // Alias so /dashboard (e.g. the AdminRoute redirect target) lands
          // on the dashboard instead of the NotFound page.
          { path: 'dashboard', element: <Dashboard /> },
          { path: 'monitors', element: <Monitors /> },
          { path: 'monitors/new', element: <MonitorForm /> },
          { path: 'monitors/:id', element: <MonitorDetail /> },
          { path: 'monitors/:id/edit', element: <MonitorForm /> },
          { path: 'alerts', element: <Alerts /> },
          { path: 'alerts/:id', element: <AlertDetail /> },
          { path: 'settings', element: <Settings /> },
          {
            element: <AdminRoute />,
            children: [{ path: 'admin', element: <Admin /> }],
          },
          { path: '*', element: <NotFound /> },
        ],
      },
    ],
  },
])

export default function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </AuthProvider>
  )
}
