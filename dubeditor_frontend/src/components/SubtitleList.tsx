import React, { useRef, useEffect, useMemo, useState, useCallback } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import useStore from '../store'
import api from '../api'
import { playSubAudio, stopGlobalAudio, subscribePlayingId } from '../audio'
import { findDuplicateStarts } from '../utils/perf'
import type { Subtitle, Chapter } from '../types'
import { loadConfig, getApiKey, getRetranslateModel, getRetranslateThinking, getRetranslateContextWindow } from './ConfigModal'
import { getEffectiveSpeed } from '../types'

interface Props {
  filter: string
  filterNoChar: boolean
  filterNoTTS: boolean
  overlapSubIds?: Set<number>
  filterCharIds?: number[]   // Lọc theo nhiều NV (rỗng = tất cả)
  chapters?: Chapter[]
  onToggleChapter?: (chapterId: number) => void
  filterChapterIds?: number[]
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

/** v3: Icon mode đã dùng khi tạo audio (BT/Buồn/Giận) */
const AUDIO_MODE_META: Record<string, { icon: string; color: string; label: string }> = {
  normal: { icon: '😐', color: '#6B7280', label: 'Bình thường' },
  sad:    { icon: '😭', color: '#2563EB', label: 'Buồn' },
  angry:  { icon: '😡', color: '#DC2626', label: 'Tức giận' },
}
function AudioModeIcon({ mode, isActive }: { mode: string; isActive: boolean }) {
  const meta = AUDIO_MODE_META[mode]
  if (!meta) return null
  return (
    <span title={`Audio đã tạo với mode: ${meta.label}`}
      style={{
        fontSize: 18, lineHeight: 1, padding: '2px 4px', borderRadius: 4,
        background: isActive ? 'rgba(255,255,255,0.15)' : meta.color + '20',
        border: `1px solid ${isActive ? 'rgba(255,255,255,0.3)' : meta.color + '60'}`,
        display: 'inline-flex', alignItems: 'center',
      }}>
      {meta.icon}
    </span>
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

/** Badge mode giọng (3 mode: BT / Buồn / Giận).
 *  Đã được backend tính sẵn qua emotion_to_mode → trả về field `voice_mode`.
 *  Click vào để xem emotion gốc + intensity (tooltip).
 */
const MODE_BADGE: Record<string, { label: string; color: string; icon: string }> = {
  normal: { label: 'BT',     color: '#6B7280', icon: '😐' },
  sad:    { label: 'Buồn',   color: '#2563EB', icon: '😭' },
  angry:  { label: 'Giận',   color: '#DC2626', icon: '😡' },
}

function VoiceModePill({ mode, emotion, intensity, isOverride, isActive }: {
  mode: string
  emotion?: string | null
  intensity?: number | null
  isOverride?: boolean
  isActive: boolean
}) {
  const cfg = MODE_BADGE[mode] || MODE_BADGE.normal
  // Tooltip: hiển thị emotion gốc để user biết LLM đã gán gì
  const tip = isOverride
    ? `Mode (user set): ${cfg.label}${emotion ? ` · gốc: ${emotion} ·${intensity ?? 5}` : ''}`
    : `Mode: ${cfg.label}${emotion ? ` · từ ${emotion} ·${intensity ?? 5}` : ''}`
  return (
    <span
      title={tip}
      style={{
        fontSize: 10, fontWeight: 700, padding: '1px 5px', borderRadius: 4,
        background: isActive ? cfg.color + '55' : cfg.color + '1f',
        color: isActive ? '#fff' : cfg.color,
        whiteSpace: 'nowrap',
        display: 'inline-flex', alignItems: 'center', gap: 3,
        border: isOverride ? `1.5px solid ${cfg.color}` : 'none',
      }}
    >
      <span style={{ fontSize: 18, lineHeight: 1 }}>{cfg.icon}</span>
      {cfg.label}
      {isOverride && <span style={{ opacity: 0.7, fontSize: 9 }}>✋</span>}
    </span>
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
  // v3: onTTS có thêm forceMode (null = dùng auto theo emotion / mode hiện tại)
  onTTS: (e: React.MouseEvent, s: Subtitle, forceMode?: string | null) => void
  onDeleteAudio: (e: React.MouseEvent, s: Subtitle) => void
  onDeleteSub: (e: React.MouseEvent, s: Subtitle) => void
  onRetranslate: (s: Subtitle) => void
  onSetVoiceMode: (s: Subtitle, mode: string) => void
  emotionVoiceOn: boolean
  // v3: list mode khả dụng cho character của row này (đã upload audio)
  availableModes: string[]
  // v3.3: project là SRT Việt thuần — ẩn row TQ + ẩn nút Dịch lại
  isViOnly: boolean
  top: number
  height: number
}

const Row = React.memo(function Row({
  s, isActive, isSel, isDup, isOverlap, isTTSLoading, isPlaying,
  isQueued, isQueueRunning,
  onClick, onDrop, onTTS, onDeleteAudio, onDeleteSub, onRetranslate,
  onSetVoiceMode, emotionVoiceOn, availableModes, isViOnly,
  top, height,
}: RowProps) {
  const char = s.character

  let rowBg = '#FAFAF8', rowBorder = '#E8E6E0'
  if (isActive)        { rowBg = '#223966'; rowBorder = '#1E40AF' }
  else if (isSel)      { rowBg = '#EFF6FF'; rowBorder = '#BFDBFE' }
  else if (isOverlap)  { rowBg = '#FFF5F5'; rowBorder = '#FCA5A5' }
  else if (!char)      { rowBg = '#FFFBF0'; rowBorder = '#E8E6E0' }

  return (
    <div
      className="absolute left-0 right-0 flex items-stretch cursor-pointer group"
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
      onDrop={e => onDrop(e, s.id)}
      onMouseEnter={e => {
        const btns = e.currentTarget.querySelector('.sub-actions') as HTMLElement
        if (btns && !isActive) btns.style.opacity = '1'
      }}
      onMouseLeave={e => {
        const btns = e.currentTarget.querySelector('.sub-actions') as HTMLElement
        if (btns && !isActive) btns.style.opacity = '0'
      }}>

      {/* Col 1: index + mic icon + mode icon */}
      <div className="w-8 flex-shrink-0 flex flex-col items-center justify-center gap-1 py-2">
        <span style={{ fontSize: 11, fontFamily: 'monospace', color: isActive ? 'rgba(255,255,255,0.6)' : '#9CA3AF', fontWeight: 600 }}>{s.index}</span>
        {isQueueRunning ? <QueueSpinner /> : isQueued ? <QueueClock /> : <MicIcon active={s.tts_done} />}
        {/* v3: icon mode đã dùng cho audio hiện tại */}
        {s.tts_done && s.audio_voice_mode && (
          <AudioModeIcon mode={s.audio_voice_mode} isActive={isActive} />
        )}
      </div>

      {/* Col 2: color bar */}
      <div className="w-[3px] flex-shrink-0 my-2 rounded-full"
        style={{ background: isPlaying ? '#10B981' : isActive ? 'rgba(255,255,255,0.5)' : isDup ? '#EA580C' : char?.color || '#D1D5DB' }} />

      {/* Col 3: main content */}
      <div className="flex-1 min-w-0 flex flex-col justify-center py-1.5 px-2.5" style={{ gap: 2 }}>

        {/* Row 1: time (xếp dọc) + character badge — KHÔNG wrap, truncate nếu chật */}
        <div className="flex items-center gap-1.5 min-w-0 overflow-hidden">
          <div className="flex flex-col items-start leading-tight" style={{ fontFamily: 'monospace' }}>
            <span style={{ fontSize: 9, fontWeight: 700, color: isActive ? '#BFDBFE' : '#6B7280', whiteSpace: 'nowrap' }}>
              {fmt(s.start_time)}
            </span>
            <span style={{ fontSize: 9, color: isActive ? 'rgba(255,255,255,0.4)' : '#9CA3AF', whiteSpace: 'nowrap' }}>
              {fmt(s.end_time)}
            </span>
          </div>
          {char ? (
            <span style={{
              fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
              background: isActive ? char.color + '55' : char.color + '22',
              color: isActive ? '#fff' : char.color,
              whiteSpace: 'nowrap', maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {char.name}
            </span>
          ) : (
            <span style={{
              fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4,
              background: isActive ? 'rgba(255,255,255,0.12)' : '#FEF3C7',
              color: isActive ? 'rgba(255,255,255,0.6)' : '#92400E',
            }}>
              chưa gán
            </span>
          )}
          {/* Voice mode badge (3 mode: BT / Buồn / Giận) — computed từ emotion+intensity */}
          <VoiceModePill mode={s.voice_mode || 'normal'} emotion={s.emotion} intensity={s.intensity} isOverride={!!s.tts_voice_mode} isActive={isActive} />

          {/* v3: variant badge — chỉ hiện khi có text_v2 */}
          {s.text_v2 && (
            <span
              style={{
                fontSize: 9, fontWeight: 700, padding: '1px 5px', borderRadius: 3,
                background: s.variant_selected === 2
                  ? (isActive ? 'rgba(192,132,252,0.35)' : '#FAE8FF')
                  : (isActive ? 'rgba(96,165,250,0.35)' : '#DBEAFE'),
                color: s.variant_selected === 2
                  ? (isActive ? '#FAE8FF' : '#7E22CE')
                  : (isActive ? '#DBEAFE' : '#1D4ED8'),
                letterSpacing: '0.04em',
              }}
              title={s.variant_selected === 2 ? 'Đang dùng bản v2 (thoát ý)' : 'Đang dùng bản v1 (sát nghĩa)'}
            >
              v{s.variant_selected || 1}
            </span>
          )}
          {/* Nút Dịch lại đã được move sang Col 4 (cùng cột action buttons)
              để tránh wrap khi sidebar hẹp */}
        </div>

        {/* Row 2: original text (tiếng Trung) — ẩn nếu là SRT Việt thuần */}
        {s.original_text && !isViOnly && (
          <span style={{
            fontSize: 11, color: isActive ? 'rgba(255,255,255,0.45)' : '#9CA3AF',
            fontFamily: 'system-ui,sans-serif', letterSpacing: '0.02em',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block',
          }}>
            {s.original_text}
          </span>
        )}

        {/* Row 3: bản dịch tiếng Việt — split speaker|text nếu BE chưa xử lý */}
        <span style={{
          fontSize: 14, lineHeight: 1.4,
          color: isActive ? '#fff' : '#1F2937',
          fontWeight: isActive ? 700 : 500,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block',
        }}>
          {(() => {
            // SRT Việt thuần (isViOnly): text chính là nội dung Việt → hiển thị luôn.
            // SRT Trung: chỉ hiển thị text khi đã dịch (khác original_text TQ).
            const t = isViOnly
              ? (s.text || '')
              : (s.text && s.text !== s.original_text ? s.text : '')
            if (!t) return <span style={{ fontStyle: 'italic', opacity: 0.35, fontSize: 13 }}>Chưa dịch</span>
            return t.includes('|')
              ? t.split('|').slice(1).join('|').trim() || t
              : t
          })()}
        </span>
      </div>

      {/* Col 4: action buttons — 2x2 grid + nút Dịch lại */}
      <div className="sub-actions flex flex-col gap-1 px-1.5 py-1.5 flex-shrink-0"
        style={{ opacity: isActive ? 1 : 0, transition: 'opacity .12s' }}>
        {/* Row 0: Dịch lại — full width 2 cột (chỉ hiện khi active + có TQ + không phải SRT Việt thuần) */}
        {s.original_text && isActive && !isViOnly && (
          <button
            onClick={e => { e.stopPropagation(); onRetranslate(s) }}
            className="sub-action-btn flex items-center justify-center gap-1 h-6 rounded text-[11px] font-semibold flex-shrink-0"
            style={{
              width: 140, // 68*2 + gap 4
              background: 'rgba(255,255,255,0.15)',
              border: '1px solid rgba(255,255,255,0.25)',
              color: '#fff', cursor: 'pointer', whiteSpace: 'nowrap',
            }}
            title="Dịch lại dòng này">
            ✨ Dịch lại
          </button>
        )}
        {/* Row 1: TTS BT + Xóa audio */}
        <div className="flex items-center gap-1">
          <button onClick={e => onTTS(e, s, 'normal')} disabled={isTTSLoading}
            className="sub-action-btn flex items-center justify-center gap-1 px-2 h-6 rounded text-[11px] font-semibold active:scale-95 disabled:opacity-40 flex-shrink-0 w-[68px]"
            style={{
              background: isActive ? 'rgba(255,255,255,0.15)' : '#EFF6FF',
              border: `1px solid ${isActive ? 'rgba(255,255,255,0.2)' : '#BFDBFE'}`,
              color: isActive ? '#fff' : '#3B82F6',
            }}
            title="TTS — Bình thường (force mode normal)">
            {isTTSLoading
              ? <div className="w-3 h-3 rounded-full border-2 border-current border-t-transparent animate-spin"/>
              : <svg width="10" height="10" viewBox="0 0 12 12" fill="none"><path d="M10 6A4 4 0 1 1 6 2a4 4 0 0 1 2.83 1.17L10 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M10 2v2.5H7.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
            }
            <span>BT</span>
          </button>
          <button onClick={e => onDeleteAudio(e, s)} disabled={!s.audio_path}
            className="sub-action-btn flex items-center justify-center h-6 rounded active:scale-95 disabled:opacity-25 flex-shrink-0 w-[68px]"
            style={{
              background: isActive ? 'rgba(255,255,255,0.1)' : '#fff',
              border: `1px solid ${isActive ? 'rgba(255,255,255,0.2)' : s.tts_done ? '#FCA5A5' : '#E5E7EB'}`,
              color: isActive ? '#fff' : s.tts_done ? '#EF4444' : '#9CA3AF',
            }}
            title="Xóa audio">
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
              <path d="M2 4H4L6 1.5V10.5L4 8H2V4Z" fill="currentColor" opacity="0.7"/>
              <line x1="8" y1="4" x2="11" y2="7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              <line x1="11" y1="4" x2="8" y2="7" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            </svg>
            <span className="text-[10px] ml-1">Xóa</span>
          </button>
        </div>
        {/* Row 2: TTS Buồn + TTS Giận */}
        <div className="flex items-center gap-1">
          {(() => {
            const hasSad = availableModes.includes('sad')
            return (
              <button onClick={e => onTTS(e, s, 'sad')} disabled={isTTSLoading || !hasSad}
                className="sub-action-btn flex items-center justify-center gap-1 px-2 h-6 rounded text-[11px] font-semibold active:scale-95 disabled:opacity-25 disabled:cursor-not-allowed flex-shrink-0 w-[68px]"
                style={{
                  background: isActive ? 'rgba(37,99,235,0.25)' : (hasSad ? '#EFF6FF' : '#F3F4F6'),
                  border: `1px solid ${isActive ? 'rgba(147,197,253,0.5)' : (hasSad ? '#93C5FD' : '#D1D5DB')}`,
                  color: isActive ? '#BFDBFE' : (hasSad ? '#2563EB' : '#9CA3AF'),
                }}
                title={hasSad ? "TTS — Buồn" : "Chưa upload ref audio Buồn"}>
                <span style={{ fontSize: 18, lineHeight: 1 }}>😭</span>
                Buồn
              </button>
            )
          })()}
          {(() => {
            const hasAngry = availableModes.includes('angry')
            return (
              <button onClick={e => onTTS(e, s, 'angry')} disabled={isTTSLoading || !hasAngry}
                className="sub-action-btn flex items-center justify-center gap-1 px-2 h-6 rounded text-[11px] font-semibold active:scale-95 disabled:opacity-25 disabled:cursor-not-allowed flex-shrink-0 w-[68px]"
                style={{
                  background: isActive ? 'rgba(220,38,38,0.25)' : (hasAngry ? '#FEF2F2' : '#F3F4F6'),
                  border: `1px solid ${isActive ? 'rgba(252,165,165,0.5)' : (hasAngry ? '#FCA5A5' : '#D1D5DB')}`,
                  color: isActive ? '#FECACA' : (hasAngry ? '#DC2626' : '#9CA3AF'),
                }}
                title={hasAngry ? "TTS — Tức giận" : "Chưa upload ref audio Tức giận"}>
                <span style={{ fontSize: 18, lineHeight: 1 }}>😡</span>
                Giận
              </button>
            )
          })()}
        </div>
      </div>
    </div>
  )
})

// ─── Main ──────────────────────────────────────────────────────────────────
export default function SubtitleList({ filter, filterNoChar, filterNoTTS, overlapSubIds, filterCharIds, chapters = [], onToggleChapter, filterChapterIds }: Props) {
  // PERF: selectors riêng cho từng field — KHÔNG destructure useStore()
  const subtitles  = useStore(s => s.subtitles)
  const characters = useStore(s => s.characters)
  const activeSubId = useStore(s => s.activeSubId)
  const selectedIds = useStore(s => s.selectedIds)
  // v3.3: project source_lang để biết có phải SRT Việt thuần (ẩn row TQ + tắt nút Dịch lại)
  const sourceLang = useStore(s => s.project?.source_lang)
  const isViOnly = sourceLang === 'vi'
  const toggleSelect    = useStore(s => s.toggleSelect)
  const updateSubtitle  = useStore(s => s.updateSubtitle)
  const deleteAudioStore = useStore(s => s.deleteAudio)
  const deleteSubStore  = useStore(s => s.deleteSubtitle)
  const setActiveSubId  = useStore(s => s.setActiveSubId)
  const project         = useStore(s => s.project)
  // v3: emotion voice flag từ project
  const emotionVoiceOn = !!project?.use_emotion_voice
  // v3: map character_id → available modes
  const voiceModesByChar = useStore(s => s.voiceModesByCharacter)

  // Queue state — show icon trên row
  const ttsQueueRunning = useStore(s => s.ttsQueueRunning)
  const ttsQueuePending = useStore(s => s.ttsQueuePending)
  const pendingSet = useMemo(() => new Set(ttsQueuePending), [ttsQueuePending])

  const parentRef = useRef<HTMLDivElement>(null)
  const [ttsLoadingId, setTtsLoadingId] = useState<number | null>(null)
  const [playingId, setPlayingId] = useState<number | null>(null)

  // v3.6: state retranslate hỗ trợ batch, mở 1-click → gọi AI luôn với
  // context_window từ ConfigPanel. Mỗi dòng có 2 checkbox v1/v2 độc lập
  // (tick = apply bản đó; cả 2 off = bỏ qua dòng). Cùng 1 dòng chỉ tick
  // được 1 trong 2 checkbox tại 1 thời điểm.
  type RTLine = {
    line_index: number
    subtitle_id: number
    original_text: string
    speaker_zh: string | null
    current_text: string
    text_v1: string
    text_v2: string | null
    emotion: string | null
    intensity: number | null
    /** null = không apply; 1 = apply v1; 2 = apply v2 */
    selected_variant: 1 | 2 | null
  }
  const [inlineRT, setInlineRT] = useState<{
    anchorSub: Subtitle           // dòng user bấm "Dịch lại"
    loading: boolean
    error: string
    results: RTLine[]             // sau khi AI trả về
  } | null>(null)

  // v3.6.2: ref + state cho scroll panel retranslate (wheel chậm + mũi tên).
  // PHẢI đặt SAU useState<inlineRT> vì useEffect dùng inlineRT làm dep.
  const rtBodyRef = useRef<HTMLDivElement>(null)
  const [rtScrollPos, setRtScrollPos] = useState({ top: 0, max: 0 })

  // Wheel chậm trong panel retranslate (0.4x default).
  // Dùng non-passive listener để preventDefault hoạt động.
  useEffect(() => {
    const el = rtBodyRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      // Chỉ xử lý wheel dọc; ctrl+wheel (zoom) thả qua native
      if (e.ctrlKey) return
      e.preventDefault()
      el.scrollTop += e.deltaY * 0.4
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [inlineRT?.results.length])  // re-attach khi list kết quả đổi

  // Track scroll position để disable mũi tên ở đầu/cuối
  useEffect(() => {
    const el = rtBodyRef.current
    if (!el) return
    const update = () => setRtScrollPos({
      top: el.scrollTop,
      max: el.scrollHeight - el.clientHeight,
    })
    update()
    el.addEventListener('scroll', update, { passive: true })
    return () => el.removeEventListener('scroll', update)
  }, [inlineRT?.results.length])

  const rtScrollBy = useCallback((delta: number) => {
    const el = rtBodyRef.current
    if (!el) return
    el.scrollBy({ top: delta, behavior: 'smooth' })
  }, [])

  /**
   * 1-click flow: bấm "Dịch lại" → gọi AI ngay với context_window từ config.
   * Default scope = "cụm context" (anchor ± context_window).
   */
  const handleRetranslate = useCallback(async (s: Subtitle) => {
    const config = loadConfig()
    const apiKey = getApiKey(config)
    if (!apiKey) {
      setInlineRT({
        anchorSub: s, loading: false, results: [],
        error: 'Chưa có API key. Vào trang Translate → Cấu hình.',
      })
      return
    }

    // Build scope: anchor ± ctxN (cap 5 lines total)
    const ctxN = getRetranslateContextWindow(config)
    const subs = useStore.getState().subtitles
    const anchorIdx = s.index
    let pool = subs.filter(x => x.index >= anchorIdx - ctxN && x.index <= anchorIdx + ctxN)
    if (pool.length > 5) {
      const anchorPos = pool.findIndex(x => x.id === s.id)
      const lo = Math.max(0, anchorPos - 2)
      const hi = Math.min(pool.length, lo + 5)
      pool = pool.slice(lo, hi)
    }
    if (!pool.length) pool = [s]

    setInlineRT({ anchorSub: s, loading: true, error: '', results: [] })

    try {
      const { translateApi } = await import('../api')
      if (pool.length === 1) {
        const res = await translateApi.retranslate(s.project_id, {
          subtitle_id: s.id,
          hint:        '',
          api_key:     apiKey,
          provider:    config.provider,
          model:       getRetranslateModel(config),
          thinking:    getRetranslateThinking(config),
          context_window: ctxN,
        })
        const line: RTLine = {
          line_index: s.index,
          subtitle_id: s.id,
          original_text: s.original_text || '',
          speaker_zh: s.speaker_zh || null,
          current_text: s.text || '',
          text_v1: res.new_text_v1 || '',
          text_v2: (res.new_text_v2 && res.new_text_v2 !== res.new_text_v1) ? res.new_text_v2 : null,
          emotion: (res as any).emotion || null,
          intensity: (res as any).intensity || null,
          selected_variant: null,
        }
        setInlineRT(r => r ? { ...r, loading: false, results: [line] } : null)
      } else {
        const res = await translateApi.retranslateBatch(s.project_id, {
          subtitle_ids: pool.map(t => t.id),
          hint:         '',
          api_key:      apiKey,
          provider:     config.provider,
          model:        getRetranslateModel(config),
          thinking:     getRetranslateThinking(config),
          context_window: ctxN,
        })
        const lines: RTLine[] = res.lines.map(l => {
          const original = pool.find(t => t.id === l.subtitle_id)
          return {
            line_index: l.line_index,
            subtitle_id: l.subtitle_id,
            original_text: original?.original_text || '',
            speaker_zh: original?.speaker_zh || null,
            current_text: original?.text || '',
            text_v1: l.text_v1,
            text_v2: l.text_v2,
            emotion: l.emotion,
            intensity: l.intensity,
            selected_variant: null,
          }
        })
        setInlineRT(r => r ? { ...r, loading: false, results: lines } : null)
      }
    } catch (err: any) {
      setInlineRT(r => r ? {
        ...r, loading: false,
        error: err?.response?.data?.detail || err?.message || 'Lỗi',
      } : null)
    }
  }, [])

  /**
   * Apply: chỉ áp dụng các dòng có selected_variant !== null.
   */
  const applyRetranslate = useCallback(async () => {
    if (!inlineRT || !inlineRT.results.length) return
    const toApply = inlineRT.results.filter(l => l.selected_variant !== null)
    if (!toApply.length) return

    try {
      for (const line of toApply) {
        const patch: any = {
          text_v1: line.text_v1,
          text_v2: line.text_v2,
          variant_selected: line.selected_variant,
        }
        const updated = await api.patch(`/subtitles/${line.subtitle_id}`, patch).then(r => r.data)
        updateSubtitle(line.subtitle_id, {
          text: updated.text,
          text_v1: updated.text_v1,
          text_v2: updated.text_v2,
          variant_selected: updated.variant_selected,
          cps_value: updated.cps_value,
        })
      }
      setInlineRT(null)
    } catch (err: any) {
      setInlineRT(r => r ? {
        ...r, error: err?.response?.data?.detail || err?.message || 'Lỗi khi áp dụng',
      } : null)
    }
  }, [inlineRT, updateSubtitle])

  /**
   * Toggle 1 checkbox v1/v2 cho 1 dòng.
   * Quy tắc: cùng 1 dòng chỉ tick 1 trong 2; tick lại cái đã active = bỏ chọn.
   */
  const toggleLineVariant = useCallback((subtitleId: number, variant: 1 | 2) => {
    setInlineRT(r => r ? {
      ...r,
      results: r.results.map(l => {
        if (l.subtitle_id !== subtitleId) return l
        // Tick cùng cái đang active → bỏ tích. Khác → đổi sang cái mới.
        return { ...l, selected_variant: l.selected_variant === variant ? null : variant }
      }),
    } : null)
  }, [])

  /** Gọi AI lại với cùng config (retry khi kết quả tệ). */
  const retryRetranslate = useCallback(() => {
    if (!inlineRT) return
    handleRetranslate(inlineRT.anchorSub)
  }, [inlineRT, handleRetranslate])

  // PERF: pub/sub thay setInterval(150ms)
  useEffect(() => subscribePlayingId(setPlayingId), [])

  // PERF: O(n log n) thay O(n²)
  const dupStartIds = useMemo(() => findDuplicateStarts(subtitles), [subtitles])

  // PERF: memo filter — không chạy lại mỗi render
  const visible = useMemo(() => {
    const f = filter.toLowerCase()
    // Pre-build chapter ranges nếu có filter chapter
    const chapterRanges: [number, number][] = (filterChapterIds && filterChapterIds.length > 0)
      ? chapters
          .filter(c => filterChapterIds.includes(c.id))
          .map(c => [c.start_sub_index, c.end_sub_index])
      : []
    const hasChapterFilter = chapterRanges.length > 0
    const hasCharFilter = filterCharIds && filterCharIds.length > 0
    return subtitles.filter(s => {
      if (f && !s.text.toLowerCase().includes(f) &&
          !(s.character?.name.toLowerCase().includes(f))) return false
      if (filterNoChar && s.character_id) return false
      if (filterNoTTS && s.tts_done) return false
      if (overlapSubIds && overlapSubIds.size > 0 && !overlapSubIds.has(s.id)) return false
      // Filter NV: nếu có lọc, chỉ giữ sub có character_id trong mảng
      if (hasCharFilter) {
        if (!s.character_id || !filterCharIds!.includes(s.character_id)) return false
      }
      // Filter chapter: chỉ giữ sub trong range của chapter đã chọn
      if (hasChapterFilter) {
        const inRange = chapterRanges.some(([lo, hi]) => s.index >= lo && s.index <= hi)
        if (!inRange) return false
      }
      return true
    })
  }, [subtitles, filter, filterNoChar, filterNoTTS, overlapSubIds, filterCharIds, filterChapterIds, chapters])

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

    // Khi có filter chapter: chỉ hiển thị các chapter được chọn
    const hasChapterFilter = filterChapterIds && filterChapterIds.length > 0
    const activeChapters = hasChapterFilter
      ? chapters.filter(c => filterChapterIds!.includes(c.id))
      : chapters

    // Sort chapters theo sort_order
    const sortedChapters = [...activeChapters].sort((a, b) => a.sort_order - b.sort_order)

    // Group visible subs theo chapter (theo `index` của sub)
    const result: Item[] = []
    const chapterRanges = sortedChapters.map(c => ({
      chapter: c,
      subs: visible.filter(s => s.index >= c.start_sub_index && s.index <= c.end_sub_index),
    }))
    // Subs ngoài tất cả chapter (nếu có) — đẩy vào mục "Chưa phân loại" cuối
    // Khi có filter chapter: KHÔNG hiển thị orphan (vì user chỉ muốn xem chapter đã chọn)
    const allChapterRanges = sortedChapters.map(c => [c.start_sub_index, c.end_sub_index] as [number, number])
    const orphanSubs = hasChapterFilter ? [] : visible.filter(s =>
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
  }, [visible, chapters, filterChapterIds])

  const HEADER_H = 44
  const SUB_H    = 88

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

  const handleTTS = useCallback(async (e: React.MouseEvent, s: Subtitle, forceMode?: string | null) => {
    e.stopPropagation()
    // Đang xử lý ở GPU thì bỏ qua, đợi xong sẽ có kết quả
    if (useStore.getState().ttsQueueRunning === s.id) return
    // Gọi /tts/generate → backend tự enqueue priority high (move lên đầu)
    try {
      const body: any = { subtitle_id: s.id }
      if (forceMode) body.force_voice_mode = forceMode
      await api.post('/tts/generate', body)
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

  // v3: override voice mode per-line
  const handleSetVoiceMode = useCallback(async (s: Subtitle, mode: string) => {
    const newMode = mode || null
    // Optimistic update
    updateSubtitle(s.id, { tts_voice_mode: newMode })
    try {
      await api.patch(`/subtitles/${s.id}`, { tts_voice_mode: newMode })
    } catch (err: any) {
      // Revert on error
      updateSubtitle(s.id, { tts_voice_mode: s.tts_voice_mode })
      alert('Lưu thất bại: ' + (err?.message || ''))
    }
  }, [updateSubtitle])

  return (
    <>
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
              onRetranslate={handleRetranslate}
              onSetVoiceMode={handleSetVoiceMode}
              emotionVoiceOn={emotionVoiceOn}
              availableModes={s.character_id ? (voiceModesByChar[s.character_id] || []) : []}
              isViOnly={isViOnly}
              top={vi.start}
              height={vi.size}
            />
          )
        })}
      </div>
    </div>
      {/* v3.6: Retranslate panel — 1-click, 2 checkbox v1/v2 độc lập */}
      {inlineRT && (() => {
        const tickedCount = inlineRT.results.filter(l => l.selected_variant !== null).length
        return (
        <div className="border-t border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/20 flex-shrink-0 max-h-[300px] flex flex-col">
          {/* Header — sticky */}
          <div className="flex items-center gap-2 px-3 py-1.5 border-b border-blue-100 dark:border-blue-900/50 bg-blue-50 dark:bg-blue-950/20">
            <span className="text-[11px] font-bold text-blue-600 dark:text-blue-400">
              ✨ Dịch lại #{inlineRT.anchorSub.index}
            </span>
            {inlineRT.anchorSub.original_text && (
              <span className="text-[10px] font-mono text-blue-400 dark:text-blue-500 truncate flex-1">
                {inlineRT.anchorSub.original_text}
              </span>
            )}
            {/* v3.6.2: mũi tên ▲ scroll lên 1 card */}
            {inlineRT.results.length > 1 && (
              <button
                onClick={() => rtScrollBy(-120)}
                disabled={rtScrollPos.top <= 0}
                title="Cuộn lên"
                className="text-blue-500 hover:text-blue-700 disabled:text-zinc-300 dark:disabled:text-zinc-600 disabled:cursor-not-allowed text-[14px] leading-none px-1.5 py-0.5 rounded hover:bg-blue-100 dark:hover:bg-blue-900/30 disabled:hover:bg-transparent">
                ▲
              </button>
            )}
            <button onClick={() => setInlineRT(null)}
              className="text-blue-400 hover:text-blue-600 text-[14px] leading-none px-1">×</button>
          </div>

          {/* Body — scroll vùng kết quả (wheel speed 0.4x) */}
          <div ref={rtBodyRef} className="overflow-y-auto flex-1 px-2.5 py-1.5">
            {/* Loading */}
            {inlineRT.loading && (
              <div className="flex items-center gap-2 text-[11px] text-blue-500 py-2">
                <div className="w-3 h-3 rounded-full border-2 border-blue-500 border-t-transparent animate-spin flex-shrink-0" />
                Đang dịch lại {Math.max(1, Math.min(5, /* visual hint */ 0))}...
              </div>
            )}

            {/* Error */}
            {inlineRT.error && (
              <div className="text-[11px] text-red-500 py-1">❌ {inlineRT.error}</div>
            )}

            {/* Results */}
            {!inlineRT.loading && inlineRT.results.length > 0 && (
              <div className="flex flex-col gap-1.5">
                {inlineRT.results.map(line => {
                  const isAnchor = line.subtitle_id === inlineRT.anchorSub.id
                  const v1Active = line.selected_variant === 1
                  const v2Active = line.selected_variant === 2
                  return (
                    <div key={line.subtitle_id}
                      className={`rounded-md border px-2 py-1.5 ${
                        isAnchor
                          ? 'border-blue-400 bg-blue-100/40 dark:bg-blue-900/20'
                          : 'border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800'
                      }`}>
                      {/* Header per-line — 1 dòng gọn */}
                      <div className="flex items-center gap-1.5 mb-1">
                        <span className={`text-[10px] font-bold ${
                          isAnchor ? 'text-blue-600 dark:text-blue-400' : 'text-zinc-500'
                        }`}>
                          #{line.line_index}{isAnchor && '⭐'}
                        </span>
                        {line.speaker_zh && (
                          <span className="text-[10px] text-zinc-400">{line.speaker_zh}</span>
                        )}
                        <span className="text-[10px] text-zinc-400 truncate flex-1">
                          Hiện tại: {line.current_text || '(chưa có)'}
                        </span>
                      </div>
                      {/* v1 + v2 checkboxes (mutually exclusive, cả 2 off cũng OK) */}
                      <div className="flex flex-col gap-0.5">
                        <label
                          className={`flex items-start gap-1.5 px-1.5 py-1 rounded cursor-pointer text-[12px] transition-all ${
                            v1Active
                              ? 'bg-blue-100 dark:bg-blue-900/40 ring-1 ring-blue-400'
                              : 'hover:bg-zinc-100 dark:hover:bg-zinc-700/50'
                          }`}>
                          <input type="checkbox"
                            checked={v1Active}
                            onChange={() => toggleLineVariant(line.subtitle_id, 1)}
                            className="w-3.5 h-3.5 mt-0.5 flex-shrink-0"
                          />
                          <div className="flex-1 min-w-0">
                            <span className="text-[11px] text-zinc-400 mr-1">v1·sát</span>
                            <span className="text-[12px] text-zinc-800 dark:text-zinc-100">
                              {line.text_v1 || '(rỗng)'}
                            </span>
                          </div>
                        </label>
                        {line.text_v2 && (
                          <label
                            className={`flex items-start gap-1.5 px-1.5 py-1 rounded cursor-pointer text-[12px] transition-all ${
                              v2Active
                                ? 'bg-blue-100 dark:bg-blue-900/40 ring-1 ring-blue-400'
                                : 'hover:bg-zinc-100 dark:hover:bg-zinc-700/50'
                            }`}>
                            <input type="checkbox"
                              checked={v2Active}
                              onChange={() => toggleLineVariant(line.subtitle_id, 2)}
                              className="w-3.5 h-3.5 mt-0.5 flex-shrink-0"
                            />
                            <div className="flex-1 min-w-0">
                              <span className="text-[11px] text-zinc-400 mr-1">v2·thoát</span>
                              <span className="text-[12px] text-zinc-800 dark:text-zinc-100">
                                {line.text_v2}
                              </span>
                            </div>
                          </label>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>

          {/* Footer — actions */}
          {!inlineRT.loading && inlineRT.results.length > 0 && (
            <div className="flex gap-2 px-3 py-1.5 border-t border-blue-100 dark:border-blue-900/50 bg-blue-50 dark:bg-blue-950/20">
              {/* v3.6.2: mũi tên ▼ scroll xuống 1 card */}
              {inlineRT.results.length > 1 && (
                <button
                  onClick={() => rtScrollBy(120)}
                  disabled={rtScrollPos.top >= rtScrollPos.max - 1}
                  title="Cuộn xuống"
                  className="text-blue-500 hover:text-blue-700 disabled:text-zinc-300 dark:disabled:text-zinc-600 disabled:cursor-not-allowed text-[14px] leading-none px-1.5 py-0.5 rounded hover:bg-blue-100 dark:hover:bg-blue-900/30 disabled:hover:bg-transparent">
                  ▼
                </button>
              )}
              <button onClick={() => setInlineRT(null)}
                className="btn text-[11px] px-2.5 py-0.5">Huỷ</button>
              <button
                onClick={applyRetranslate}
                disabled={tickedCount === 0}
                className="btn-primary text-[11px] px-2.5 py-0.5 disabled:opacity-50 disabled:cursor-not-allowed">
                ✓ Áp dụng {tickedCount} dòng
              </button>
              <button
                onClick={retryRetranslate}
                className="btn text-[11px] px-2.5 py-0.5 text-blue-500 border-blue-200 dark:border-blue-800 ml-auto">
                🔄 Thử lại
              </button>
            </div>
          )}
        </div>
        )
      })()}
    </>
  )
}