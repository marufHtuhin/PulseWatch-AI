import { createBrowserRouter, RouterProvider } from 'react-router-dom'
import { AppLayout } from './layouts/AppLayout'
import { ToastProvider } from './components/Toast'
import { Dashboard } from './pages/Dashboard'
import { Monitors } from './pages/Monitors'
import { MonitorForm } from './pages/MonitorForm'
import { MonitorDetail } from './pages/MonitorDetail'
import { Alerts } from './pages/Alerts'
import { AlertDetail } from './pages/AlertDetail'
import { Settings } from './pages/Settings'
import { NotFound } from './pages/NotFound'

const router = createBrowserRouter([
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { index: true, element: <Dashboard /> },
      { path: 'monitors', element: <Monitors /> },
      { path: 'monitors/new', element: <MonitorForm /> },
      { path: 'monitors/:id', element: <MonitorDetail /> },
      { path: 'monitors/:id/edit', element: <MonitorForm /> },
      { path: 'alerts', element: <Alerts /> },
      { path: 'alerts/:id', element: <AlertDetail /> },
      { path: 'settings', element: <Settings /> },
      { path: '*', element: <NotFound /> },
    ],
  },
])

export default function App() {
  return (
    <ToastProvider>
      <RouterProvider router={router} />
    </ToastProvider>
  )
}
