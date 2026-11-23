import { createContext, useCallback, useContext, useMemo, useState } from 'react'
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'

const ToastContext = createContext(null)

const ICONS = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
}

const STYLES = {
  success: 'border-emerald-500/40 text-emerald-400',
  error: 'border-red-500/40 text-red-400',
  warning: 'border-amber-500/40 text-amber-400',
  info: 'border-sky-500/40 text-sky-400',
}

let nextId = 1

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([])

  const dismiss = useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id))
  }, [])

  const push = useCallback(
    (type, message, { duration = 5000 } = {}) => {
      const id = nextId++
      setToasts((prev) => [...prev.slice(-4), { id, type, message }])
      if (duration > 0) {
        setTimeout(() => dismiss(id), duration)
      }
    },
    [dismiss]
  )

  const value = useMemo(
    () => ({
      success: (msg, opts) => push('success', msg, opts),
      error: (msg, opts) => push('error', msg, opts),
      warning: (msg, opts) => push('warning', msg, opts),
      info: (msg, opts) => push('info', msg, opts),
    }),
    [push]
  )

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-[min(92vw,380px)] flex-col gap-2">
        {toasts.map((toast) => {
          const Icon = ICONS[toast.type] || Info
          return (
            <div
              key={toast.id}
              className={`pointer-events-auto flex items-start gap-2.5 rounded-xl border bg-ink-900/95 px-3.5 py-3 shadow-xl backdrop-blur ${STYLES[toast.type] || STYLES.info}`}
              role="alert"
            >
              <Icon className="mt-0.5 h-4 w-4 shrink-0" />
              <p className="flex-1 text-sm leading-snug text-slate-100">{toast.message}</p>
              <button
                onClick={() => dismiss(toast.id)}
                className="shrink-0 rounded p-0.5 text-slate-500 hover:text-slate-200"
                aria-label="Dismiss notification"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          )
        })}
      </div>
    </ToastContext.Provider>
  )
}

export function useToast() {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>')
  return ctx
}
