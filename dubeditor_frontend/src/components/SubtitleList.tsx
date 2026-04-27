import React, { useRef, useEffect, useMemo, useState } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import useStore from '../store'
import api from '../api'
import { playSubAudio, stopGlobalAudio, getGlobalPlayingId } from './AudioList'

interface Props { filter: string; filterNoChar: boolean; filterNoTTS: boolean; overlapSubIds?: Set<number>; filterCharId?: number | null }

const fmt = (s: number) => {
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(3)
  return `${String(m).padStart(2, '0')}:${sec.padStart(6, '0')}`
}

function MicIcon({ active }: { active: boolean }) {
  return (
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none"
      style={{ color: active ? '#10B981' : '#C4C4C4', flexShrink: 0 }}>
      <rect x="4.5" y="1" width="5" height="7" rx="2.5" fill="currentColor"/>
      <path d="M2.5 7C2.5 9.5 11.5 9.5 11.5 7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
      <line x1="7" y1="9.5" x2="7" y2="12" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
      <line x1="5" y1="12" x2="9" y2="12" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
    </svg>
  )
}

export default function SubtitleList({ filter, filterNoChar, filterNoTTS, overlapSubIds, filterCharId }: Props) {
  const { subtitles, characters, activeSubId, selectedIds, toggleSelect, updateSubtitle, deleteAudio } = useStore()
  const parentRef = useRef<HTMLDivElement>(null)
  const [ttsLoadingId, setTtsLoadingId] = useState<number | null>(null)
  const [playingId, setPlayingId] = useState<number | null>(null)

  // Sync playingId với global audio
  useEffect(() => {
    const id = setInterval(() => setPlayingId(getGlobalPlayingId()), 150)
    return () => clearInterval(id)
  }, [])

  const dupStartIds = useMemo(() => {
    const ids = new Set<number>()
    for (let i = 0; i < subtitles.length; i++) {
      for (let j = i + 1; j < subtitles.length; j++) {
        if (Math.abs(subtitles[i].start_time - subtitles[j].start_time) < 0.05) {
          ids.add(subtitles[i].id); ids.add(subtitles[j].id)
        }
      }
    }
    return ids
  }, [subtitles])

  const visible = subtitles.filter(s => {
    if (filter && !s.text.toLowerCase().includes(filter.toLowerCase()) &&
        !(s.character?.name.toLowerCase().includes(filter.toLowerCase()))) return false
    if (filterNoChar && s.character_id) return false
    if (filterNoTTS && s.tts_done) return false
    if (overlapSubIds && overlapSubIds.size > 0 && !overlapSubIds.has(s.id)) return false
    if (filterCharId != null && s.character_id !== filterCharId) return false
    return true
  })

  const virt = useVirtualizer({
    count: visible.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 68,
    overscan: 14,
  })

  // Auto scroll list phụ đề theo activeSubId
  useEffect(() => {
    if (!activeSubId) return
    const idx = visible.findIndex(s => s.id === activeSubId)
    if (idx < 0) return
    const parent = parentRef.current; if (!parent) return
    const ITEM_H = 68
    const itemTop = idx * ITEM_H
    const itemBottom = itemTop + ITEM_H
    const scrollTop = parent.scrollTop
    const viewHeight = parent.clientHeight
    if (itemBottom > scrollTop + viewHeight * 0.7) {
      parent.scrollTo({ top: itemTop - viewHeight * 0.5, behavior: 'smooth' })
    } else if (itemTop < scrollTop) {
      parent.scrollTo({ top: itemTop - ITEM_H, behavior: 'smooth' })
    }
  }, [activeSubId])

  const handleDrop = async (e: React.DragEvent, subId: number) => {
    e.preventDefault()
    const charId = parseInt(e.dataTransfer.getData('charId'))
    if (!charId) return
    const char = characters.find(c => c.id === charId)
    await api.patch(`/subtitles/${subId}`, { character_id: charId })
    updateSubtitle(subId, { character_id: charId, character: char })
  }

  const handleTTS = async (e: React.MouseEvent, s: typeof subtitles[0]) => {
    e.stopPropagation()
    if (ttsLoadingId) return
    setTtsLoadingId(s.id)
    try {
      const res = await api.post('/tts/generate', { subtitle_id: s.id })
      updateSubtitle(s.id, { tts_done: true, audio_path: res.data.audio_path })
    } finally { setTtsLoadingId(null) }
  }

  // Click row → select + tự phát audio nếu có
  const handleRowClick = (e: React.MouseEvent, s: typeof subtitles[0]) => {
    toggleSelect(s.id, e.ctrlKey || e.metaKey, e.shiftKey, visible.map(s => s.id))
    // Chỉ phát audio khi video KHÔNG đang play
    const video = document.querySelector('video') as HTMLVideoElement | null
    const videoPlaying = video && !video.paused
    if (!videoPlaying && s.audio_path && s.tts_done) {
      const playing = playSubAudio(s.id, s.audio_path, () => setPlayingId(null))
      setPlayingId(playing ? s.id : null)
    } else {
      stopGlobalAudio()
      setPlayingId(null)
    }
  }

  // Nút play riêng
  const handleDeleteAudio = async (e: React.MouseEvent, s: typeof subtitles[0]) => {
    e.stopPropagation()
    if (!s.audio_path) return
    await api.post('/tts/delete-audio', { subtitle_ids: [s.id] })
    deleteAudio([s.id])
  }

  const handlePlayBtn = (e: React.MouseEvent, s: typeof subtitles[0]) => {
    e.stopPropagation()
    if (!s.audio_path) return
    const playing = playSubAudio(s.id, s.audio_path, () => setPlayingId(null))
    setPlayingId(playing ? s.id : null)
  }

  return (
    <div ref={parentRef} className="flex-1 overflow-y-auto bg-[#FAFAF8] dark:bg-zinc-900">
      <div style={{ height: virt.getTotalSize(), position: 'relative' }}>
        {virt.getVirtualItems().map(item => {
          const s = visible[item.index]
          const isActive  = s.id === activeSubId
          const isSel     = selectedIds.has(s.id)
          const char      = s.character
          const isDup     = dupStartIds.has(s.id)
          const isOverlap = overlapSubIds ? overlapSubIds.has(s.id) : false
          const isTTSLoading = ttsLoadingId === s.id
          const isPlaying = playingId === s.id

          let rowBg = '#FAFAF8', rowBorder = '#E8E6E0'
          if (isActive)        { rowBg = '#1D4ED8'; rowBorder = '#1E40AF' }
          else if (isSel)      { rowBg = '#EFF6FF'; rowBorder = '#BFDBFE' }
          else if (isOverlap)  { rowBg = '#FFF5F5'; rowBorder = '#FCA5A5' }
          else if (!char)      { rowBg = '#FFFBF0'; rowBorder = '#E8E6E0' }

          return (
            <div key={s.id}
              className="absolute left-0 right-0 flex items-stretch cursor-pointer"
              style={{
                top: item.start, height: item.size,
                background: rowBg,
                borderBottom: `1px solid ${rowBorder}`,
                outline: isDup ? '2px solid #EA580C' : 'none',
                outlineOffset: -2,
                zIndex: isDup ? 1 : isActive ? 2 : 0,
              }}
              onClick={e => handleRowClick(e, s)}
              onDragOver={e => e.preventDefault()}
              onDrop={e => handleDrop(e, s.id)}>

              {/* Mic icon */}
              <div className="w-9 flex-shrink-0 flex items-center justify-center">
                <MicIcon active={s.tts_done} />
              </div>

              {/* Index */}
              <div className="w-8 flex-shrink-0 flex items-center justify-end pr-1.5">
                <span style={{ fontSize: 13, fontFamily: 'monospace', color: isActive ? 'rgba(255,255,255,0.6)' : '#9CA3AF', fontWeight: isActive ? 700 : 400 }}>
                  {s.index}
                </span>
              </div>

              {/* Accent bar */}
              <div className="w-[3px] flex-shrink-0 my-2.5 rounded-full"
                style={{ background: isPlaying ? '#10B981' : isActive ? 'rgba(255,255,255,0.4)' : isDup ? '#EA580C' : char?.color || '#D1D5DB' }} />

              {/* Timestamps */}
              <div className="w-[90px] flex-shrink-0 flex flex-col justify-center px-2.5 gap-[2px]">
                <span style={{ fontSize: 12, fontFamily: 'monospace', fontWeight: 700, color: isActive ? '#BFDBFE' : '#374151' }}>
                  {fmt(s.start_time)}
                </span>
                <span style={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 600, color: isActive ? 'rgba(255,255,255,0.55)' : '#6B7280' }}>
                  {fmt(s.end_time)}
                </span>
              </div>

              {/* Content */}
              <div className="flex-1 min-w-0 flex flex-col justify-center py-2 pr-2 gap-1">
                <div className="flex items-center gap-1.5">
                  <span style={{ fontSize: 10, fontWeight: 600, color: isActive ? 'rgba(255,255,255,0.45)' : '#9CA3AF', textTransform: 'uppercase', letterSpacing: '0.04em' }}>NV:</span>
                  {char ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-md font-bold"
                      style={{ fontSize: 12, background: isActive ? 'rgba(255,255,255,0.15)' : char.color + '20', color: isActive ? '#fff' : char.color }}>
                      {char.name}
                    </span>
                  ) : (
                    <span className="inline-flex items-center px-2 py-0.5 rounded-md font-bold"
                      style={{ fontSize: 12, background: isActive ? 'rgba(255,255,255,0.12)' : '#FEF3C7', color: isActive ? 'rgba(255,255,255,0.7)' : '#92400E' }}>
                      chưa gán
                    </span>
                  )}
                </div>
                <span className="truncate leading-snug"
                  style={{ fontSize: 16, color: isActive ? '#FFFFFF' : '#1F2937', fontWeight: isActive ? 700 : 500 }}>
                  {s.text}
                </span>
              </div>

              {/* Buttons */}
              <div className="flex flex-col items-center justify-center gap-1.5 px-2 flex-shrink-0">
                {/* Reload TTS */}
                <button onClick={e => handleTTS(e, s)} disabled={isTTSLoading}
                  title="Tạo lại TTS"
                  className="flex items-center justify-center rounded-lg transition-all duration-150 disabled:opacity-50 active:scale-95"
                  style={{ width: 32, height: 28, background: isActive ? 'rgba(255,255,255,0.15)' : '#F3F4F6', border: `1.5px solid ${isActive ? 'rgba(255,255,255,0.25)' : '#D1D5DB'}` }}
                  onMouseEnter={e => { const el = e.currentTarget; el.style.transform = 'scale(1.08)'; el.style.background = isActive ? 'rgba(255,255,255,0.25)' : '#E5E7EB' }}
                  onMouseLeave={e => { const el = e.currentTarget; el.style.transform = 'scale(1)'; el.style.background = isActive ? 'rgba(255,255,255,0.15)' : '#F3F4F6' }}>
                  {isTTSLoading
                    ? <div className="w-3.5 h-3.5 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
                    : <svg width="13" height="13" viewBox="0 0 12 12" fill="none" style={{ color: isActive ? '#fff' : '#4B5563' }}>
                        <path d="M10 6A4 4 0 1 1 6 2a4 4 0 0 1 2.83 1.17L10 4.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
                        <path d="M10 2v2.5H7.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>}
                </button>

                {/* Xóa audio */}
                <button onClick={e => handleDeleteAudio(e, s)} disabled={!s.audio_path}
                  title="Xóa audio"
                  className="flex items-center justify-center rounded-lg transition-all duration-150 disabled:opacity-30 active:scale-95"
                  style={{
                    width: 32, height: 28,
                    background: isActive ? 'rgba(255,255,255,0.15)' : '#FEF2F2',
                    border: `1.5px solid ${isActive ? 'rgba(255,255,255,0.25)' : s.tts_done ? '#FCA5A5' : '#D1D5DB'}`,
                  }}
                  onMouseEnter={e => { if (!s.audio_path) return; e.currentTarget.style.transform = 'scale(1.08)' }}
                  onMouseLeave={e => { e.currentTarget.style.transform = 'scale(1)' }}>
                  <svg width="11" height="11" viewBox="0 0 12 12" fill="none"
                    style={{ color: isActive ? '#fff' : s.tts_done ? '#EF4444' : '#9CA3AF' }}>
                    <path d="M2 4H4L6 1.5V10.5L4 8H2V4Z" fill="currentColor" opacity="0.4"/>
                    <line x1="8" y1="4" x2="11" y2="7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                    <line x1="11" y1="4" x2="8" y2="7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
                  </svg>
                </button>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}