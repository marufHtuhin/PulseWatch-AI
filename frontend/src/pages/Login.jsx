import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Activity } from 'lucide-react'
import { useAuth } from '../context/AuthContext'
import { apiErrorMessage } from '../api/client'

export function Login() {
  const { user, loading: authLoading, login } = useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  // Already signed in — go straight to the dashboard.
  if (!authLoading && user) return <Navigate to="/" replace />

  async function handleSubmit(e) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      await login(email.trim(), password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(apiErrorMessage(err, 'Login failed — check your email and password.'))
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
          <p className="mt-1 text-sm text-zinc-500">Sign in to monitor your APIs</p>
        </div>

        <div className="card p-6">
          <form onSubmit={handleSubmit} className="space-y-4">
            {error && (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
                {error}
              </div>
            )}
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
            <div>
              <label htmlFor="password" className="label">Password</label>
              <input
                id="password"
                type="password"
                className="input"
                placeholder="Your password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
              />
            </div>
            <button type="submit" className="btn-primary w-full" disabled={submitting}>
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        </div>

        <p className="mt-4 text-center text-sm text-zinc-500">
          No account?{' '}
          <Link to="/register" className="font-medium text-zinc-900 hover:underline">
            Register
          </Link>
        </p>
      </div>
    </div>
  )
}
