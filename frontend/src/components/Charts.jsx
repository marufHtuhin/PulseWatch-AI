import { useMemo } from 'react'
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { formatMs, formatTimeOnly } from '../utils/format'

const LINE_COLORS = ['#10b981', '#38bdf8', '#f59e0b', '#f472b6', '#a78bfa', '#34d399']

/**
 * Response-time trend chart.
 * Accepts either dashboard performance points
 * ({ time, monitor_name, response_time_ms, is_success }) or monitoring
 * history records ({ checked_at, response_time_ms, is_success }).
 * When multiple monitors are present, one line per monitor is drawn.
 */
export function ResponseTimeChart({ points = [], height = 280, latencyThresholdMs = null, singleSeries = false }) {
  const { chartData, series } = useMemo(() => {
    if (!points || points.length === 0) return { chartData: [], series: [] }

    const normalized = points
      .map((p) => ({
        time: p.time || p.checked_at,
        name: p.monitor_name || 'Response time',
        ms: p.response_time_ms,
        ok: p.is_success !== false,
      }))
      .filter((p) => p.time && p.ms !== null && p.ms !== undefined)
      .sort((a, b) => new Date(a.time) - new Date(b.time))

    if (singleSeries || new Set(normalized.map((p) => p.name)).size <= 1) {
      const label = singleSeries ? 'Response time' : normalized[0]?.name || 'Response time'
      return {
        chartData: normalized.map((p) => ({ time: p.time, [label]: p.ms })),
        series: [{ key: label, color: LINE_COLORS[0] }],
      }
    }

    const names = [...new Set(normalized.map((p) => p.name))]
    const byTime = new Map()
    for (const p of normalized) {
      if (!byTime.has(p.time)) byTime.set(p.time, { time: p.time })
      byTime.get(p.time)[p.name] = p.ms
    }
    return {
      chartData: [...byTime.values()],
      series: names.map((name, i) => ({ key: name, color: LINE_COLORS[i % LINE_COLORS.length] })),
    }
  }, [points, singleSeries])

  if (chartData.length === 0) {
    return (
      <div className="flex h-[220px] items-center justify-center text-sm text-slate-500">
        No response-time data yet — checks will appear here once monitors run.
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" vertical={false} />
        <XAxis
          dataKey="time"
          tickFormatter={(t) => formatTimeOnly(t)}
          tickLine={false}
          axisLine={{ stroke: '#243349' }}
          minTickGap={40}
        />
        <YAxis
          tickFormatter={(v) => formatMs(v)}
          tickLine={false}
          axisLine={false}
          width={70}
          domain={[0, 'auto']}
        />
        <Tooltip
          contentStyle={{
            background: '#0f172a',
            border: '1px solid #243349',
            borderRadius: 10,
            fontSize: 12,
            color: '#e2e8f0',
          }}
          labelFormatter={(t) => new Date(t).toLocaleString()}
          formatter={(value, name) => [formatMs(value), name]}
        />
        {series.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
        {latencyThresholdMs ? (
          <ReferenceLine
            y={latencyThresholdMs}
            stroke="#f59e0b"
            strokeDasharray="4 4"
            label={{ value: `Threshold ${formatMs(latencyThresholdMs)}`, fill: '#f59e0b', fontSize: 11, position: 'insideTopRight' }}
          />
        ) : null}
        {series.map((s) => (
          <Line
            key={s.key}
            type="monotone"
            dataKey={s.key}
            stroke={s.color}
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

/**
 * StatusHistory — a row of small bars, one per check (newest on the right),
 * green = success, red = failure. Hover shows time + status code.
 */
export function StatusHistory({ records = [], maxBars = 40 }) {
  const bars = useMemo(() => {
    const sorted = [...records].sort((a, b) => new Date(a.checked_at) - new Date(b.checked_at))
    return sorted.slice(-maxBars)
  }, [records, maxBars])

  if (bars.length === 0) {
    return <p className="text-sm text-slate-500">No checks recorded yet.</p>
  }

  const uptime = bars.length ? (bars.filter((r) => r.is_success).length / bars.length) * 100 : 0

  return (
    <div>
      <div className="flex items-end gap-[3px]" role="img" aria-label={`Last ${bars.length} checks, ${uptime.toFixed(1)}% successful`}>
        {bars.map((r) => (
          <div
            key={r.id}
            title={`${new Date(r.checked_at).toLocaleString()} — ${r.is_success ? 'OK' : 'Failed'}${r.status_code ? ` (${r.status_code})` : ''}${r.response_time_ms != null ? ` · ${formatMs(r.response_time_ms)}` : ''}`}
            className={`h-8 flex-1 rounded-sm ${r.is_success ? 'bg-emerald-500/80' : 'bg-red-500/80'}`}
          />
        ))}
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-slate-500">
        <span>
          Last {bars.length} check{bars.length === 1 ? '' : 's'}
        </span>
        <span>
          <span className="font-medium text-slate-300">{uptime.toFixed(1)}%</span> successful in this window
        </span>
      </div>
    </div>
  )
}
