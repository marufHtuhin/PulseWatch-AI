import { useEffect } from 'react'
import { AlertTriangle } from 'lucide-react'

export function ConfirmDialog({ open, title, message, confirmLabel = 'Confirm', cancelLabel = 'Cancel', onConfirm, onCancel, danger = false, loading = false }) {
  useEffect(() => {
    if (!open) return
    const onKey = (e) => {
      if (e.key === 'Escape') onCancel?.()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm"
      onClick={onCancel}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <div
        className="w-full max-w-md rounded-xl border border-ink-700 bg-ink-900 p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start gap-3">
          <div className={`rounded-full p-2 ${danger ? 'bg-red-500/10 text-red-400' : 'bg-amber-500/10 text-amber-400'}`}>
            <AlertTriangle className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="text-base font-semibold text-white">{title}</h2>
            <p className="mt-1 text-sm leading-relaxed text-slate-400">{message}</p>
          </div>
        </div>
        <div className="mt-6 flex justify-end gap-2">
          <button onClick={onCancel} className="btn-secondary" disabled={loading}>
            {cancelLabel}
          </button>
          <button
            onClick={onConfirm}
            className={danger ? 'btn-danger' : 'btn-primary'}
            disabled={loading}
          >
            {loading ? 'Please wait…' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
