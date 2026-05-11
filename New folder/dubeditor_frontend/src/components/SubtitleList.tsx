import React, { useRef, useEffect, useMemo, useState, useCallback } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import useStore from '../store'
import api from '../api'
import { playSubAudio, stopGlobalAudio, subscribePlayingId } from '../audio'
import { findDuplicateStarts } from '../utils/perf'
import type { Subtitle, Chapter } from '../types'
import { getEffectiveSpeed } from '../types'

interface Props {
  filter: string
  filterNoChar: boolean
  filterNoTTS: boolean
  overlapSubIds?: Set<number>
  filterCharId?: number | null
  chapters?: Chapter[]
  onToggleChapter?: (chapterId: number) => void
}

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

/** Icon spinner xoay khi sub đang xử lý ở queue worker */
function QueueSpinner() {
  return (
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none" className="animate-spin"
      style={{ color: '#3B82F6', flexShrink: 0 }}>
      <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.5" strokeOpacity="0.25"/>
      <path d="M12 7a5 5 0 0 0-5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  )
}

/** Icon đồng hồ khi sub đang chờ trong queue */
function QueueClock() {
  return (
    <svg width="13" height="13" viewBox="0 0 14 14" fill="none"
      style={{ color: '#A78BFA', flexShrink: 0 }}>
      <circle cx="7" cy="7" r="5" stroke="currentColor" strokeWidth="1.3"/>
      <path d="M7 4v3l2 1.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  )
}

// ─── Row component memo ────────────────────────────────────────────────────
// Tách Row + React.memo để khi 1 sub đổi (TTS xong, click chọn), chỉ row đó
// re-render thay vì 6000 rows. Đây là chìa khoá hiệu năng khi bulk TTS.
interface RowProps {
  s: Subtitle
  isActive: boolean
  isSel: boolean
  isDup: boolean
  isOverlap: boolean
  isTTSLoading: boolean
  isPlaying: boolean
  isQueued: boolean       // có trong queue chờ
  isQueueRunning: boolean // đang xử lý ở GPU (queue running)
  onClick: (e: React.MouseEvent, s: Subtitle) => void
  onDrop: (e: React.DragEvent, id: number) => void
  onTTS: (e: React.MouseEvent, s: Subtitle) => void
  onDeleteAudio: (e: React.MouseEvent, s: Subtitle) => void
  onDeleteSub: (e: React.MouseEvent, s: Subtitle) => void
  top: number
  height: number
}

const Row = React.memo(function Row({
  s, isActive, isSel, isDup, isOverlap, isTTSLoading, isPlaying,
  isQueued, isQueueRunning,
  onClick, onDrop, onTTS, onDeleteAudio, onDeleteSub, top, height,
}: RowProps) {
  const char = s.character

  let rowBg = '#FAFAF8', rowBorder = '#E8E6E0'
  if (isActive)        { rowBg = '#223966'; rowBorder = '#1E40AF' }
  else if (isSel)      { rowBg = '#EFF6FF'; rowBorder = '#BFDBFE' }
  else if (isOverlap)  { rowBg = '#FFF5F5'; rowBorder = '#FCA5A5' }
  else if (!char)      { rowBg = '#FFFBF0'; rowBorder = '#E8E6E0' }

  return (
    <div
      className="absolute left-0 right-0 flex items-stretch cursor-pointer"
      style={{
        top, height,
        background: rowBg,
        borderBottom: `1px solid ${rowBorder}`,
        outline: isDup ? '2px solid #EA580C' : 'none',
        outlineOffset: -2,
        zIndex: isDup ? 1 : isActive ? 2 : 0,
      }}
      onClick={e => onClick(e, s)}
      onDragOver={e => e.preventDefault()}
      onDrop={e => onDrop(e, s.id)}>

      <div className="w-8 flex-shrink-0 flex flex-col items-center justify-center gap-1 py-2">
        <span style={{ fontSize: 11, fontFamily: 'monospace', color: isActive ? 'rgba(255,255,255,0.6)' : '#9CA3AF', fontWeight: 600 }}>{s.index}</span>
        {isQueueRunning ? <QueueSpinner /> :
         isQueued       ? <QueueClock /> :
         <MicIcon active={s.tts_done} />}
      </div>

      <div className="w-[3px] flex-shrink-0 my-2 rounded-full"
        style={{ background: isPlaying ? '#10B981' : isActive ? 'rgba(255,255,255,0.5)' : isDup ? '#EA580C' : char?.color || '#D1D5DB' }} />

      <div className="flex-1 min-w-0 flex flex-col justify-center py-1.5 px-2.5 gap-1">
        <div className="flex items-center gap-2">
          <div className="flex flex-col leading-none">
            <span style={{ fontSize: 11, fontFamily: 'monospace', fontWeight: 700, color: isActive ? '#BFDBFE' : '#374151' }}>
              {fmt(s.start_time)}
            </span>
            <span style={{ fontSize: 10, fontFamily: 'monospace', color: isActive ? 'rgba(255,255,255,0.45)' : '#9CA3AF' }}>
              {fmt(s.end_time)}
            </span>
          </div>
          {char ? (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-bold"
              style={{ background: isActive ? 'rgba(255,255,255,0.18)' : char.color+'22', color: isActive ? '#fff' : char.color }}>
              {char.name}
            </span>
          ) : (
            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-bold"
              style={{ background: isActive ? 'rgba(255,255,255,0.12)' : '#FEF3C7', color: isActive ? 'rgba(255,255,255,0.7)' : '#92400E' }}>
              chưa gán
            </span>
          )}
        </div>
        <span className="truncate leading-snug"
          style={{ fontSize: 15, color: isActive ? '#fff' : '#1F2937', fontWeight: isActive ? 700 : 500 }}>
          {s.text}
        </span>
      </div>

      <div className="flex items-stretch gap-1 px-2 py-2 flex-shrink-0">
        <div className="flex flex-col gap-1">
          <button onClick={e => onTTS(e, s)} disabled={isTTSLoading}
            className="flex items-center gap-1 px-2 h-7 rounded-md text-[11px] font-semibold transition-all active:scale-95 disabled:opacity-40"
            style={{ background: isActive ? 'rgba(255,255,255,0.15)' : '#EFF6FF', border: `1.5px solid ${isActive ? 'rgba(255,255,255,0.2)' : '#BFDBFE'}`, color: isActive ? '#fff' : '#3B82F6', minWidth: 72 }}>
            {isTTSLoading
              ? <div className="w-3 h-3 rounded-full border-2 border-blue-400 border-t-transparent animate-spin"/>
              : <svg width="11" height="11" viewBox="0 0 12 12" fill="none"><path d="M10 6A4 4 0 1 1 6 2a4 4 0 0 1 2.83 1.17L10 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M10 2v2.5H7.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
            }
            Tạo lại
          </button>
          <button onClick={e => onDeleteAudio(e, s)} disabled={!s.audio_path}
            className="flex items-center gap-1 px-2 h-7 rounded-md text-[11px] font-semibold transition-all active:scale-95 disabled:opacity-30"
            style={{ background: isActive ? 'rgba(255,255,255,0.12)' : '#fff', border: `1.5px solid ${isActive ? 'rgba(255,255,255,0.2)' : s.tts_done ? '#FCA5A5' : '#E5E7EB'}`, color: isActive ? '#fff' : s.tts_done ? '#EF4444' : '#9CA3AF', minWidth: 72 }}>
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none"><path d="M2 4H4L6 1.5V10.5L4 8H2V4Z" fill="currentColor" opacity="0.6"/><line x1="8" y1="4" x2="11" y2="7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/><line x1="11" y1="4" x2="8" y2="7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
            Xóa audio
          </button>
        </div>

        <div className="w-px self-stretch mx-0.5" style={{ background: isActive ? 'rgba(255,255,255,0.2)' : '#E5E7EB' }}/>

        <button onClick={e => onDeleteSub(e, s)}
          className="flex flex-col items-center justify-center gap-0.5 px-2 rounded-md text-[10px] font-semibold transition-all active:scale-95 self-stretch"
          style={{ background: isActive ? 'rgba(255,255,255,0.1)' : '#fff', border: `1.5px solid ${isActive ? 'rgba(255,255,255,0.2)' : '#FECACA'}`, color: isActive ? '#fff' : '#F87171', minWidth: 44 }}>
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M2 3h9M5 3V2h3v1M4 3l.5 7.5h4L9 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round"/></svg>
          Xóa
        </button>
      </div>
    </div>
  )
})

// ─── Main ──────────────────────────────────────────────────────────────────
export default function SubtitleList({ filter, filterNoChar, filterNoTTS, overlapSubIds, filterCharId, chapters = [], onToggleChapter }: Props) {
  // PERF: selectors riêng cho từng field — KHÔNG destructure useStore()
  const subtitles  = useStore(s => s.subtitles)
  const characters = useStore(s => s.characters)
  const activeSubId = useStore(s => s.activeSubId)
  const selectedIds = useStore(s => s.selectedIds)
  const toggleSelect    = useStore(s => s.toggleSelect)
  const updateSubtitle  = useStore(s => s.updateSubtitle)
  const deleteAudioStore = useStore(s => s.deleteAudio)
  const deleteSubStore  = useStore(s => s.deleteSubtitle)
  const setActiveSubId  = useStore(s => s.setActiveSubId)

  // Queue state — show icon trên row
  const ttsQueueRunning = useStore(s => s.ttsQueueRunning)
  const ttsQueuePending = useStore(s => s.ttsQueuePending)
  const pendingSet = useMemo(() => new Set(ttsQueuePending), [ttsQueuePending])

  const parentRef = useRef<HTMLDivElement>(null)
  const [ttsLoadingId, setTtsLoadingId] = useState<number | null>(null)
  const [playingId, setPlayingId] = useState<number | null>(null)

  // PERF: pub/sub thay setInterval(150ms)
  useEffect(() => subscribePlayingId(setPlayingId), [])

  // PERF: O(n log n) thay O(n²)
  const dupStartIds = useMemo(() => findDuplicateStarts(subtitles), [subtitles])

  // PERF: memo filter — không chạy lại mỗi render
  const visible = useMemo(() => {
    const f = filter.toLowerCase()
    return subtitles.filter(s => {
      if (f && !s.text.toLowerCase().includes(f) &&
          !(s.character?.name.toLowerCase().includes(f))) return false
      if (filterNoChar && s.character_id) return false
      if (filterNoTTS && s.tts_done) return false
      if (overlapSubIds && overlapSubIds.size > 0 && !overlapSubIds.has(s.id)) return false
      if (filterCharId != null && s.character_id !== filterCharId) return false
      return true
    })
  }, [subtitles, filter, filterNoChar, filterNoTTS, overlapSubIds, filterCharId])

  const visibleIds = useMemo(() => visible.map(s => s.id), [visible])

  // ─── Build items array với chapters ─────────────────────────────────────
  // Khi có chapters: items = [header(ch1), sub1, sub2, ..., header(ch2), ...]
  // Khi không: items = [sub1, sub2, ...]
  type ItemSub = { type: 'sub', sub: Subtitle }
  type ItemHeader = { type: 'header', chapter: Chapter, count: number, collapsed: boolean }
  type Item = ItemSub | ItemHeader

  const items = useMemo<Item[]>(() => {
    if (!chapters.length) {
      return visible.map(s => ({ type: 'sub' as const, sub: s }))
    }

    // Sort chapters theo sort_order
    const sortedChapters = [...chapters].sort((a, b) => a.sort_order - b.sort_order)

    // Group visible subs theo chapter (theo `index` của sub)
    const result: Item[] = []
    const chapterRanges = sortedChapters.map(c => ({
      chapter: c,
      subs: visible.filter(s => s.index >= c.start_sub_index && s.index <= c.end_sub_index),
    }))
    // Subs ngoài tất cả chapter (nếu có) — đẩy vào mục "Chưa phân loại" cuối
    const allChapterRanges = sortedChapters.map(c => [c.start_sub_index, c.end_sub_index] as [number, number])
    const orphanSubs = visible.filter(s =>
      !allChapterRanges.some(([lo, hi]) => s.index >= lo && s.index <= hi)
    )

    for (const { chapter, subs } of chapterRanges) {
      const collapsed = !!chapter.collapsed
      result.push({
        type: 'header',
        chapter,
        count: subs.length,
        collapsed,
      })
      if (!collapsed) {
        for (const s of subs) result.push({ type: 'sub', sub: s })
      }
    }
    // Orphan subs (sub ngoài range chapter) — hiển thị ở dưới cùng không có header
    for (const s of orphanSubs) {
      result.push({ type: 'sub', sub: s })
    }
    return result
  }, [visible, chapters])

  const HEADER_H = 44
  const SUB_H    = 68

  const virt = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => items[index]?.type === 'header' ? HEADER_H : SUB_H,
    overscan: 14,
  })

  // Lưu ý cho virtualizer: estimateSize phụ thuộc vào items, phải reset khi items đổi
  useEffect(() => { virt.measure() }, [items.length])

  // Auto scroll list theo activeSubId
  // PERF: dùng ref để đọc visible/items hiện tại — tránh effect re-run khi subtitles
  // đổi (TTS xong từng dòng) trong khi activeSubId không đổi.
  const visibleRef = useRef(visible)
  visibleRef.current = visible
  const itemsRef = useRef(items)
  itemsRef.current = items

  useEffect(() => {
    if (!activeSubId) return
    // Tìm item index trong items (có thể là sub trong chapter expanded)
    const idx = itemsRef.current.findIndex(it => it.type === 'sub' && it.sub.id === activeSubId)
    if (idx < 0) return
    const parent = parentRef.current; if (!parent) return

    // Lấy offset của item từ virtualizer
    const itemSize = SUB_H
    // Tính offset thủ công theo cumulated size — virtualizer đã có sẵn offset
    let itemTop = 0
    for (let i = 0; i < idx; i++) {
      itemTop += itemsRef.current[i].type === 'header' ? HEADER_H : SUB_H
    }
    const itemBottom = itemTop + itemSize
    const scrollTop = parent.scrollTop
    const viewHeight = parent.clientHeight
    if (itemBottom > scrollTop + viewHeight * 0.7) {
      parent.scrollTo({ top: itemTop - viewHeight * 0.5, behavior: 'smooth' })
    } else if (itemTop < scrollTop) {
      parent.scrollTo({ top: itemTop - SUB_H, behavior: 'smooth' })
    }
  }, [activeSubId])

  // PERF: handlers wrap useCallback để Row.memo skip re-render khi parent re-render
  const handleDrop = useCallback(async (e: React.DragEvent, subId: number) => {
    e.preventDefault()
    const charId = parseInt(e.dataTransfer.getData('charId'))
    if (!charId) return
    const char = characters.find(c => c.id === charId)
    await api.patch(`/subtitles/${subId}`, { character_id: charId })
    updateSubtitle(subId, { character_id: charId, character: char })
    // Trigger auto TTS — Editor lắng nghe event này
    window.dispatchEvent(new CustomEvent('subs_assigned', { detail: { subtitle_ids: [subId] } }))
  }, [characters, updateSubtitle])

  const handleTTS = useCallback(async (e: React.MouseEvent, s: Subtitle) => {
    e.stopPropagation()
    // Đang xử lý ở GPU thì bỏ qua, đợi xong sẽ có kết quả
    if (useStore.getState().ttsQueueRunning === s.id) return
    // Gọi /tts/generate → backend tự enqueue priority high (move lên đầu)
    try {
      await api.post('/tts/generate', { subtitle_id: s.id })
    } catch (err) {
      console.error(err)
    }
  }, [])

  const handleRowClick = useCallback((e: React.MouseEvent, s: Subtitle) => {
    toggleSelect(s.id, e.ctrlKey || e.metaKey, e.shiftKey, visibleIds)
    const video = document.querySelector('video') as HTMLVideoElement | null
    const videoPlaying = video && !video.paused
    if (!videoPlaying && s.audio_path && s.tts_done) {
      const char = s.character || characters.find(c => c.id === s.character_id)
      const speed = getEffectiveSpeed(s, char)
      playSubAudio(s.id, s.audio_path, undefined, speed)
    } else {
      stopGlobalAudio()
    }
  }, [toggleSelect, visibleIds, characters])

  const handleDeleteAudio = useCallback(async (e: React.MouseEvent, s: Subtitle) => {
    e.stopPropagation()
    if (!s.audio_path) return
    await api.post('/tts/delete-audio', { subtitle_ids: [s.id] })
    deleteAudioStore([s.id])
  }, [deleteAudioStore])

  const handleDeleteSub = useCallback(async (e: React.MouseEvent, s: Subtitle) => {
    e.stopPropagation()
    if (!window.confirm(`Xóa dòng #${s.index}?\n"${s.text.slice(0, 60)}"`)) return
    const idx = subtitles.findIndex(sub => sub.id === s.id)
    await api.delete(`/subtitles/${s.id}`)
    deleteSubStore(s.id)
    const remaining = subtitles.filter(sub => sub.id !== s.id)
    if (remaining.length > 0) setActiveSubId(remaining[Math.min(idx, remaining.length - 1)].id)
  }, [subtitles, deleteSubStore, setActiveSubId])

  return (
    <div ref={parentRef} className="flex-1 overflow-y-auto bg-[#FAFAF8] dark:bg-zinc-900">
      <div style={{ height: virt.getTotalSize(), position: 'relative' }}>
        {virt.getVirtualItems().map(vi => {
          const it = items[vi.index]
          if (!it) return null

          if (it.type === 'header') {
            const ch = it.chapter
            const statusColor = ch.status === 'done' ? '#10B981'
              : ch.status === 'in_progress' ? '#F59E0B'
              : '#9CA3AF'
            const statusIcon = ch.status === 'done' ? '✓'
              : ch.status === 'in_progress' ? '▶'
              : '○'
            return (
              <div key={`h-${ch.id}`}
                onClick={() => onToggleChapter && onToggleChapter(ch.id)}
                className="absolute left-0 right-0 cursor-pointer select-none flex items-center gap-2 px-3 border-b-2 hover:opacity-90 transition-opacity"
                style={{
                  top: vi.start,
                  height: vi.size,
                  background: '#1E293B',
                  borderBottomColor: statusColor,
                  zIndex: 5,
                }}>
                <span className="text-white/70 text-[14px] font-mono w-4">
                  {it.collapsed ? '▶' : '▼'}
                </span>
                <span className="text-white font-bold text-[14px]">{ch.name}</span>
                <span className="text-white/50 text-[11px] font-mono">
                  ({ch.start_sub_index}-{ch.end_sub_index})
                </span>
                <span className="ml-auto flex items-center gap-2">
                  <span className="text-white/60 text-[11px] tabular-nums">
                    {it.count}{it.collapsed ? '' : '/' + (ch.end_sub_index - ch.start_sub_index + 1)} dòng
                  </span>
                  <span className="text-[11px] font-bold px-2 py-0.5 rounded"
                    style={{ background: statusColor + '30', color: statusColor }}>
                    {statusIcon} {ch.status === 'done' ? 'Xong' : ch.status === 'in_progress' ? 'Đang làm' : 'Chưa làm'}
                  </span>
                </span>
              </div>
            )
          }

          // sub item
          const s = it.sub
          const isActive  = s.id === activeSubId
          const isSel     = selectedIds.has(s.id)
          const isDup     = dupStartIds.has(s.id)
          const isOverlap = overlapSubIds ? overlapSubIds.has(s.id) : false
          const isTTSLoading = ttsLoadingId === s.id
          const isPlaying = playingId === s.id
          const isQueueRunning = ttsQueueRunning === s.id
          const isQueued       = !isQueueRunning && pendingSet.has(s.id)

          return (
            <Row key={s.id}
              s={s}
              isActive={isActive}
              isSel={isSel}
              isDup={isDup}
              isOverlap={isOverlap}
              isTTSLoading={isTTSLoading}
              isPlaying={isPlaying}
              isQueued={isQueued}
              isQueueRunning={isQueueRunning}
              onClick={handleRowClick}
              onDrop={handleDrop}
              onTTS={handleTTS}
              onDeleteAudio={handleDeleteAudio}
              onDeleteSub={handleDeleteSub}
              top={vi.start}
              height={vi.size}
            />
          )
        })}
      </div>
    </div>
  )
}
