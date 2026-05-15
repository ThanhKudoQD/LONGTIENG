import React, { useState, useEffect, useRef } from 'react'
import api from '../api'
import type { Chapter } from '../types'
import ConfirmModal from './ConfirmModal'
import InfoDialog from './InfoDialog'

interface Props {
  projectId: number
  chapters: Chapter[]
  selectedIds: number[]
  onChange: (ids: number[]) => void
}

/**
 * Dropdown multi-select để filter Editor theo Chapter (Arc).
 * Dùng position: fixed để thoát khỏi overflow-x-auto của header parent.
 */
export default function ChapterFilterDropdown({ projectId, chapters, selectedIds, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const [syncing, setSyncing] = useState(false)
  const [showSyncConfirm, setShowSyncConfirm] = useState(false)
  const [info, setInfo] = useState<{ message: string; variant: 'success' | 'error' | 'info' | 'warning' } | null>(null)
  const [coords, setCoords] = useState<{ top: number; left: number } | null>(null)

  const buttonRef = useRef<HTMLButtonElement>(null)
  const dropdownRef = useRef<HTMLDivElement>(null)

  // Tính vị trí dropdown khi mở
  useEffect(() => {
    if (!open || !buttonRef.current) return
    const rect = buttonRef.current.getBoundingClientRect()
    setCoords({ top: rect.bottom + 4, left: rect.left })
  }, [open])

  // Click ngoài đóng + reposition khi resize/scroll
  useEffect(() => {
    if (!open) return
    const onClickOut = (e: MouseEvent) => {
      const target = e.target as Node
      if (
        buttonRef.current && !buttonRef.current.contains(target) &&
        dropdownRef.current && !dropdownRef.current.contains(target)
      ) {
        setOpen(false)
      }
    }
    const onReposition = () => {
      if (!buttonRef.current) return
      const rect = buttonRef.current.getBoundingClientRect()
      setCoords({ top: rect.bottom + 4, left: rect.left })
    }
    document.addEventListener('mousedown', onClickOut)
    window.addEventListener('resize', onReposition)
    window.addEventListener('scroll', onReposition, true)
    return () => {
      document.removeEventListener('mousedown', onClickOut)
      window.removeEventListener('resize', onReposition)
      window.removeEventListener('scroll', onReposition, true)
    }
  }, [open])

  const allSelected = selectedIds.length === 0
  const someSelected = selectedIds.length > 0 && selectedIds.length < chapters.length

  const toggleAll = () => {
    if (allSelected) return
    onChange([])
  }

  const toggleOne = (id: number) => {
    if (selectedIds.includes(id)) {
      onChange(selectedIds.filter(x => x !== id))
    } else {
      onChange([...selectedIds, id])
    }
  }

  const requestSync = () => {
    setShowSyncConfirm(true)
  }

  const handleSync = async () => {
    setShowSyncConfirm(false)
    if (syncing) return
    setSyncing(true)
    try {
      const r = await api.post(`/chapters/project/${projectId}/sync-from-arcs`)
      setInfo({
        message: r.data.message || `Đã sync ${r.data.created} chapters từ Story Arc`,
        variant: 'success',
      })
      window.dispatchEvent(new Event('chapters_changed'))
    } catch (e: any) {
      setInfo({
        message: `Sync thất bại: ${e?.response?.data?.detail || e.message}`,
        variant: 'error',
      })
    } finally {
      setSyncing(false)
    }
  }

  // Khi chưa có chapter — chỉ hiện nút sync
  if (chapters.length === 0) {
    return (
      <>
        <button
          onClick={requestSync}
          disabled={syncing}
          title="Sync chapters từ StoryArc (cần đã chạy Stage 1)"
          className="px-2.5 py-1.5 text-[12px] rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 flex-shrink-0"
        >
          {syncing ? '⏳ Đang sync...' : '🔄 Sync từ Arc'}
        </button>

        <ConfirmModal
          open={showSyncConfirm}
          title="Sync Chapter từ Story Arc"
          message="Hệ thống sẽ xóa Chapter loại 'auto_from_arc' và tạo lại từ Story Arc hiện tại. Chapter do user tạo tay được giữ nguyên."
          variant="warning"
          confirmText="Đồng bộ"
          cancelText="Hủy"
          onConfirm={handleSync}
          onCancel={() => setShowSyncConfirm(false)}
        />

        <InfoDialog
          open={!!info}
          message={info?.message || ''}
          variant={info?.variant || 'info'}
          onClose={() => setInfo(null)}
        />
      </>
    )
  }

  // Label hiển thị
  const label = allSelected
    ? `Tất cả (${chapters.length})`
    : selectedIds.length === 1
      ? chapters.find(c => c.id === selectedIds[0])?.name || '?'
      : `${selectedIds.length} đoạn`

  return (
    <>
      <button
        ref={buttonRef}
        onClick={() => setOpen(o => !o)}
        title="Lọc theo đoạn"
        className={`flex-shrink-0 px-2.5 py-1.5 text-[12px] rounded-lg border flex items-center gap-1.5 font-medium
          ${someSelected
            ? 'border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400'
            : 'border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-zinc-700 dark:text-zinc-300'
          }
        `}
      >
        <span>📑 Lọc đoạn:</span>
        <span className="font-semibold truncate max-w-[180px]">{label}</span>
        <span className="text-[10px]">▼</span>
      </button>

      {open && coords && (
        <div
          ref={dropdownRef}
          style={{ position: 'fixed', top: coords.top, left: coords.left, zIndex: 1000 }}
          className="w-80 max-h-[440px] overflow-auto rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-2xl py-1"
        >
          {/* Header — Tất cả + Sync */}
          <div className="sticky top-0 bg-white dark:bg-zinc-900 border-b border-zinc-100 dark:border-zinc-800 px-2 py-1.5 flex items-center justify-between gap-2">
            <label className="flex items-center gap-2 text-[12px] cursor-pointer flex-1">
              <input
                type="checkbox"
                checked={allSelected}
                onChange={toggleAll}
                className="w-4 h-4 cursor-pointer"
              />
              <span className="font-semibold">Tất cả ({chapters.length} đoạn)</span>
            </label>
            <button
              onClick={requestSync}
              disabled={syncing}
              title="Sync chapters từ Arc"
              className="text-[11px] px-2 py-0.5 rounded border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            >
              {syncing ? '⏳' : '🔄 Sync'}
            </button>
          </div>

          {/* List chapters */}
          <div className="py-1">
            {chapters.map(c => {
              const isSelected = selectedIds.includes(c.id)
              const isAuto = c.source === 'auto_from_arc'
              return (
                <label
                  key={c.id}
                  className="flex items-center gap-2 px-3 py-1.5 hover:bg-zinc-50 dark:hover:bg-zinc-800 cursor-pointer text-[12px]"
                >
                  <input
                    type="checkbox"
                    checked={isSelected}
                    onChange={() => toggleOne(c.id)}
                    className="w-4 h-4 cursor-pointer"
                  />
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      {isAuto && (
                        <span title="Auto từ Story Arc" className="text-[10px] px-1 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-400">
                          ARC
                        </span>
                      )}
                      <span className="font-medium truncate">{c.name}</span>
                    </div>
                    <div className="text-[10px] text-zinc-500 dark:text-zinc-400">
                      dòng {c.start_sub_index}-{c.end_sub_index}
                    </div>
                  </div>
                </label>
              )
            })}
          </div>
        </div>
      )}

      {/* Dialog xác nhận sync */}
      <ConfirmModal
        open={showSyncConfirm}
        title="Sync Chapter từ Story Arc"
        message="Hệ thống sẽ xóa Chapter loại 'auto_from_arc' và tạo lại từ Story Arc hiện tại. Chapter do user tạo tay được giữ nguyên."
        variant="warning"
        confirmText="Đồng bộ"
        cancelText="Hủy"
        onConfirm={handleSync}
        onCancel={() => setShowSyncConfirm(false)}
      />

      {/* Dialog thông báo kết quả */}
      <InfoDialog
        open={!!info}
        message={info?.message || ''}
        variant={info?.variant || 'info'}
        onClose={() => setInfo(null)}
      />
    </>
  )
}
