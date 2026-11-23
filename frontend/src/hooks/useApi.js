import { useCallback, useEffect, useRef, useState } from 'react'
import { apiErrorMessage } from '../api/client'

/**
 * useApi — fetch data with loading/error state and optional polling.
 *
 * @param {Function} fetcher - async function returning the data (receives an AbortSignal-aware call via `isCurrent` guard)
 * @param {Array} deps - re-fetch when these change
 * @param {Object} options
 * @param {number|null} options.pollIntervalMs - refetch every N ms (no loading spinner on polls)
 * @param {*} options.initialData - initial data value
 */
export function useApi(fetcher, deps = [], { pollIntervalMs = null, initialData = null } = {}) {
  const [data, setData] = useState(initialData)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const fetcherRef = useRef(fetcher)
  fetcherRef.current = fetcher

  const fetchData = useCallback(
    async ({ silent = false } = {}) => {
      if (!silent) setLoading(true)
      setError(null)
      try {
        const result = await fetcherRef.current()
        setData(result)
      } catch (err) {
        // Ignore cancellations
        if (err?.code === 'ERR_CANCELED') return
        setError(apiErrorMessage(err))
      } finally {
        setLoading(false)
      }
    },
    []
  )

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setLoading(true)
      setError(null)
      try {
        const result = await fetcherRef.current()
        if (!cancelled) setData(result)
      } catch (err) {
        if (err?.code === 'ERR_CANCELED') return
        if (!cancelled) setError(apiErrorMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()

    let timer = null
    if (pollIntervalMs) {
      timer = setInterval(() => {
        fetcherRef
          .current()
          .then((result) => {
            if (!cancelled) {
              setData(result)
              setError(null)
            }
          })
          .catch(() => {
            // Polling failures are silent — the last good data stays visible
          })
      }, pollIntervalMs)
    }
    return () => {
      cancelled = true
      if (timer) clearInterval(timer)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollIntervalMs])

  const refetch = useCallback(() => fetchData(), [fetchData])

  return { data, loading, error, refetch, setData }
}

/** useToast hook — re-exported from the Toast context for convenience. */
export { useToast } from '../components/Toast'
