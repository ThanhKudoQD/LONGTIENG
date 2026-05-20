import React, { useEffect, useState } from 'react'
import useUndoStore, { UNDO_TIMEOUT_MS } from '../store/undo'

/**
 * Toast "Hoàn tác" — góc TRÁI DƯỚI màn hình.
 *
 * UX:
 *   - Hiện khi có `current` trong useUndoStore.
 *   - Label + nút "Hoàn tác" + nút X dismiss.
 *   - Progress bar countdown 8s — chạy mượt bằng CSS transition.
 *   - Bấm "Hoàn tác" → gọi store.undo() (tự clear).
 *   - Bấm X → store.dismiss() (KHÔNG gọi onExpire).
 *   - Hết countdown → tự ẩn (timer trong store đã clear).
 */
export default function UndoToast() {
  const current = useUndoStore(s => s.current)
  const undo    = useUndoStore(s => s.undo)
  const dismiss = useUndoStore(s => s.dismiss)
  const [busy, setBusy] = useState(false)

  // Reset busy mỗi khi current thay đổi (entry mới)
  useEffect(() => { setBusy(false) }, [current?.id])

  if (!current) return null

  const handleUndo = async () => {
    if (busy) return
    setBusy(true)
    await undo()
    // Không cần setBusy(false) vì current đã = null sau undo
  }

  return (
    <div
      key={current.id}
      className="fixed bottom-4 left-4 z-50 flex items-stretch gap-0 rounded-lg
                 bg-zinc-900 dark:bg-zinc-800 text-white shadow-2xl
                 ring-1 ring-black/10 dark:ring-white/10
                 overflow-hidden animate-[undo-slide-in_180ms_ease-out]"
      role="status"
      aria-live="polite"
    >
      {/* Label */}
      <div className="flex items-center gap-2 pl-3.5 pr-2 py-2.5 text-[13px] min-w-[140px]">
        <span className="text-zinc-300">{current.label}</span>
      </div>

      {/* Nút Hoàn tác */}
      <button
        onClick={handleUndo}
        disabled={busy}
        className="px-3 py-2.5 text-[13px] font-medium text-blue-400 hover:text-blue-300
                   hover:bg-white/5 disabled:opacity-50 disabled:cursor-not-allowed
                   border-l border-white/10 transition-colors"
      >
        {busy ? 'Đang...' : 'Hoàn tác'}
      </button>

      {/* Nút X */}
      <button
        onClick={dismiss}
        disabled={busy}
        className="px-2 text-zinc-500 hover:text-zinc-300 hover:bg-white/5
                   border-l border-white/10 transition-colors"
        title="Bỏ qua"
        aria-label="Dismiss"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
             strokeWidth="2.5" strokeLinecap="round">
          <path d="M18 6L6 18M6 6l12 12" />
        </svg>
      </button>

      {/* Progress bar countdown — CSS animation trải đều UNDO_TIMEOUT_MS */}
      <div className="absolute bottom-0 left-0 h-[2px] bg-blue-500/70 origin-left"
           style={{
             animation: `undo-progress ${UNDO_TIMEOUT_MS}ms linear forwards`,
             width: '100%',
           }} />

      {/* Inline keyframes (giữ trong component để không phụ thuộc tailwind config) */}
      <style>{`
        @keyframes undo-slide-in {
          from { transform: translateY(8px); opacity: 0 }
          to   { transform: translateY(0);   opacity: 1 }
        }
        @keyframes undo-progress {
          from { transform: scaleX(1) }
          to   { transform: scaleX(0) }
        }
      `}</style>
    </div>
  )
}