import React, { useState, useEffect } from 'react'
import api from '../api'
import useStore from '../store'

interface Props {
  projectId: number
  onClose: () => void
}

interface ChapterStat {
  chapter_id: number
  name: string
  status: 'pending' | 'in_progress' | 'done'
  collapsed: number
  start_sub_index: number
  end_sub_index: number
  total: number
  assigned: number
  tts_done: number
  overlap_count: number
}

const STATUS_INFO = {
  pending:     { icon: '○', text: 'Chưa làm',  color: '#9CA3AF', bg: 'bg-zinc-100 dark:bg-zinc-800' },
  in_progress: { icon: '▶', text: 'Đang làm', color: '#F59E0B', bg: 'bg-amber-50 dark:bg-amber-950/40' },
  done:        { icon: '✓', text: 'Xong',      color: '#10B981', bg: 'bg-emerald-50 dark:bg-emerald-950/40' },
}

export default function ChapterStatsModal({ projectId, onClose }: Props) {
  const [stats, setStats] = useState<ChapterStat[]>([])
  const [loading, setLoading] = useState(true)
  const [marking, setMarking] = useState<number | null>(null)

  const subtitles = useStore(s => s.subtitles)
  const setActiveSubId = useStore(s => s.setActiveSubId)
  const project = useStore(s => s.project)
  const setProject = useStore(s => s.setProject)

  const reload = async () => {
    setLoading(true)
    try {
      const r = await api.get(`/chapters/project/${projectId}/stats`)
      setStats(r.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { reload() }, [projectId])

  const handleJump = (stat: ChapterStat) => {
    const sub = subtitles.find(s => s.index === stat.start_sub_index)
    if (sub) setActiveSubId(sub.id)
    // Trigger expand chapter trong list
    window.dispatchEvent(new CustomEvent('chapter_jump', { detail: { chapter_id: stat.chapter_id } }))
    onClose()
  }

  const handleMarkDone = async (stat: ChapterStat) => {
    let warning = ''
    if (stat.assigned < stat.total) warning += `\n• Còn ${stat.total - stat.assigned} dòng chưa gán nhân vật`
    if (stat.tts_done < stat.total) warning += `\n• Còn ${stat.total - stat.tts_done} dòng chưa có TTS`
    if (stat.overlap_count > 0) warning += `\n• Còn ${stat.overlap_count} audio đè nhau`

    if (warning) {
      if (!confirm(`Đoạn "${stat.name}" còn vấn đề:${warning}\n\nVẫn đánh dấu Xong?`)) return
    }

    setMarking(stat.chapter_id)
    try {
      await api.patch(`/chapters/${stat.chapter_id}`, { status: 'done' })
      // Tự move current_chapter_id sang chapter pending kế tiếp
      const next = stats.find(s => s.chapter_id !== stat.chapter_id &&
        s.status !== 'done' &&
        stats.findIndex(x => x.chapter_id === s.chapter_id) > stats.findIndex(x => x.chapter_id === stat.chapter_id))
      if (next) {
        await api.post(`/chapters/project/${projectId}/set-current`, { chapter_id: next.chapter_id })
        if (next.status === 'pending') {
          await api.patch(`/chapters/${next.chapter_id}`, { status: 'in_progress' })
        }
        if (project) setProject({ ...project, current_chapter_id: next.chapter_id })
      } else {
        // Không còn đoạn pending — clear current
        await api.post(`/chapters/project/${projectId}/set-current`, { chapter_id: null })
        if (project) setProject({ ...project, current_chapter_id: null })
      }
      window.dispatchEvent(new Event('chapters_changed'))
      await reload()
    } finally {
      setMarking(null)
    }
  }

  const handleSetInProgress = async (stat: ChapterStat) => {
    setMarking(stat.chapter_id)
    try {
      await api.patch(`/chapters/${stat.chapter_id}`, { status: 'in_progress' })
      await api.post(`/chapters/project/${projectId}/set-current`, { chapter_id: stat.chapter_id })
      if (project) setProject({ ...project, current_chapter_id: stat.chapter_id })
      window.dispatchEvent(new Event('chapters_changed'))
      await reload()
    } finally {
      setMarking(null)
    }
  }

  const StatPill = ({ label, current, total, color }: { label: string, current: number, total: number, color: string }) => {
    const pct = total > 0 ? Math.round((current / total) * 100) : 0
    return (
      <div className="flex flex-col items-start gap-0.5 min-w-[100px]">
        <div className="text-[10px] text-zinc-500 dark:text-zinc-400">{label}</div>
        <div className="flex items-baseline gap-1">
          <span className="font-bold tabular-nums text-[14px]" style={{ color }}>{current}</span>
          <span className="text-[10px] text-zinc-400 tabular-nums">/{total}</span>
          <span className="text-[10px] text-zinc-400 ml-1">({pct}%)</span>
        </div>
        <div className="w-full h-1 rounded-full bg-zinc-200 dark:bg-zinc-700 overflow-hidden">
          <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }}/>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-3xl w-full mx-4 max-h-[90vh] overflow-hidden flex flex-col"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-200 dark:border-zinc-700 flex items-center justify-between">
          <h3 className="text-base font-bold flex items-center gap-2">
            <span>📑</span> Thống kê các đoạn
          </h3>
          <div className="flex items-center gap-2">
            <button onClick={reload} disabled={loading}
              title="Làm mới"
              className="w-8 h-8 rounded border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 disabled:opacity-50 text-[14px] flex items-center justify-center">
              {loading ? '⏳' : '🔄'}
            </button>
            <button onClick={onClose} className="text-zinc-400 hover:text-zinc-600 text-xl leading-none">×</button>
          </div>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4">
          {loading ? (
            <div className="text-center py-12 text-zinc-400 text-[13px]">Đang tải thống kê...</div>
          ) : stats.length === 0 ? (
            <div className="text-center py-12 text-zinc-400">
              <div className="text-4xl mb-2">📑</div>
              <p className="text-[13px]">Chưa có đoạn nào</p>
            </div>
          ) : (
            <div className="space-y-2">
              {stats.map(stat => {
                const info = STATUS_INFO[stat.status]
                const isCurrent = project?.current_chapter_id === stat.chapter_id
                const isReady = stat.assigned === stat.total && stat.tts_done === stat.total && stat.overlap_count === 0
                return (
                  <div key={stat.chapter_id}
                    className={`rounded-lg border-2 transition-all ${
                      isCurrent ? 'border-blue-400 bg-blue-50/40 dark:bg-blue-950/20' :
                      `border-transparent ${info.bg}`
                    }`}>
                    {/* Top row: name + status + actions */}
                    <div className="flex items-center gap-2 px-4 py-2.5">
                      <span className="text-[18px] leading-none" style={{ color: info.color }}>{info.icon}</span>
                      <span className="text-[14px] font-bold">{stat.name}</span>
                      <span className="text-[11px] text-zinc-500 dark:text-zinc-400 font-mono">
                        ({stat.start_sub_index}-{stat.end_sub_index})
                      </span>
                      {isCurrent && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500 text-white font-bold">ĐANG</span>
                      )}
                      {isReady && stat.status !== 'done' && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-500 text-white font-bold">SẴN SÀNG</span>
                      )}
                      <div className="ml-auto flex items-center gap-1">
                        <button onClick={() => handleJump(stat)}
                          className="px-2.5 py-1 text-[11px] rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold">
                          → Đến đoạn
                        </button>
                        {stat.status !== 'done' && (
                          <>
                            {stat.status === 'pending' && (
                              <button onClick={() => handleSetInProgress(stat)}
                                disabled={marking === stat.chapter_id}
                                className="px-2.5 py-1 text-[11px] rounded-lg border border-amber-400 text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-950/30 font-semibold disabled:opacity-40">
                                ▶ Bắt đầu
                              </button>
                            )}
                            <button onClick={() => handleMarkDone(stat)}
                              disabled={marking === stat.chapter_id}
                              className="px-2.5 py-1 text-[11px] rounded-lg border border-emerald-400 text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950/30 font-semibold disabled:opacity-40">
                              ✓ Xong
                            </button>
                          </>
                        )}
                        {stat.status === 'done' && (
                          <button onClick={async () => {
                            setMarking(stat.chapter_id)
                            try {
                              await api.patch(`/chapters/${stat.chapter_id}`, { status: 'in_progress' })
                              window.dispatchEvent(new Event('chapters_changed'))
                              await reload()
                            } finally { setMarking(null) }
                          }}
                            disabled={marking === stat.chapter_id}
                            className="px-2.5 py-1 text-[11px] rounded-lg border border-zinc-300 text-zinc-500 hover:bg-zinc-100 disabled:opacity-40">
                            Mở lại
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Stats grid */}
                    <div className="px-4 pb-3 flex items-center gap-4 flex-wrap">
                      <StatPill label="Tổng" current={stat.total} total={stat.total} color="#6B7280"/>
                      <StatPill label="Đã gán nhân vật" current={stat.assigned} total={stat.total} color="#3B82F6"/>
                      <StatPill label="Đã có TTS" current={stat.tts_done} total={stat.total} color="#10B981"/>
                      <div className="flex flex-col items-start gap-0.5 min-w-[80px]">
                        <div className="text-[10px] text-zinc-500 dark:text-zinc-400">Audio đè</div>
                        <div className="flex items-baseline gap-1">
                          <span className={`font-bold tabular-nums text-[14px] ${stat.overlap_count > 0 ? 'text-red-500' : 'text-emerald-500'}`}>
                            {stat.overlap_count}
                          </span>
                          {stat.overlap_count === 0 && stat.tts_done > 0 && (
                            <span className="text-[10px] text-emerald-500">✓</span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* Footer */}
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
