import React, { useState, useEffect } from 'react'
import api from '../api'
import useStore from '../store'
import type { Chapter } from '../types'

interface Props {
  projectId: number
  onOpenManage: () => void
}

/**
 * Header dropdown nhỏ gọn để chọn chapter hiện tại + jump.
 */
export default function ChapterSelector({ projectId, onOpenManage }: Props) {
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [open, setOpen] = useState(false)

  const project = useStore(s => s.project)
  const setProject = useStore(s => s.setProject)
  const subtitles = useStore(s => s.subtitles)
  const setActiveSubId = useStore(s => s.setActiveSubId)

  const reload = async () => {
    try {
      const r = await api.get(`/chapters/project/${projectId}`)
      setChapters(r.data)
    } catch {}
  }

  useEffect(() => { reload() }, [projectId])

  // Listen event chapters changed (từ ChaptersModal)
  useEffect(() => {
    const onChange = () => reload()
    window.addEventListener('chapters_changed', onChange)
    return () => window.removeEventListener('chapters_changed', onChange)
  }, [])

  const currentChapter = chapters.find(c => c.id === project?.current_chapter_id)
  const currentIdx = currentChapter ? chapters.indexOf(currentChapter) : -1

  const jumpTo = async (chapter: Chapter) => {
    await api.post(`/chapters/project/${projectId}/set-current`, { chapter_id: chapter.id })
    if (project) setProject({ ...project, current_chapter_id: chapter.id })
    // Mark as in_progress nếu đang pending
    if (chapter.status === 'pending') {
      await api.patch(`/chapters/${chapter.id}`, { status: 'in_progress' })
      setChapters(chapters.map(c => c.id === chapter.id ? { ...c, status: 'in_progress' } : c))
    }
    const sub = subtitles.find(s => s.index === chapter.start_sub_index)
    if (sub) setActiveSubId(sub.id)
    setOpen(false)
  }

  const goPrev = () => {
    if (currentIdx > 0) jumpTo(chapters[currentIdx - 1])
  }
  const goNext = () => {
    if (currentIdx >= 0 && currentIdx < chapters.length - 1) jumpTo(chapters[currentIdx + 1])
  }

  if (chapters.length === 0) {
    return (
      <button onClick={onOpenManage}
        title="Chia đoạn để dễ quản lý"
        className="px-2.5 py-1.5 text-[12px] rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 font-medium text-zinc-500 dark:text-zinc-400 flex-shrink-0">
        📑 Chia đoạn
      </button>
    )
  }

  return (
    <div className="flex items-center gap-1 flex-shrink-0">
      <button onClick={goPrev} disabled={currentIdx <= 0}
        title="Đoạn trước" aria-label="Đoạn trước"
        className="w-7 h-7 rounded border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-30 text-[13px] leading-none flex items-center justify-center">‹</button>

      <div className="relative">
        <button onClick={() => setOpen(v => !v)}
          className="px-2.5 py-1.5 text-[12px] rounded-lg border border-blue-300 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400 hover:bg-blue-100 font-semibold flex items-center gap-1 min-w-[110px] justify-between">
          <span className="truncate">{currentChapter ? currentChapter.name : `📑 ${chapters.length} đoạn`}</span>
          <span className="text-[10px]">▼</span>
        </button>
        {open && (
          <>
            <div className="fixed inset-0 z-30" onClick={() => setOpen(false)}/>
            <div className="absolute top-full mt-1 left-0 z-40 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-700 rounded-lg shadow-xl min-w-[260px] max-h-72 overflow-y-auto">
              {chapters.map(c => {
                const isCurrent = c.id === currentChapter?.id
                const subCount = c.end_sub_index - c.start_sub_index + 1
                const statusIcon = c.status === 'done' ? '✓' : c.status === 'in_progress' ? '▶' : '○'
                const statusColor = c.status === 'done' ? 'text-emerald-500' : c.status === 'in_progress' ? 'text-amber-500' : 'text-zinc-400'
                return (
                  <button key={c.id} onClick={() => jumpTo(c)}
                    className={`w-full px-3 py-1.5 text-left text-[12px] flex items-center gap-2 hover:bg-zinc-50 dark:hover:bg-zinc-800 ${isCurrent ? 'bg-blue-50 dark:bg-blue-950/40 font-semibold' : ''}`}>
                    <span className={statusColor}>{statusIcon}</span>
                    <span className="flex-1 truncate">{c.name}</span>
                    <span className="text-[10px] text-zinc-400 tabular-nums">{subCount}</span>
                  </button>
                )
              })}
            </div>
          </>
        )}
      </div>

      <button onClick={goNext} disabled={currentIdx < 0 || currentIdx >= chapters.length - 1}
        title="Đoạn sau" aria-label="Đoạn sau"
        className="w-7 h-7 rounded border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-30 text-[13px] leading-none flex items-center justify-center">›</button>

      <button onClick={onOpenManage}
        title="Quản lý đoạn"
        className="w-7 h-7 rounded border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-[12px] flex items-center justify-center">⚙</button>
    </div>
  )
}
