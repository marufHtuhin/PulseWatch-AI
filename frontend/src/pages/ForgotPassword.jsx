import { useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { Activity, CheckCircle2 } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { apiErrorMessage, forgotPassword } from '../api/client'

export function ForgotPassword() {
  const { user, loading: authLoading } = useAuth()
  const [email, setEmail] = useState('')
  const [error, setError] = useState(null)
  const [submitted, setSubmitted] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  // Already signed in — go straight to the dashboard.
  if (!authLoading && user) return <Navigate to="/" replace />

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      // The API always returns 200 here, whether or not the account
      // exists — we show the same generic message either way.
      await forgotPassword({ email: email.trim() })
      setSubmitted(true)
    } catch (err) {
      setError(apiErrorMessage(err, 'Could not send the reset code — please try again.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center px-4 py-12">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="flex h-10 w-10 items-center justify-center rounded-lg bg-zinc-900 text-white">
            <Activity className="h-5 w-5" />
          </span>
          <h1 className="mt-4 text-xl font-semibold tracking-tight text-zinc-900">PulseWatch</h1>
          <p className="mt-1 text-sm text-zinc-500">Reset your password</p>
        </div>

        <div className="card p-6">
          {submitted ? (
            <div className="space-y-4">
              <div className="flex items-start gap-2.5 rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700" role="status">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                <span>
                  If an account exists for this email, a reset code has been sent. Check your
                  inbox.
                </span>
              </div>
              <Link to="/reset-password" className="btn-primary w-full">
                Have a code? Reset your password
              </Link>
              <p className="text-center text-sm text-zinc-500">
                <Link to="/login" className="font-medium text-zinc-900 hover:underline">
                  Back to log in
                </Link>
              </p>
            </div>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              {error && (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                  {error}
                </div>
              )}
              <p className="text-sm text-zinc-500">
                Enter the email you signed up with and we&apos;ll send you a 6-digit reset code.
              </p>
              <div>
                <label htmlFor="email" className="label">Email</label>
                <input
                  id="email"
                  type="email"
                  className="input"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  autoComplete="email"
                  autoFocus
                />
              </div>
              <button type="submit" className="btn-primary w-full" disabled={submitting}>
                {submitting ? 'Sending…' : 'Send reset code'}
              </button>
              <p className="text-center text-sm text-zinc-500">
                Have a code?{' '}
                <Link to="/reset-password" className="font-medium text-zinc-900 hover:underline">
                  Reset your password
                </Link>
              </p>
              <p className="text-center text-sm text-zinc-500">
                <Link to="/login" className="font-medium text-zinc-900 hover:underline">
                  Back to log in
                </Link>
              </p>
            </form>
          )}
        </div>
      </div>
    </div>
  )
}
