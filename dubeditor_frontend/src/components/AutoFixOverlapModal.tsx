import React, { useState, useEffect } from 'react'
import api from '../api'
import useStore from '../store'

interface Props {
  projectId: number
  onClose: () => void
  /**
   * v3.4: nếu có filter đoạn/NV đang bật ở Editor, parent truyền danh sách
   * subtitle ids visible xuống. Auto-fix sẽ CHỈ scan + fix các sub này.
   * undefined → fix toàn phim như behavior cũ.
   */
  subtitleIdsFilter?: number[]
}

interface FixChange {
  sub_id: number
  sub_index: number
  old_offset: number
  new_offset: number
  shift: number
}

interface PreviewData {
  summary: {
    total_chains: number
    total_audio_in_chains: number
    subs_affected: number
    max_shift: number
    avg_shift: number
    max_shift_sub?: { index: number, shift: number }
  }
  changes: FixChange[]
}

export default function AutoFixOverlapModal({ projectId, onClose, subtitleIdsFilter }: Props) {
  const [overlapThreshold, setOverlapThreshold] = useState(0.5)
  const [thresholdAnchor, setThresholdAnchor]   = useState(4.0)
  const [preview, setPreview]                   = useState<PreviewData | null>(null)
  const [loading, setLoading]                   = useState(false)
  const [applying, setApplying]                 = useState(false)
  const [applied, setApplied]                   = useState<{ count: number, snapshotId: number } | null>(null)

  const updateSubtitle = useStore(s => s.updateSubtitle)

  // v3.4: helper build payload — kèm subtitle_ids nếu có filter
  const buildPayload = (dryRun: boolean) => {
    const base: any = {
      overlap_threshold: overlapThreshold,
      threshold_anchor:  thresholdAnchor,
      dry_run:           dryRun,
    }
    if (subtitleIdsFilter && subtitleIdsFilter.length > 0) {
      base.subtitle_ids = subtitleIdsFilter
    }
    return base
  }

  const isScoped = !!(subtitleIdsFilter && subtitleIdsFilter.length > 0)

  // Tự load preview khi mở hoặc đổi config
  useEffect(() => {
    if (applied) return
    let cancelled = false
    setLoading(true)
    api.post(`/projects/${projectId}/auto-fix-overlap`, buildPayload(true)).then(r => {
      if (!cancelled) setPreview(r.data)
    }).catch(() => {
      if (!cancelled) setPreview(null)
    }).finally(() => {
      if (!cancelled) setLoading(false)
    })
    return () => { cancelled = true }
  }, [overlapThreshold, thresholdAnchor, projectId, applied, subtitleIdsFilter])

  const handleApply = async () => {
    if (!preview || preview.changes.length === 0) return
    setApplying(true)
    try {
      const r = await api.post(`/projects/${projectId}/auto-fix-overlap`, buildPayload(false))
      // Update local store ngay
      r.data.changes.forEach((c: FixChange) => {
        updateSubtitle(c.sub_id, { audio_offset: c.new_offset })
      })
      setApplied({ count: r.data.changes.length, snapshotId: r.data.snapshot_id })
    } catch (e) {
      alert('Lỗi: ' + (e as any).message)
    } finally {
      setApplying(false)
    }
  }

  const handleUndo = async () => {
    if (!applied) return
    setApplying(true)
    try {
      await api.post(`/projects/${projectId}/undo-auto-fix`)
      // Reload subtitles
      const r = await api.get(`/subtitles/project/${projectId}`)
      useStore.setState({ subtitles: r.data })
      setApplied(null)
    } finally {
      setApplying(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-lg w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-200 dark:border-zinc-700 flex items-center justify-between">
          <h3 className="text-base font-bold flex items-center gap-2">
            <span>⚡</span> Tự động fix audio chồng lấn
            {isScoped && (
              <span className="text-[11px] font-medium px-2 py-0.5 rounded-full bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 border border-blue-200 dark:border-blue-800">
                đoạn đang lọc · {subtitleIdsFilter!.length} dòng
              </span>
            )}
          </h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 text-xl leading-none">×</button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 overflow-y-auto flex-1">

          {!applied ? (
            <>
              {/* Config */}
              <div className="space-y-3 mb-4">
                <div>
                  <label className="text-[12px] font-medium text-zinc-700 dark:text-zinc-300 flex items-center justify-between">
                    <span>Ngưỡng đè:</span>
                    <span className="text-blue-600 font-bold tabular-nums">{overlapThreshold.toFixed(2)}s</span>
                  </label>
                  <input type="range" min="0" max="2" step="0.05"
                    value={overlapThreshold}
                    onChange={e => setOverlapThreshold(parseFloat(e.target.value))}
                    className="w-full mt-1"/>
                  <p className="text-[11px] text-zinc-500 mt-1">
                    Audio chồng nhau dưới ngưỡng này sẽ bỏ qua
                  </p>
                </div>

                <div>
                  <label className="text-[12px] font-medium text-zinc-700 dark:text-zinc-300 flex items-center justify-between">
                    <span>Khoảng cách an toàn:</span>
                    <span className="text-blue-600 font-bold tabular-nums">{thresholdAnchor.toFixed(1)}s</span>
                  </label>
                  <input type="range" min="0.5" max="10" step="0.5"
                    value={thresholdAnchor}
                    onChange={e => setThresholdAnchor(parseFloat(e.target.value))}
                    className="w-full mt-1"/>
                  <p className="text-[11px] text-zinc-500 mt-1">
                    Khe ≥ ngưỡng này coi là an toàn, dừng cascade
                  </p>
                </div>
              </div>

              {/* Preview */}
              <div className="bg-zinc-50 dark:bg-zinc-800/40 rounded-lg p-3">
                <div className="text-[12px] font-semibold text-zinc-700 dark:text-zinc-300 mb-2">📊 Xem trước</div>
                {loading ? (
                  <div className="text-[12px] text-zinc-400 py-2">Đang tính toán...</div>
                ) : !preview ? (
                  <div className="text-[12px] text-red-500">Không tải được preview</div>
                ) : preview.changes.length === 0 ? (
                  <div className="text-[12px] text-emerald-600 py-2">
                    ✓ Không có audio nào cần fix với cấu hình hiện tại
                  </div>
                ) : (
                  <div className="space-y-1 text-[12px]">
                    <div className="flex justify-between">
                      <span className="text-zinc-500">Số chuỗi đè:</span>
                      <span className="font-semibold">{preview.summary.total_chains}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-zinc-500">Sub bị dịch:</span>
                      <span className="font-semibold text-blue-600">{preview.summary.subs_affected}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-zinc-500">Dịch trung bình:</span>
                      <span className="font-semibold tabular-nums">{preview.summary.avg_shift.toFixed(2)}s</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-zinc-500">Dịch nhiều nhất:</span>
                      <span className="font-semibold tabular-nums text-amber-600">
                        {preview.summary.max_shift.toFixed(2)}s
                        {preview.summary.max_shift_sub && (
                          <span className="text-[10px] text-zinc-400 ml-1">
                            (#{preview.summary.max_shift_sub.index})
                          </span>
                        )}
                      </span>
                    </div>
                  </div>
                )}
              </div>

              {/* Chi tiết changes (collapsible) */}
              {preview && preview.changes.length > 0 && (
                <details className="mt-3">
                  <summary className="text-[11px] text-zinc-500 cursor-pointer hover:text-zinc-700">
                    Xem chi tiết {preview.changes.length} thay đổi
                  </summary>
                  <div className="mt-2 max-h-48 overflow-y-auto bg-zinc-50 dark:bg-zinc-800/40 rounded p-2 text-[11px] font-mono">
                    {preview.changes.slice(0, 100).map(c => (
                      <div key={c.sub_id} className="flex justify-between py-0.5">
                        <span>#{c.sub_index}</span>
                        <span className="text-zinc-500">
                          {c.old_offset.toFixed(2)} → <span className="text-blue-600 font-bold">{c.new_offset.toFixed(2)}</span>
                          <span className="text-amber-600 ml-2">({c.shift > 0 ? '+' : ''}{c.shift.toFixed(2)}s)</span>
                        </span>
                      </div>
                    ))}
                    {preview.changes.length > 100 && (
                      <div className="text-center text-zinc-400 py-1">... và {preview.changes.length - 100} thay đổi khác</div>
                    )}
                  </div>
                </details>
              )}
            </>
          ) : (
            <div className="py-8 text-center">
              <div className="text-4xl mb-2">✅</div>
              <div className="text-base font-semibold text-emerald-600 mb-1">
                Đã fix {applied.count} audio
              </div>
              <p className="text-[12px] text-zinc-500">
                Bạn có thể hoàn tác hành động này.
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-5 py-3 border-t border-zinc-200 dark:border-zinc-700 flex items-center justify-end gap-2">
          {!applied ? (
            <>
              <button onClick={onClose}
                className="px-4 py-1.5 text-[13px] rounded-lg border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800">
                Hủy
              </button>
              <button onClick={handleApply}
                disabled={applying || loading || !preview || preview.changes.length === 0}
                className="px-4 py-1.5 text-[13px] rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold disabled:opacity-40 disabled:cursor-not-allowed">
                {applying ? 'Đang áp dụng...' : '✓ Áp dụng'}
              </button>
            </>
          ) : (
            <>
              <button onClick={handleUndo} disabled={applying}
                className="px-4 py-1.5 text-[13px] rounded-lg border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-40">
                {applying ? 'Đang hoàn tác...' : '↶ Hoàn tác'}
              </button>
              <button onClick={onClose}
                className="px-4 py-1.5 text-[13px] rounded-lg bg-emerald-600 hover:bg-emerald-700 text-white font-semibold">
                Đóng
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
