/**
 * RenderQueuePanel — danh sách render job đang chạy / đã xong.
 * v4.0: thêm thống kê thời gian render (định dạng giờ:phút:giây).
 */
import React, { useState, useEffect } from 'react'
import { ExportJob } from './types'

interface Props {
  jobs: ExportJob[]
  onCancel: (id: number) => void
  onClear: (id: number) => void
}

export default function RenderQueuePanel({ jobs, onCancel, onClear }: Props) {
  const [collapsed, setCollapsed] = useState(false)
  const running = jobs.filter(j => j.status === 'running' || j.status === 'pending').length

  return (
    <div className="border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex-shrink-0">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full px-4 py-2 flex items-center gap-3 text-[12px] hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors"
      >
        <span>{collapsed ? '▸' : '▾'}</span>
        <span className="font-semibold">Render Queue</span>
        <span className="text-zinc-500">·</span>
        <span className="text-zinc-600 dark:text-zinc-400">
          {jobs.length} job{running > 0 ? ` · ${running} đang chạy` : ''}
        </span>
      </button>

      {!collapsed && (
        <div className="max-h-48 overflow-y-auto px-4 pb-3 space-y-2">
          {jobs.map(j => (
            <JobRow key={j.id} job={j} onCancel={onCancel} onClear={onClear} />
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * Parse ISO string an toàn — giả định UTC nếu không có timezone suffix.
 * "2026-05-29T07:14:23" → coi là UTC (thêm 'Z')
 * "2026-05-29T07:14:23Z" → đã UTC, parse bình thường
 * "2026-05-29T14:14:23+07:00" → có TZ, parse bình thường
 */
function parseIsoAsUtc(s: string | null | undefined): number | null {
  if (!s) return null
  // Có TZ? (Z hoặc ±HH:MM ở cuối)
  const hasTz = /Z$|[+-]\d{2}:?\d{2}$/.test(s)
  const safe = hasTz ? s : s + 'Z'
  const t = new Date(safe).getTime()
  return isNaN(t) ? null : t
}

function JobRow({ job, onCancel, onClear }: { job: ExportJob; onCancel: (id: number) => void; onClear: (id: number) => void }) {
  const isRunning = job.status === 'running' || job.status === 'pending'
  const isDone = job.status === 'done'
  const isError = job.status === 'error'
  const isCancel = job.status === 'cancelled'

  // Tick mỗi giây để hiện thời gian chạy realtime
  const [, tick] = useState(0)
  useEffect(() => {
    if (!isRunning) return
    const tid = setInterval(() => tick(n => n + 1), 1000)
    return () => clearInterval(tid)
  }, [isRunning])

  // Thời gian render: ưu tiên started_at, fallback created_at. Parse luôn dưới dạng UTC.
  const startMs = parseIsoAsUtc(job.started_at) ?? parseIsoAsUtc(job.created_at)
  const endMs   = parseIsoAsUtc(job.finished_at) ?? (isRunning ? Date.now() : null)
  const elapsedSec = (startMs != null && endMs != null) ? Math.max(0, (endMs - startMs) / 1000) : null

  return (
    <div className="flex items-center gap-3 text-[12px] py-1.5">
      <span className="w-5 text-center">
        {isRunning && '⏳'}
        {isDone && '✓'}
        {isError && '✕'}
        {isCancel && '⊗'}
      </span>

      <span className="font-mono text-[11px] text-zinc-500 w-12">#{job.id}</span>

      {/* Progress bar / status */}
      <div className="flex-1 max-w-md">
        {isRunning ? (
          <div className="h-2 bg-zinc-200 dark:bg-zinc-700 rounded-full overflow-hidden">
            <div className="h-full bg-blue-500 transition-all" style={{ width: `${job.progress_percent}%` }} />
          </div>
        ) : (
          <div className="text-[11px] text-zinc-500 truncate">
            {isDone && (
              <span>
                <span className="text-emerald-600 dark:text-emerald-400">✓ Hoàn tất</span>
                {elapsedSec != null && (
                  <span className="ml-2 text-zinc-500">
                    · ⏱ {formatDuration(elapsedSec)}
                  </span>
                )}
              </span>
            )}
            {isError && <span className="text-red-600">✕ {job.error_msg || 'Render thất bại'}</span>}
            {isCancel && <span>⊗ Đã hủy{elapsedSec != null && ` · ${formatDuration(elapsedSec)}`}</span>}
          </div>
        )}
      </div>

      {/* Progress % / ETA / thời gian chạy */}
      {isRunning && (
        <span className="font-mono text-[11px] text-zinc-500 w-32 text-right">
          {job.progress_percent.toFixed(0)}%
          {elapsedSec != null && (
            <span className="ml-1 text-zinc-400">· ⏱ {formatDuration(elapsedSec)}</span>
          )}
          {job.estimated_remaining_sec && job.estimated_remaining_sec > 0 && (
            <span className="ml-1 text-zinc-400">· còn {formatDuration(job.estimated_remaining_sec)}</span>
          )}
        </span>
      )}

      {/* Actions */}
      <div className="flex gap-1 w-20 justify-end">
        {isRunning && (
          <button onClick={() => onCancel(job.id)}
            className="px-2 py-0.5 text-[11px] text-red-600 hover:bg-red-50 dark:hover:bg-red-950 rounded">
            ⊗ Hủy
          </button>
        )}
        {isDone && job.output_url && (
          <a href={job.output_url} download
            className="px-2 py-0.5 text-[11px] text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950 rounded">
            ↓ Tải
          </a>
        )}
        {!isRunning && (
          <button onClick={() => onClear(job.id)}
            className="px-2 py-0.5 text-[11px] text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded">
            ✕
          </button>
        )}
      </div>
    </div>
  )
}

/**
 * Format duration theo giờ:phút:giây hoặc phút:giây hoặc giây.
 *   3725s → 1g 02p 05s
 *    125s →   02p 05s
 *     45s →       45s
 */
function formatDuration(totalSec: number): string {
  totalSec = Math.max(0, Math.round(totalSec))
  const h = Math.floor(totalSec / 3600)
  const m = Math.floor((totalSec % 3600) / 60)
  const s = totalSec % 60
  if (h > 0) return `${h}g ${String(m).padStart(2, '0')}p ${String(s).padStart(2, '0')}s`
  if (m > 0) return `${m}p ${String(s).padStart(2, '0')}s`
  return `${s}s`
}
