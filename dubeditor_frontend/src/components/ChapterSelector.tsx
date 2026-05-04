import React, { useState, useEffect } from 'react'
import api from '../api'
import useStore from '../store'
import type { Chapter } from '../types'
import ChapterStatsModal from './ChapterStatsModal'

interface Props {
  projectId: number
  onOpenManage: () => void
}

/**
 * Nút header: "📑 Đoạn" — click mở modal stats (mới).
 * Nút riêng "⚙ Quản lý" mở ChaptersModal cũ (CRUD đầy đủ).
 */
export default function ChapterSelector({ projectId, onOpenManage }: Props) {
  const [chapters, setChapters] = useState<Chapter[]>([])
  const [showStats, setShowStats] = useState(false)

  const reload = async () => {
    try {
      const r = await api.get(`/chapters/project/${projectId}`)
      setChapters(r.data)
    } catch {}
  }

  useEffect(() => { reload() }, [projectId])

  useEffect(() => {
    const onChange = () => reload()
    window.addEventListener('chapters_changed', onChange)
    return () => window.removeEventListener('chapters_changed', onChange)
  }, [])

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
    <>
      <div className="flex items-center gap-1 flex-shrink-0">
        <button onClick={() => setShowStats(true)}
          title="Xem thống kê các đoạn"
          className="px-2.5 py-1.5 text-[12px] rounded-lg border border-blue-300 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400 hover:bg-blue-100 font-semibold flex items-center gap-1.5">
          📑 <span>Đoạn ({chapters.length})</span>
        </button>
        <button onClick={onOpenManage}
          title="Quản lý đoạn"
          className="w-7 h-7 rounded border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-[12px] flex items-center justify-center">⚙</button>
      </div>

      {showStats && (
        <ChapterStatsModal
          projectId={projectId}
          onClose={() => setShowStats(false)}
        />
      )}
    </>
  )
}
