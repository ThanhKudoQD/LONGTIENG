import React, { useState, useEffect, useRef } from 'react'
import api from '../api'
import useStore from '../store'
import ConfirmModal from './ConfirmModal'

interface Props {
  projectId: number
}

/**
 * Toast queue TTS — đọc trực tiếp từ store (tts_queue_state event đã được sync vào store).
 * Hiển thị: sub đang chạy + count pending + nút Hủy tất cả.
 * Auto ẩn 3s sau khi queue rỗng.
 */
export default function BulkTTSProgress({ projectId }: Props) {
  const running = useStore(s => s.ttsQueueRunning)
  const pending = useStore(s => s.ttsQueuePending)
  const subtitles = useStore(s => s.subtitles)

  const [visible, setVisible] = useState(false)
  const [errors, setErrors] = useState<{ subtitle_id: number, error: string }[]>([])
  const [showErrors, setShowErrors] = useState(false)
  const [confirmCancel, setConfirmCancel] = useState(false)
  const hideTimerRef = useRef<number | null>(null)
  const startedAtRef = useRef<number | null>(null)
  const completedRef = useRef<number>(0)
  const totalRef = useRef<number>(0)

  // Lắng nghe error events
  useEffect(() => {
    const onError = (e: Event) => {
      const d = (e as CustomEvent).detail
      setErrors(prev => [...prev.slice(-49), { subtitle_id: d.subtitle_id, error: d.error }])
    }
    window.addEventListener('tts_queue_error', onError)
    return () => window.removeEventListener('tts_queue_error', onError)
  }, [])

  // Theo dõi state để hiện/ẩn toast + tính progress
  useEffect(() => {
    const isActive = running !== null || pending.length > 0
    if (isActive) {
      // Reset hide timer
      if (hideTimerRef.current) {
        clearTimeout(hideTimerRef.current)
        hideTimerRef.current = null
      }
      if (!visible) {
        setVisible(true)
        startedAtRef.current = Date.now()
        completedRef.current = 0
        totalRef.current = (running ? 1 : 0) + pending.length
        setErrors([])
        setShowErrors(false)
      } else {
        // Update total nếu queue tăng (user enqueue thêm)
        const cur = (running ? 1 : 0) + pending.length
        const remaining = totalRef.current - completedRef.current
        if (cur > remaining) {
          // Có sub mới enqueue → tăng total
          totalRef.current += (cur - remaining)
        }
      }
    } else {
      // Queue rỗng → tăng completed = total, ẩn sau 3s
      if (visible && hideTimerRef.current == null) {
        completedRef.current = totalRef.current
        hideTimerRef.current = window.setTimeout(() => {
          setVisible(false)
          startedAtRef.current = null
          completedRef.current = 0
          totalRef.current = 0
        }, 3000)
      }
    }
  }, [running, pending.length, visible])

  // Track completed: mỗi khi running đổi từ X → null hoặc X → Y, tính 1 sub xong
  const prevRunningRef = useRef<number | null>(null)
  useEffect(() => {
    if (prevRunningRef.current !== null && prevRunningRef.current !== running) {
      completedRef.current += 1
    }
    prevRunningRef.current = running
  }, [running])

  if (!visible) return null

  const total = totalRef.current
  const done = completedRef.current
  const pct = total > 0 ? Math.min(100, Math.round((done / total) * 100)) : 0
  const isComplete = running === null && pending.length === 0

  // ETA
  let eta = ''
  if (!isComplete && startedAtRef.current && done > 0) {
    const elapsed = (Date.now() - startedAtRef.current) / 1000
    const avgPerSub = elapsed / done
    const remaining = total - done
    const etaSec = remaining * avgPerSub
    if (etaSec > 60) eta = `~${Math.round(etaSec / 60)} phút`
    else eta = `~${Math.round(etaSec)} giây`
  }

  // Tìm text của sub đang chạy
  const runningSub = running != null ? subtitles.find(s => s.id === running) : null
  const runningText = runningSub ? (runningSub.text || '').slice(0, 50) : ''

  const handleCancel = () => {
    setConfirmCancel(true)
  }

  const doCancel = async () => {
    setConfirmCancel(false)
    try {
      await api.post(`/tts/queue/cancel/${projectId}`)
      // Reset total ngay để UI cập nhật đúng (chỉ còn sub đang chạy nếu có)
      const curRunning = useStore.getState().ttsQueueRunning
      totalRef.current = completedRef.current + (curRunning ? 1 : 0)
    } catch (e) {
      console.error(e)
    }
  }

  const handleClose = () => {
    setVisible(false)
    if (hideTimerRef.current) {
      clearTimeout(hideTimerRef.current)
      hideTimerRef.current = null
    }
  }

  let bgColor = 'bg-blue-600'
  let title = '🎙️ Đang tạo TTS'
  if (isComplete) {
    bgColor = errors.length > 0 ? 'bg-amber-600' : 'bg-emerald-600'
    title = errors.length > 0 ? '⚠️ Hoàn tất (có lỗi)' : '✅ Hoàn tất'
  }

  return (
    <div className="fixed bottom-4 right-4 z-40 w-96 max-w-[calc(100vw-2rem)] bg-white dark:bg-zinc-900 rounded-xl shadow-2xl overflow-hidden border border-zinc-200 dark:border-zinc-700">
      {/* Header */}
      <div className={`${bgColor} text-white px-4 py-2 flex items-center justify-between`}>
        <span className="font-semibold text-[13px]">{title}</span>
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

        <div className="flex items-center justify-between text-[12px] mb-2">
          <span className="font-mono tabular-nums">
            <span className="font-bold">{done}</span>
            <span className="text-zinc-400">/{total}</span>
            <span className="text-zinc-500 ml-2">({pct}%)</span>
          </span>
          {!isComplete && eta && (
            <span className="text-zinc-500 text-[11px]">⏱ Còn {eta}</span>
          )}
        </div>

        {!isComplete && running != null && (
          <div className="text-[11px] text-zinc-500 mb-2 truncate">
            ▶ Đang xử lý #{running}{runningText ? `: "${runningText}${runningText.length >= 50 ? '...' : ''}"` : ''}
          </div>
        )}

        {!isComplete && pending.length > 0 && (
          <div className="text-[11px] text-zinc-400 mb-3">
            ⏱ {pending.length} dòng trong hàng chờ
          </div>
        )}

        {errors.length > 0 && (
          <div className="mb-3">
            <button onClick={() => setShowErrors(v => !v)}
              className="text-[12px] text-red-500 underline hover:text-red-700">
              ✗ {errors.length} lỗi {showErrors ? '▲' : '▼'}
            </button>
            {showErrors && (
              <div className="max-h-32 overflow-y-auto bg-red-50 dark:bg-red-950/30 rounded p-2 text-[11px] font-mono mt-1">
                {errors.map((err, i) => (
                  <div key={i} className="text-red-600 dark:text-red-400 truncate">
                    #{err.subtitle_id}: {err.error}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {!isComplete && (
          <button onClick={handleCancel}
            className="w-full px-3 py-1.5 text-[12px] rounded-lg border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/30 text-red-600 hover:bg-red-100 font-semibold">
            🛑 Hủy tất cả hàng chờ
          </button>
        )}
      </div>

      <ConfirmModal
        open={confirmCancel}
        title="Hủy hàng chờ TTS?"
        message={`Sẽ xóa ${pending.length} dòng đang chờ trong hàng chờ.`}
        warnings={running != null ? [`Dòng đang xử lý (#${running}) vẫn tiếp tục đến khi xong, không thể ngắt giữa chừng.`] : []}
        variant="danger"
        confirmText="Hủy hàng chờ"
        cancelText="Để tôi xem lại"
        onConfirm={doCancel}
        onCancel={() => setConfirmCancel(false)}
      />
    </div>
  )
}