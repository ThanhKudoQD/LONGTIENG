import React, { useState, useMemo } from 'react'
import type { Character, Subtitle } from '../types'

interface Props {
  open: boolean
  characters: Character[]
  subtitles: Subtitle[]
  onCancel: () => void
  onConfirm: (fromId: number, toId: number) => void | Promise<void>
}

/**
 * Modal đổi nhân vật A → B (2 bước):
 *   Bước 1: Click chip chọn nhân vật cần đổi (A)
 *   Bước 2: Click chip chọn nhân vật đích (B)
 *   Hiển thị preview "A → B" + số dòng sẽ đổi.
 */
export default function SwapCharacterModal({
  open, characters, subtitles, onCancel, onConfirm,
}: Props) {
  const [fromId, setFromId] = useState<number | null>(null)
  const [toId, setToId]     = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)

  // Đếm số dòng theo character
  const counts = useMemo(() => {
    const m = new Map<number, number>()
    for (const s of subtitles) {
      if (s.character_id) m.set(s.character_id, (m.get(s.character_id) || 0) + 1)
    }
    return m
  }, [subtitles])

  if (!open) return null

  const charFrom = fromId != null ? characters.find(c => c.id === fromId) : null
  const charTo   = toId   != null ? characters.find(c => c.id === toId)   : null
  const affectedCount = fromId != null ? (counts.get(fromId) || 0) : 0
  const canConfirm = fromId != null && toId != null && fromId !== toId && affectedCount > 0

  const reset = () => {
    setFromId(null)
    setToId(null)
    setSubmitting(false)
  }

  const handleCancel = () => {
    reset()
    onCancel()
  }

  const handleConfirm = async () => {
    if (!canConfirm || submitting) return
    setSubmitting(true)
    try {
      await onConfirm(fromId!, toId!)
      reset()
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50" onClick={handleCancel}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-2xl w-full mx-4 max-h-[85vh] overflow-hidden flex flex-col"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="px-5 py-3 border-b border-zinc-200 dark:border-zinc-700 flex items-center justify-between flex-shrink-0">
          <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 flex items-center gap-2">
            🔄 <span>Đổi nhân vật hàng loạt</span>
          </h3>
          <button onClick={handleCancel}
            className="w-7 h-7 rounded hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-500 text-base">
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-auto px-5 py-4 space-y-4">

          {/* Bước 1: Chọn A */}
          <div>
            <div className="text-[12px] font-bold text-zinc-700 dark:text-zinc-300 mb-2 flex items-center gap-1.5">
              <span className="w-5 h-5 rounded-full bg-blue-500 text-white text-[11px] flex items-center justify-center font-bold">1</span>
              <span>Chọn nhân vật cần đổi (A)</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {characters.map(c => {
                const isSel = fromId === c.id
                const cnt = counts.get(c.id) || 0
                return (
                  <button
                    key={c.id}
                    onClick={() => {
                      setFromId(c.id)
                      // Nếu chọn lại A trùng B → reset B
                      if (toId === c.id) setToId(null)
                    }}
                    disabled={cnt === 0}
                    className={`px-2.5 py-1 rounded-full text-[12px] font-medium border transition-all inline-flex items-center gap-1.5
                      ${cnt === 0 ? 'opacity-30 cursor-not-allowed' : 'hover:opacity-90 active:scale-95'}
                      ${isSel ? 'ring-2 ring-blue-500 ring-offset-1 dark:ring-offset-zinc-900' : ''}
                    `}
                    style={{
                      background: isSel ? c.color : c.color + '18',
                      color: isSel ? '#fff' : c.color,
                      borderColor: c.color + '60',
                    }}
                  >
                    <span>{c.name}</span>
                    <span className={`text-[10px] px-1 rounded ${isSel ? 'bg-white/30' : 'bg-black/10 dark:bg-white/10'}`}>
                      {cnt}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Bước 2: Chọn B (chỉ hiện khi đã có A) */}
          <div className={fromId == null ? 'opacity-40 pointer-events-none' : ''}>
            <div className="text-[12px] font-bold text-zinc-700 dark:text-zinc-300 mb-2 flex items-center gap-1.5">
              <span className="w-5 h-5 rounded-full bg-emerald-500 text-white text-[11px] flex items-center justify-center font-bold">2</span>
              <span>Đổi sang nhân vật (B)</span>
              {fromId == null && (
                <span className="text-[11px] text-zinc-400 ml-1">(Chọn A trước)</span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {characters.map(c => {
                const isSameAsA = c.id === fromId
                const isSel = toId === c.id
                return (
                  <button
                    key={c.id}
                    onClick={() => setToId(c.id)}
                    disabled={isSameAsA}
                    className={`px-2.5 py-1 rounded-full text-[12px] font-medium border transition-all inline-flex items-center gap-1
                      ${isSameAsA ? 'opacity-25 cursor-not-allowed' : 'hover:opacity-90 active:scale-95'}
                      ${isSel ? 'ring-2 ring-emerald-500 ring-offset-1 dark:ring-offset-zinc-900' : ''}
                    `}
                    style={{
                      background: isSel ? c.color : c.color + '18',
                      color: isSel ? '#fff' : c.color,
                      borderColor: c.color + '60',
                    }}
                    title={isSameAsA ? 'Trùng với A — không thể chọn' : ''}
                  >
                    {c.name}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Preview */}
          {(charFrom || charTo) && (
            <div className="bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-200 dark:border-zinc-700 rounded-lg p-3">
              <div className="text-[11px] uppercase tracking-wider text-zinc-500 mb-1.5 font-bold">Xem trước</div>
              <div className="flex items-center gap-2 flex-wrap">
                {charFrom ? (
                  <span className="px-2.5 py-1 rounded-full text-[12px] font-medium"
                    style={{ background: charFrom.color, color: '#fff' }}>
                    {charFrom.name}
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-full text-[12px] border border-dashed border-zinc-400 text-zinc-400">...</span>
                )}
                <span className="text-lg text-zinc-400">→</span>
                {charTo ? (
                  <span className="px-2.5 py-1 rounded-full text-[12px] font-medium"
                    style={{ background: charTo.color, color: '#fff' }}>
                    {charTo.name}
                  </span>
                ) : (
                  <span className="px-2.5 py-1 rounded-full text-[12px] border border-dashed border-zinc-400 text-zinc-400">...</span>
                )}
                {affectedCount > 0 && charFrom && (
                  <span className="ml-auto text-[12px] text-zinc-600 dark:text-zinc-400">
                    <strong className="text-amber-600 dark:text-amber-400">{affectedCount}</strong> dòng sẽ được đổi
                  </span>
                )}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-zinc-50 dark:bg-zinc-800/40 border-t border-zinc-200 dark:border-zinc-700 flex items-center justify-end gap-2 flex-shrink-0">
          <button onClick={handleCancel}
            className="px-4 py-1.5 text-[13px] rounded-lg border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 font-medium">
            Hủy
          </button>
          <button
            onClick={handleConfirm}
            disabled={!canConfirm || submitting}
            className="px-4 py-1.5 text-[13px] rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white font-semibold disabled:opacity-40 disabled:cursor-not-allowed shadow-sm"
          >
            {submitting ? 'Đang đổi...' : (
              canConfirm
                ? `✓ Đổi ${affectedCount} dòng`
                : '✓ Đổi'
            )}
          </button>
        </div>
      </div>
    </div>
  )
}
