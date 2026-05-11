import React, { useState, useEffect } from 'react'
import api from '../api'
import useStore from '../store'
import type { Chapter } from '../types'

interface Props {
  projectId: number
  onClose: () => void
  onChaptersChanged?: () => void
}

const STATUS_LABELS = {
  pending:     { text: '○ Chưa làm',  color: 'text-zinc-500',     bg: 'bg-zinc-100 dark:bg-zinc-800' },
  in_progress: { text: '▶ Đang làm', color: 'text-amber-600',    bg: 'bg-amber-50 dark:bg-amber-950/40' },
  done:        { text: '✓ Xong',      color: 'text-emerald-600',  bg: 'bg-emerald-50 dark:bg-emerald-950/40' },
}

export default function ChaptersModal({ projectId, onClose, onChaptersChanged }: Props) {
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [splitSize, setSplitSize] = useState(300)
  const [loading, setLoading] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editingName, setEditingName] = useState('')

  const project = useStore(s => s.project)
  const subtitles = useStore(s => s.subtitles)
  const setProject = useStore(s => s.setProject)
  const setActiveSubId = useStore(s => s.setActiveSubId)

  const totalSubs = subtitles.length

  const loadChapters = async () => {
    const r = await api.get(`/chapters/project/${projectId}`)
    setChapters(r.data)
  }

  useEffect(() => { loadChapters() }, [projectId])

  const handleAutoSplit = async () => {
    if (totalSubs === 0) return alert('Chưa có phụ đề')
    if (chapters.length > 0 && !confirm(`Sẽ xoá ${chapters.length} đoạn cũ và chia lại. Tiếp tục?`)) return
    setLoading(true)
    try {
      const r = await api.post(`/chapters/project/${projectId}/auto-split`, { size: splitSize })
      setChapters(r.data)
      if (project) setProject({ ...project, current_chapter_id: null })
      onChaptersChanged?.()
    } finally { setLoading(false) }
  }

  const handleDeleteAll = async () => {
    if (!chapters.length) return
    if (!confirm(`Xoá tất cả ${chapters.length} đoạn?`)) return
    await api.delete(`/chapters/project/${projectId}/all`)
    setChapters([])
    if (project) setProject({ ...project, current_chapter_id: null })
    onChaptersChanged?.()
  }

  const handleSetStatus = async (chapter: Chapter, status: Chapter['status']) => {
    await api.patch(`/chapters/${chapter.id}`, { status })
    setChapters(chapters.map(c => c.id === chapter.id ? { ...c, status } : c))

    // Nếu mark "done", chuyển active sang chapter kế tiếp pending
    if (status === 'done') {
      const next = chapters.find(c => c.sort_order > chapter.sort_order && c.status !== 'done')
      if (next) {
        await api.post(`/chapters/project/${projectId}/set-current`, { chapter_id: next.id })
        if (project) setProject({ ...project, current_chapter_id: next.id })
        setChapters(prev => prev.map(c => c.id === next.id ? { ...c, status: 'in_progress' } : c))
      }
    } else if (status === 'in_progress') {
      // Set as current
      await api.post(`/chapters/project/${projectId}/set-current`, { chapter_id: chapter.id })
      if (project) setProject({ ...project, current_chapter_id: chapter.id })
    }
    onChaptersChanged?.()
  }

  const handleGoTo = (chapter: Chapter) => {
    const sub = subtitles.find(s => s.index === chapter.start_sub_index)
    if (sub) setActiveSubId(sub.id)
    onClose()
  }

  const handleDelete = async (chapter: Chapter) => {
    if (!confirm(`Xoá "${chapter.name}"?`)) return
    await api.delete(`/chapters/${chapter.id}`)
    setChapters(chapters.filter(c => c.id !== chapter.id))
    onChaptersChanged?.()
  }

  const saveRename = async (id: number) => {
    if (!editingName.trim()) { setEditingId(null); return }
    await api.patch(`/chapters/${id}`, { name: editingName.trim() })
    setChapters(chapters.map(c => c.id === id ? { ...c, name: editingName.trim() } : c))
    setEditingId(null)
    onChaptersChanged?.()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-2xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={e => e.stopPropagation()}>

        <div className="px-5 py-4 border-b border-zinc-200 dark:border-zinc-700 flex items-center justify-between">
          <h3 className="text-base font-bold flex items-center gap-2">
            <span>📑</span> Quản lý đoạn
          </h3>
          <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 text-xl leading-none">×</button>
        </div>

        <div className="px-5 py-3 border-b border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/40">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[12px] text-zinc-600 dark:text-zinc-400">Chia tự động mỗi</span>
            <input type="number" min="10" max="2000" step="50"
              value={splitSize} onChange={e => setSplitSize(Math.max(10, parseInt(e.target.value) || 300))}
              className="w-20 px-2 py-1 text-[12px] rounded border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900 text-center"/>
            <span className="text-[12px] text-zinc-600 dark:text-zinc-400">dòng</span>
            <button onClick={handleAutoSplit} disabled={loading || totalSubs === 0}
              className="px-3 py-1 text-[12px] rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold disabled:opacity-40">
              {loading ? '...' : `Chia ${Math.ceil(totalSubs / splitSize)} đoạn`}
            </button>
            {chapters.length > 0 && (
              <button onClick={handleDeleteAll}
                className="ml-auto px-3 py-1 text-[12px] rounded-lg border border-red-300 text-red-600 hover:bg-red-50">
                Xoá tất cả
              </button>
            )}
          </div>
          <p className="text-[11px] text-zinc-500 mt-1">
            Tổng {totalSubs} dòng • {chapters.length} đoạn hiện tại
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-3">
          {chapters.length === 0 ? (
            <div className="text-center py-12 text-zinc-400">
              <div className="text-4xl mb-2">📑</div>
              <p className="text-[13px]">Chưa có đoạn nào</p>
              <p className="text-[11px] mt-1">Click "Chia" ở trên để tự động chia thành đoạn</p>
            </div>
          ) : (
            <div className="space-y-1.5">
              {chapters.map(c => {
                const isCurrent = project?.current_chapter_id === c.id
                const status = STATUS_LABELS[c.status]
                const subCount = c.end_sub_index - c.start_sub_index + 1
                return (
                  <div key={c.id}
                    className={`flex items-center gap-2 px-3 py-2 rounded-lg border transition-all ${
                      isCurrent ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/40' :
                      `border-zinc-200 dark:border-zinc-700 ${status.bg}`
                    }`}>

                    <span className={`text-[11px] font-semibold ${status.color} w-20 flex-shrink-0`}>
                      {status.text}
                    </span>

                    <div className="flex-1 min-w-0">
                      {editingId === c.id ? (
                        <input value={editingName}
                          onChange={e => setEditingName(e.target.value)}
                          onBlur={() => saveRename(c.id)}
                          onKeyDown={e => { if (e.key === 'Enter') saveRename(c.id); if (e.key === 'Escape') setEditingId(null) }}
                          autoFocus
                          className="w-full px-2 py-0.5 text-[13px] font-semibold border border-blue-400 rounded bg-white dark:bg-zinc-900"/>
                      ) : (
                        <div onClick={() => { setEditingId(c.id); setEditingName(c.name) }}
                          className="cursor-text hover:underline">
                          <span className="text-[13px] font-semibold">{c.name}</span>
                          <span className="text-[11px] text-zinc-500 ml-2">
                            (#{c.start_sub_index}-{c.end_sub_index} • {subCount} dòng)
                          </span>
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-1 flex-shrink-0">
                      {/* Status buttons */}
                      <select value={c.status}
                        onChange={e => handleSetStatus(c, e.target.value as Chapter['status'])}
                        className="text-[11px] px-1 py-0.5 rounded border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-900">
                        <option value="pending">Chưa làm</option>
                        <option value="in_progress">Đang làm</option>
                        <option value="done">Xong</option>
                      </select>
                      <button onClick={() => handleGoTo(c)}
                        title="Đến đoạn này"
                        className="px-2 py-0.5 text-[11px] rounded bg-blue-100 dark:bg-blue-950 text-blue-600 hover:bg-blue-200 font-semibold">
                        Đến
                      </button>
                      <button onClick={() => handleDelete(c)}
                        title="Xoá đoạn"
                        className="px-1.5 py-0.5 text-[11px] rounded text-red-500 hover:bg-red-50">
                        🗑
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-zinc-200 dark:border-zinc-700 flex justify-end">
          <button onClick={onClose}
            className="px-4 py-1.5 text-[13px] rounded-lg bg-zinc-200 dark:bg-zinc-700 hover:bg-zinc-300 dark:hover:bg-zinc-600 font-semibold">
            Đóng
          </button>
        </div>
      </div>
    </div>
  )
}
