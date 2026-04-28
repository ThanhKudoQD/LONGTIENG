import React, { useState, useEffect, useRef } from 'react'
import api from '../api'

interface BulkState {
  jobId: string
  total: number
  current: number
  currentSubId: number | null
  success: number
  failed: number
  errors: { subtitle_id: number, error: string }[]
  status: 'running' | 'done' | 'cancelled' | 'error'
  startedAt: number
}

interface Props {
  projectId: number
}

/**
 * Lắng nghe WS events tts_bulk_* và hiển thị toast tiến trình.
 * Toast tự ẩn sau 5s khi done/cancelled (trừ khi có lỗi thì giữ).
 */
export default function BulkTTSProgress({ projectId }: Props) {
  const [state, setState] = useState<BulkState | null>(null)
  const [showErrors, setShowErrors] = useState(false)
  const recentTimesRef = useRef<number[]>([])  // timestamps các sub xong gần đây để tính ETA
  const hideTimerRef = useRef<number | null>(null)

  useEffect(() => {
    const onStart = (e: Event) => {
      const d = (e as CustomEvent).detail
      recentTimesRef.current = [Date.now()]
      if (hideTimerRef.current) { clearTimeout(hideTimerRef.current); hideTimerRef.current = null }
      setState({
        jobId: d.job_id,
        total: d.total,
        current: 0,
        currentSubId: null,
        success: 0,
        failed: 0,
        errors: [],
        status: 'running',
        startedAt: Date.now(),
      })
      setShowErrors(false)
    }
    const onProgress = (e: Event) => {
      const d = (e as CustomEvent).detail
      recentTimesRef.current.push(Date.now())
      if (recentTimesRef.current.length > 20) recentTimesRef.current.shift()
      setState(prev => prev ? {
        ...prev,
        current: d.current,
        currentSubId: d.subtitle_id,
      } : prev)
    }
    const onDone = (e: Event) => {
      const d = (e as CustomEvent).detail
      setState(prev => prev ? {
        ...prev,
        current: d.total,
        success: d.success,
        failed: d.failed,
        errors: d.errors || [],
        status: 'done',
      } : prev)
      // Auto hide sau 5s nếu không có lỗi
      const autoHide = (d.failed === 0)
      if (autoHide) {
        hideTimerRef.current = window.setTimeout(() => setState(null), 5000)
      }
    }
    const onCancelled = (e: Event) => {
      const d = (e as CustomEvent).detail
      setState(prev => prev ? {
        ...prev,
        current: d.current,
        status: 'cancelled',
      } : prev)
      hideTimerRef.current = window.setTimeout(() => setState(null), 4000)
    }

    window.addEventListener('tts_bulk_start', onStart)
    window.addEventListener('tts_bulk_progress', onProgress)
    window.addEventListener('tts_bulk_done', onDone)
    window.addEventListener('tts_bulk_cancelled', onCancelled)
    return () => {
      window.removeEventListener('tts_bulk_start', onStart)
      window.removeEventListener('tts_bulk_progress', onProgress)
      window.removeEventListener('tts_bulk_done', onDone)
      window.removeEventListener('tts_bulk_cancelled', onCancelled)
      if (hideTimerRef.current) clearTimeout(hideTimerRef.current)
    }
  }, [])

  if (!state) return null

  const handleCancel = async () => {
    if (!confirm('Hủy quá trình tạo TTS? Các audio đã tạo sẽ được giữ lại.')) return
    try {
      await api.post(`/tts/bulk/cancel/${projectId}`)
    } catch (e) {
      console.error(e)
    }
  }

  const handleClose = () => {
    setState(null)
    if (hideTimerRef.current) { clearTimeout(hideTimerRef.current); hideTimerRef.current = null }
  }

  // Tính ETA
  const pct = state.total > 0 ? Math.round((state.current / state.total) * 100) : 0
  const elapsed = (Date.now() - state.startedAt) / 1000

  let eta = ''
  if (state.status === 'running' && recentTimesRef.current.length >= 3 && state.current > 0) {
    const recent = recentTimesRef.current
    const avgGap = (recent[recent.length - 1] - recent[0]) / (recent.length - 1) / 1000
    const remaining = state.total - state.current
    const etaSec = remaining * avgGap
    if (etaSec > 60) eta = `~${Math.round(etaSec / 60)} phút`
    else eta = `~${Math.round(etaSec)} giây`
  }

  let bgColor = 'bg-blue-600'
  let title = '🎙️ Đang tạo TTS'
  let titleSuffix = ''
  if (state.status === 'done') {
    bgColor = state.failed > 0 ? 'bg-amber-600' : 'bg-emerald-600'
    title = state.failed > 0 ? '⚠️ Tạo TTS xong (có lỗi)' : '✅ Tạo TTS xong'
  } else if (state.status === 'cancelled') {
    bgColor = 'bg-zinc-600'
    title = '🛑 Đã hủy'
  }

  return (
    <div className="fixed bottom-4 right-4 z-40 w-96 max-w-[calc(100vw-2rem)] bg-white dark:bg-zinc-900 rounded-xl shadow-2xl overflow-hidden border border-zinc-200 dark:border-zinc-700">
      {/* Header bar */}
      <div className={`${bgColor} text-white px-4 py-2 flex items-center justify-between`}>
        <span className="font-semibold text-[13px]">{title}{titleSuffix}</span>
        <button onClick={handleClose} className="text-white/80 hover:text-white text-lg leading-none">×</button>
      </div>

      {/* Body */}
      <div className="p-4">
        {/* Progress bar */}
        <div className="relative h-2 bg-zinc-200 dark:bg-zinc-700 rounded-full overflow-hidden mb-2">
          <div
            className={`absolute inset-y-0 left-0 ${bgColor} transition-all duration-300`}
            style={{ width: `${pct}%` }}
          />
        </div>

        {/* Numbers */}
        <div className="flex items-center justify-between text-[12px] mb-2">
          <span className="font-mono tabular-nums">
            <span className="font-bold">{state.current}</span>
            <span className="text-zinc-400">/{state.total}</span>
            <span className="text-zinc-500 ml-2">({pct}%)</span>
          </span>
          {eta && state.status === 'running' && (
            <span className="text-zinc-500 text-[11px]">⏱ Còn {eta}</span>
          )}
          {state.status === 'done' && (
            <span className="text-zinc-500 text-[11px]">⏱ {Math.round(elapsed)}s</span>
          )}
        </div>

        {/* Status detail */}
        {state.status === 'running' && state.currentSubId && (
          <div className="text-[11px] text-zinc-500 mb-3">
            ▶ Đang xử lý #{state.currentSubId}...
          </div>
        )}
        {state.status === 'done' && (
          <div className="text-[12px] mb-3">
            <span className="text-emerald-600">✓ {state.success} thành công</span>
            {state.failed > 0 && (
              <button onClick={() => setShowErrors(v => !v)} className="text-red-600 ml-3 underline">
                ✗ {state.failed} lỗi
              </button>
            )}
          </div>
        )}
        {state.status === 'cancelled' && (
          <div className="text-[12px] text-zinc-500 mb-3">
            Đã dừng tại {state.current}/{state.total}
          </div>
        )}

        {/* Error list */}
        {showErrors && state.errors.length > 0 && (
          <div className="max-h-32 overflow-y-auto bg-red-50 dark:bg-red-950/30 rounded p-2 text-[11px] font-mono mb-3">
            {state.errors.map((err, i) => (
              <div key={i} className="text-red-600 dark:text-red-400 truncate">
                #{err.subtitle_id}: {err.error}
              </div>
            ))}
          </div>
        )}

        {/* Actions */}
        {state.status === 'running' && (
          <button onClick={handleCancel}
            className="w-full px-3 py-1.5 text-[12px] rounded-lg border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/30 text-red-600 hover:bg-red-100 font-semibold">
            🛑 Hủy
          </button>
        )}
      </div>
    </div>
  )
}
