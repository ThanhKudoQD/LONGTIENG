import React, { useEffect, useState, useRef } from 'react'
import useStore from '../store'
import api from '../api'
import { secToSrt, srtToSec } from '../types'

export default function EditPanel() {
  const { subtitles, characters, activeSubId, updateSubtitle, deleteSubtitle, setActiveSubId } = useStore()

  const activeSub = subtitles.find(s => s.id === activeSubId) ?? null
  const lastSubRef = useRef<typeof activeSub>(null)
  if (activeSub) lastSubRef.current = activeSub
  const sub = lastSubRef.current

  const [text, setText] = useState('')
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [charId, setCharId] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  useEffect(() => {
    if (!activeSub) return
    setText(activeSub.text)
    setStart(secToSrt(activeSub.start_time))
    setEnd(secToSrt(activeSub.end_time))
    setCharId(activeSub.character_id ? String(activeSub.character_id) : '')
    setConfirmDelete(false)
  }, [activeSub?.id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === 'Delete' && sub && !confirmDelete) { e.preventDefault(); setConfirmDelete(true) }
      if (e.key === 'Enter' && confirmDelete) { e.preventDefault(); handleDelete() }
      if (e.key === 'Escape' && confirmDelete) setConfirmDelete(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [confirmDelete, sub?.id])

  const handleDelete = async () => {
    if (!sub) return
    const idx = subtitles.findIndex(s => s.id === sub.id)
    await api.delete(`/subtitles/${sub.id}`)
    deleteSubtitle(sub.id)
    setConfirmDelete(false)
    lastSubRef.current = null
    const remaining = subtitles.filter(s => s.id !== sub.id)
    if (remaining.length > 0) setActiveSubId(remaining[Math.min(idx, remaining.length - 1)].id)
  }

  const save = async () => {
    if (!sub) return
    setSaving(true)
    try {
      const patch = {
        text,
        start_time: srtToSec(start),
        end_time: srtToSec(end),
        character_id: charId ? parseInt(charId) : null,
        audio_offset: 0,
      }
      await api.patch(`/subtitles/${sub.id}`, patch)
      updateSubtitle(sub.id, { ...patch, character: characters.find(c => c.id === patch.character_id) })
    } finally { setSaving(false) }
  }

  return (
    <div className="border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex-shrink-0 p-3 space-y-2 relative">

      {/* Confirm delete */}
      {confirmDelete && sub && (
        <div className="absolute inset-0 z-20 bg-white/95 dark:bg-zinc-900/95 flex flex-col items-center justify-center gap-3 rounded">
          <p className="text-[13px] text-zinc-700 dark:text-zinc-300 text-center px-4">
            Xóa dòng <span className="font-semibold">#{sub.index}</span>?<br/>
            <span className="text-zinc-400 text-[12px]">"{sub.text.slice(0, 40)}{sub.text.length > 40 ? '...' : ''}"</span>
          </p>
          <div className="flex gap-2">
            <button onClick={handleDelete} className="px-4 py-1.5 rounded-lg bg-red-500 hover:bg-red-600 text-white text-[13px] font-medium transition-colors">Xóa (Enter)</button>
            <button onClick={() => setConfirmDelete(false)} className="px-4 py-1.5 rounded-lg border border-zinc-200 text-[13px] hover:bg-zinc-50 transition-colors">Huỷ (Esc)</button>
          </div>
        </div>
      )}

      {!sub ? (
        <div className="flex items-center justify-center h-[80px] rounded-lg border border-dashed border-zinc-200 dark:border-zinc-700 text-[12px] text-zinc-400">
          Phát video để xem phụ đề
        </div>
      ) : (
        <>
          {/* Row 1: index + timing + char + xóa */}
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] text-zinc-400 font-mono flex-shrink-0">#{sub.index}</span>

            {/* Time inputs — rộng hơn để hiện đủ HH:MM:SS,mmm */}
            <input value={start} onChange={e => setStart(e.target.value)}
              className="input text-[12px] font-mono flex-shrink-0"
              style={{ width: 110 }} />
            <span className="text-zinc-300 flex-shrink-0">→</span>
            <input value={end} onChange={e => setEnd(e.target.value)}
              className="input text-[12px] font-mono flex-shrink-0"
              style={{ width: 110 }} />

            <select value={charId} onChange={e => setCharId(e.target.value)}
              className="input text-[12px] flex-1 min-w-0">
              <option value="">— nhân vật —</option>
              {characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button onClick={() => setConfirmDelete(true)} title="Xóa (Delete)"
              className="flex-shrink-0 w-8 h-8 rounded-lg border border-red-200 dark:border-red-900 text-red-400 hover:bg-red-500 hover:text-white hover:border-red-500 flex items-center justify-center transition-all duration-150">
              <svg width="13" height="13" viewBox="0 0 13 13" fill="none">
                <path d="M2 3h9M5 3V2h3v1M4 3l.5 7.5h4L9 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </button>
          </div>

          {/* Row 2: textarea + nút Lưu */}
          <div className="flex gap-2 items-stretch">
            <textarea
              value={text}
              onChange={e => setText(e.target.value)}
              rows={3}
              className="input text-[14px] flex-1 resize-none leading-relaxed font-medium"

              style={{ minHeight: 72 }}
            />

            <button
              onClick={save}
              disabled={saving}
              title="Lưu"
              className="flex-shrink-0 flex flex-col items-center justify-center gap-1 rounded-xl transition-all duration-150 disabled:opacity-60 active:scale-95"
              style={{
                width: 52,
                background: saving ? '#93C5FD' : '#1D4ED8',
                boxShadow: '0 2px 8px rgba(29,78,216,0.35)',
                border: 'none',
              }}
              onMouseEnter={e => {
                if (saving) return
                const el = e.currentTarget
                el.style.background = '#2563EB'
                el.style.boxShadow = '0 4px 14px rgba(29,78,216,0.5)'
                el.style.transform = 'scale(1.04)'
              }}
              onMouseLeave={e => {
                const el = e.currentTarget
                el.style.background = saving ? '#93C5FD' : '#1D4ED8'
                el.style.boxShadow = '0 2px 8px rgba(29,78,216,0.35)'
                el.style.transform = 'scale(1)'
              }}
            >
              {saving ? (
                <div className="w-5 h-5 rounded-full border-2 border-white border-t-transparent animate-spin" />
              ) : (
                <>
                  <svg width="18" height="18" viewBox="0 0 15 15" fill="none" className="text-white">
                    <path d="M2.5 2.5h8L12 4V12.5H2.5V2.5Z" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round"/>
                    <rect x="4.5" y="8" width="6" height="4" rx="0.5" fill="currentColor" opacity="0.5"/>
                    <rect x="4.5" y="3" width="5" height="3" rx="0.5" fill="currentColor" opacity="0.5"/>
                  </svg>
                  <span className="text-[11px] text-white font-bold tracking-wide">Lưu</span>
                </>
              )}
            </button>
          </div>
        </>
      )}
    </div>
  )
}