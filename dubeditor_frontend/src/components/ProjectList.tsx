import React, { useEffect, useState } from 'react'
import api from '../api'
import { Project } from '../types'

interface Props { onOpen: (id: number) => void }

export default function ProjectList({ onOpen }: Props) {
  const [projects, setProjects] = useState<Project[]>([])
  const [name, setName] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async () => {
    const res = await api.get('/projects/'); setProjects(res.data); setLoading(false)
  }
  useEffect(() => { load() }, [])

  const create = async () => {
    if (!name.trim()) return
    const res = await api.post('/projects/', { name }); setName(''); onOpen(res.data.id)
  }
  const del = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Xoá dự án này?')) return
    await api.delete(`/projects/${id}`); load()
  }

  return (
    <div className="min-h-screen bg-zinc-50 dark:bg-zinc-950">
      <div className="max-w-2xl mx-auto px-6 py-12">
        <div className="mb-8">
          <h1 className="text-2xl font-semibold mb-1">DubEditor</h1>
          <p className="text-sm text-zinc-400">Lồng tiếng và chỉnh sửa phụ đề</p>
        </div>

        {/* Create new */}
        <div className="flex gap-2 mb-8">
          <input placeholder="Tên dự án mới..." value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && create()}
            className="input flex-1 text-sm" />
          <button onClick={create} className="btn-primary px-5">Tạo mới</button>
        </div>

        {/* Project list */}
        {loading ? (
          <div className="text-sm text-zinc-400 text-center py-8">Đang tải...</div>
        ) : projects.length === 0 ? (
          <div className="text-center py-16 text-zinc-400">
            <div className="text-4xl mb-3">🎬</div>
            <p className="text-sm">Chưa có dự án nào. Tạo dự án đầu tiên!</p>
          </div>
        ) : (
          <div className="space-y-2">
            {projects.map(p => (
              <div key={p.id} onClick={() => onOpen(p.id)}
                className="flex items-center gap-4 p-4 bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 cursor-pointer hover:border-accent hover:shadow-sm transition-all">
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm">{p.name}</div>
                  <div className="text-xs text-zinc-400 mt-0.5 flex gap-2">
                    <span>{p.subtitle_count} dòng</span>
                    <span>·</span>
                    <span className={p.tts_done_count === p.subtitle_count && p.subtitle_count > 0 ? 'text-emerald-500' : ''}>
                      {p.tts_done_count}/{p.subtitle_count} TTS
                    </span>
                    {p.video_name && <><span>·</span><span className="truncate">{p.video_name}</span></>}
                    {p.has_bible && (
                      <><span>·</span>
                      <span style={{ color: '#7c3aed', fontWeight: 700 }}>
                        {p.source_lang === 'zh' ? '🌐 Đã dịch' : '📋 Có Bible'}
                      </span></>
                    )}
                  </div>
                </div>
                <div className="flex gap-2 flex-shrink-0">
                  <button onClick={e => del(p.id, e)}
                    className="px-3 py-1.5 text-xs rounded-lg border border-zinc-200 dark:border-zinc-700 text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors">
                    Xoá
                  </button>
                  <button className="btn-primary text-xs px-4">Mở →</button>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
