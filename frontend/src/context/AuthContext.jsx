import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import api, { TOKEN_KEY } from '../api/client'

const AuthContext = createContext(null)

/**
 * AuthProvider — holds the JWT + current user for the whole app.
 *
 * The token lives in localStorage under `pulsewatch_token` so a refresh
 * keeps the session. On mount, a stored token is validated against
 * GET /api/auth/me; an invalid/expired token is cleared.
 *
 * Backend contract (v4):
 *   POST /api/auth/register {email, password} -> 201 {user, access_token, token_type}
 *   POST /api/auth/login    {email, password} -> {access_token, token_type}
 *   GET  /api/auth/me                         -> {id, email, created_at}
 */
export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem(TOKEN_KEY))
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const clearSession = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY)
    setToken(null)
    setUser(null)
  }, [])

  // Validate any stored token on mount.
  useEffect(() => {
    let cancelled = false
    const stored = localStorage.getItem(TOKEN_KEY)
    if (!stored) {
      setLoading(false)
      return
    }
    api
      .get('/auth/me')
      .then((r) => {
        if (!cancelled) setUser(r.data)
      })
      .catch(() => {
        // Invalid/expired token — clear it. The 401 response interceptor
        // in client.js handles the redirect to /login when needed.
        if (!cancelled) clearSession()
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [clearSession])

  const login = useCallback(async (email, password) => {
    const { data } = await api.post('/auth/login', { email, password })
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setToken(data.access_token)
    // Login returns only the token — fetch the user profile.
    const me = await api.get('/auth/me')
    setUser(me.data)
    return me.data
  }, [])

  const register = useCallback(async (email, password) => {
    const { data } = await api.post('/auth/register', { email, password })
    localStorage.setItem(TOKEN_KEY, data.access_token)
    setToken(data.access_token)
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(() => {
    clearSession()
    window.location.href = '/login'
  }, [clearSession])

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout, loading }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within an AuthProvider')
  return ctx
}
