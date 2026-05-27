/**
 * SubtitlesView — danh sách subtitles theo phong cách giống Editor's SubtitleList:
 *   - Col 1: index + mic icon
 *   - Col 2: color bar
 *   - Col 3 (main): time + character badge | ZH (gốc) | VI (dịch, click để edit)
 *
 * Khác biệt với Editor:
 *   - Không có TTS / delete (đây là view dịch, không phải audio)
 *   - Click vào VI → edit inline (textarea), Esc hủy, Ctrl+Enter lưu
 *   - Có thêm filter (search, only-review, over-CPS, speaker)
 *   - Có badge cảm xúc + CPS
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import api, { translateApi } from '../../api'

interface SubRow {
  id: number
  project_id: number
  index: number
  start_time: number
  end_time: number
  text: string
  text_v1?: string | null
  text_v2?: string | null
  variant_selected?: 1 | 2
  original_text: string | null
  speaker_zh: string | null
  speaker_slot?: string | null   // v4.3: slot cho lồng tiếng (M/F/NAM_CHINH...)
  character: { id: number; name: string; color?: string } | null
  emotion: string | null
  intensity: number
  cps_value: number | null
  needs_review: boolean
  review_reason: string
  is_hook: boolean
  tts_done?: boolean
}

const EMOTION_BADGE: Record<string, { label: string; color: string }> = {
  neutral:     { label: 'BT',     color: '#6B7280' },
  happy:       { label: 'Vui',    color: '#CA8A04' },
  sad:         { label: 'Buồn',   color: '#2563EB' },
  angry:       { label: 'Giận',   color: '#DC2626' },
  cold:        { label: 'Lạnh',   color: '#475569' },
  tense:       { label: 'Căng',   color: '#EA580C' },
  intimate:    { label: 'Thân',   color: '#DB2777' },
  fearful:     { label: 'Sợ',     color: '#7C3AED' },
  sarcastic:   { label: 'Mỉa',    color: '#B45309' },
  shocked:     { label: 'Sốc',    color: '#0891B2' },
  determined:  { label: 'Quyết',  color: '#059669' },
  regretful:   { label: 'Hối',    color: '#BE123C' },
  humorous:    { label: 'Hài',    color: '#65A30D' },
  threatening: { label: 'Đe dọa', color: '#991B1B' },
}

function fmt(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`
}

function cpsColor(cps: number | null): string {
  if (!cps) return '#9CA3AF'
  if (cps > 22) return '#DC2626'
  if (cps > 18) return '#D97706'
  if (cps > 14) return '#6B7280'
  return '#059669'
}

// v4.3: Map slot key → label + màu (cho badge)
const SLOT_BADGE: Record<string, { label: string; color: string; bg: string }> = {
  // Mode SIMPLE
  M: { label: 'Nam', color: '#1D4ED8', bg: '#DBEAFE' },
  F: { label: 'Nữ', color: '#BE185D', bg: '#FCE7F3' },
  // Mode MEDIUM
  NAM_CHINH:     { label: 'Nam chính',     color: '#1E3A8A', bg: '#DBEAFE' },
  NU_CHINH:      { label: 'Nữ chính',      color: '#9D174D', bg: '#FCE7F3' },
  PHAN_DIEN_NAM: { label: 'P.diện nam',    color: '#7C2D12', bg: '#FED7AA' },
  PHAN_DIEN_NU:  { label: 'P.diện nữ',     color: '#86198F', bg: '#F5D0FE' },
  NAM_PHU:       { label: 'Nam phụ',       color: '#0E7490', bg: '#CFFAFE' },
  NU_PHU:        { label: 'Nữ phụ',        color: '#A16207', bg: '#FEF3C7' },
  NARRATION:     { label: 'Voice-over',    color: '#374151', bg: '#E5E7EB' },
}

/** v4.3: Trả về speaker key/label hiển thị cho 1 sub.
 *  Ưu tiên: speaker_slot > character.name > speaker_zh */
function getSpeakerDisplay(sub: { speaker_slot?: string | null; character?: any; speaker_zh?: string | null }):
  { key: string; label: string; color: string; bg: string } | null {
  if (sub.speaker_slot && SLOT_BADGE[sub.speaker_slot]) {
    const b = SLOT_BADGE[sub.speaker_slot]
    return { key: sub.speaker_slot, label: b.label, color: b.color, bg: b.bg }
  }
  if (sub.character?.name) {
    const c = sub.character.color || '#6B7280'
    return { key: sub.character.name, label: sub.character.name, color: c, bg: c + '22' }
  }
  if (sub.speaker_zh) {
    return { key: sub.speaker_zh, label: sub.speaker_zh, color: '#6B7280', bg: '#F3F4F6' }
  }
  return null
}

// ─── Mic icon (giống Editor) ────────────────────────────────────────────────
function MicIcon({ active }: { active: boolean }) {
  return (
    <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
      <rect x="4.5" y="1.5" width="3" height="6" rx="1.5"
            fill={active ? '#10B981' : 'none'}
            stroke={active ? '#10B981' : '#9CA3AF'} strokeWidth="1.2"/>
      <path d="M3 6.5a3 3 0 0 0 6 0M6 9.5v1.5"
            stroke={active ? '#10B981' : '#9CA3AF'} strokeWidth="1.2" strokeLinecap="round"/>
    </svg>
  )
}

// ─── Main ───────────────────────────────────────────────────────────────────
export default function SubtitlesView({ projectId }: { projectId: number }) {
  const [subs, setSubs] = useState<SubRow[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeId, setActiveId] = useState<number | null>(null)

  // Filters
  const [search, setSearch] = useState('')
  const [onlyReview, setOnlyReview] = useState(false)
  const [onlyOverCps, setOnlyOverCps] = useState(false)
  const [speakerFilter, setSpeakerFilter] = useState<string>('all')

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    api.get<SubRow[]>(`/subtitles/project/${projectId}`)
      .then(r => { if (!cancelled) setSubs(r.data) })
      .catch(e => { if (!cancelled) setError(e?.message || 'Load failed') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [projectId])

  // Listen variant-changed event để reload sub đó (cập nhật text active từ server)
  useEffect(() => {
    function onVariantChanged(e: Event) {
      const detail = (e as CustomEvent).detail as { id: number; variant: 1 | 2 }
      if (!detail) return
      api.get<SubRow>(`/subtitles/${detail.id}`).then(r => {
        setSubs(prev => prev.map(s => s.id === detail.id ? { ...s, ...r.data } : s))
      }).catch(() => {
        // Fallback: re-fetch all
        api.get<SubRow[]>(`/subtitles/project/${projectId}`).then(r => setSubs(r.data))
      })
    }
    // Reload toàn bộ sau khi Stage 0 chuẩn hóa (text gốc thay đổi, có dòng bị xóa)
    function onStage0Done() {
      api.get<SubRow[]>(`/subtitles/project/${projectId}`)
        .then(r => setSubs(r.data))
        .catch(() => {})
    }
    window.addEventListener('subtitle-variant-changed', onVariantChanged)
    window.addEventListener('stage0-done', onStage0Done)
    return () => {
      window.removeEventListener('subtitle-variant-changed', onVariantChanged)
      window.removeEventListener('stage0-done', onStage0Done)
    }
  }, [projectId])

  const speakers = useMemo(() => {
    // v4.3: list các key speaker từ slot/character/zh
    const set = new Set<string>()
    for (const s of subs) {
      const disp = getSpeakerDisplay(s)
      if (disp) set.add(disp.key)
    }
    // Slot keys ưu tiên đặt trước (theo thứ tự cố định), sau đó character/zh sort tên
    const slotOrder = ['M', 'F', 'NAM_CHINH', 'NU_CHINH', 'PHAN_DIEN_NAM',
                       'PHAN_DIEN_NU', 'NAM_PHU', 'NU_PHU', 'NARRATION']
    const slots = slotOrder.filter(k => set.has(k))
    const others = Array.from(set).filter(k => !slotOrder.includes(k)).sort()
    return [...slots, ...others]
  }, [subs])

  const filtered = useMemo(() => {
    let arr = subs
    if (onlyReview) arr = arr.filter(s => s.needs_review)
    if (onlyOverCps) arr = arr.filter(s => (s.cps_value ?? 0) > 18)
    if (speakerFilter !== 'all') {
      arr = arr.filter(s => {
        const disp = getSpeakerDisplay(s)
        return disp?.key === speakerFilter
      })
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      arr = arr.filter(s =>
        (s.text || '').toLowerCase().includes(q) ||
        (s.original_text || '').toLowerCase().includes(q) ||
        (s.character?.name || '').toLowerCase().includes(q) ||
        (s.speaker_zh || '').toLowerCase().includes(q) ||
        (s.speaker_slot || '').toLowerCase().includes(q)
      )
    }
    return arr
  }, [subs, onlyReview, onlyOverCps, speakerFilter, search])

  const stats = useMemo(() => {
    const total = subs.length
    const reviewCount = subs.filter(s => s.needs_review).length
    const overCpsCount = subs.filter(s => (s.cps_value ?? 0) > 18).length
    const cps = subs.map(s => s.cps_value).filter((x): x is number => !!x)
    const avgCps = cps.length ? cps.reduce((a, b) => a + b, 0) / cps.length : 0
    return { total, reviewCount, overCpsCount, avgCps }
  }, [subs])

  const updateSubtitle = async (id: number, newText: string) => {
    setSubs(prev => prev.map(s => {
      if (s.id !== id) return s
      const duration = s.end_time - s.start_time
      const cps = duration > 0 ? newText.trim().length / duration : 0
      return { ...s, text: newText, cps_value: Math.round(cps * 100) / 100 }
    }))
    try {
      await api.patch(`/subtitles/${id}`, { text: newText })
    } catch (e: any) {
      console.error('[SubtitlesView] save failed', e)
      alert('Lưu thất bại. Refresh để xem trạng thái mới nhất.')
    }
  }

  const copyAllVi = async () => {
    const text = filtered.map(s => s.text).join('\n')
    try { await navigator.clipboard.writeText(text) } catch {}
  }
  const copyAsSrt = async () => {
    const fmt2 = (sec: number) => {
      const h = Math.floor(sec / 3600)
      const m = Math.floor((sec % 3600) / 60)
      const s = sec % 60
      const ms = Math.floor((s - Math.floor(s)) * 1000)
      return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(Math.floor(s)).padStart(2,'0')},${String(ms).padStart(3,'0')}`
    }
    const text = filtered.map((s, i) =>
      `${i + 1}\n${fmt2(s.start_time)} --> ${fmt2(s.end_time)}\n${s.text || s.original_text || ''}\n`
    ).join('\n')
    try { await navigator.clipboard.writeText(text) } catch {}
  }

  if (loading) return <div className="p-12 text-center text-zinc-500 animate-pulse">Đang tải subtitles...</div>
  if (error) return <div className="p-12 text-center text-red-500">Lỗi: {error}</div>
  if (subs.length === 0) return <div className="p-12 text-center text-zinc-500">Project chưa có subtitle nào.</div>

  return (
    <div className="h-full flex flex-col bg-[#FAFAF8] dark:bg-zinc-900">
      {/* TOOLBAR — sticky */}
      <div className="sticky top-0 z-10 bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800 px-4 py-2.5">
        {/* Stats row */}
        <div className="flex items-center gap-3 mb-2 text-[11px]">
          <span className="font-mono">
            <span className="text-zinc-800 dark:text-zinc-100 font-semibold">{filtered.length}</span>
            <span className="text-zinc-400"> / {stats.total}</span>
          </span>
          <Divider />
          <span className="text-zinc-500">
            avg CPS <strong className="text-zinc-700 dark:text-zinc-300 tabular-nums">{stats.avgCps.toFixed(1)}</strong>
          </span>
          {stats.reviewCount > 0 && (
            <span className="text-amber-700 dark:text-amber-400 font-medium">⚠ {stats.reviewCount} review</span>
          )}
          {stats.overCpsCount > 0 && (
            <span className="text-red-700 dark:text-red-400 font-medium">⚡ {stats.overCpsCount} over CPS</span>
          )}
          <div className="flex-1" />
          <button onClick={copyAllVi} className="text-[11px] px-2.5 py-1 rounded bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-300">📋 Copy text</button>
          <button onClick={copyAsSrt} className="text-[11px] px-2.5 py-1 rounded bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-300">📋 Copy SRT</button>
        </div>

        {/* Filters row */}
        <div className="flex items-center gap-2 flex-wrap">
          <div className="relative flex-1 min-w-[260px] max-w-md">
            <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400 text-[12px] pointer-events-none">🔍</span>
            <input
              type="text"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Tìm trong nội dung (Trung/Việt/speaker)..."
              className="w-full pl-8 pr-2.5 py-1 text-[12px] rounded border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 focus:bg-white dark:focus:bg-zinc-950 focus:outline-none focus:ring-1 focus:ring-blue-500/40"
            />
          </div>
          <select
            value={speakerFilter}
            onChange={e => setSpeakerFilter(e.target.value)}
            className="text-[12px] px-2 py-1 rounded border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 focus:outline-none"
          >
            <option value="all">Tất cả speaker</option>
            {speakers.map(s => {
              const slotInfo = SLOT_BADGE[s]
              const label = slotInfo ? `${slotInfo.label} (${s})` : s
              return <option key={s} value={s}>{label}</option>
            })}
          </select>
          <Toggle checked={onlyReview} onChange={setOnlyReview} label="⚠ Review" warning />
          <Toggle checked={onlyOverCps} onChange={setOnlyOverCps} label="⚡ Over CPS" danger />
        </div>
      </div>

      {/* LIST — virtual không cần vì max ~2000 dòng */}
      <div className="flex-1 overflow-auto">
        {filtered.length === 0 ? (
          <div className="text-center py-12 text-zinc-400 text-sm">Không có dòng nào khớp bộ lọc.</div>
        ) : (
          <div>
            {filtered.map(s => (
              <SubRowComponent
                key={s.id}
                sub={s}
                isActive={s.id === activeId}
                onActivate={() => setActiveId(s.id)}
                onSave={text => updateSubtitle(s.id, text)}
                onBlurAll={() => setActiveId(null)}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Subtitle Row — Editor style ────────────────────────────────────────────

function SubRowComponent({ sub, isActive, onActivate, onSave, onBlurAll }: {
  sub: SubRow
  isActive: boolean
  onActivate: () => void
  onSave: (text: string) => void | Promise<void>
  onBlurAll: () => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(sub.text || '')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (!editing) setDraft(sub.text || '')
  }, [sub.text, editing])

  useEffect(() => {
    if (editing && textareaRef.current) {
      const ta = textareaRef.current
      ta.focus()
      ta.setSelectionRange(ta.value.length, ta.value.length)
      ta.style.height = 'auto'
      ta.style.height = ta.scrollHeight + 'px'
    }
  }, [editing])

  const handleSave = async () => {
    const trimmed = draft.trim()
    if (trimmed && trimmed !== sub.text) {
      await onSave(trimmed)
    }
    setEditing(false)
    onBlurAll()
  }

  const handleCancel = () => {
    setDraft(sub.text || '')
    setEditing(false)
    onBlurAll()
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Escape') {
      e.preventDefault()
      handleCancel()
    } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      handleSave()
    }
  }

  const char = sub.character
  const speakerDisplay = getSpeakerDisplay(sub)
  const emo = sub.emotion ? EMOTION_BADGE[sub.emotion] : null

  // Bg row (giống Editor)
  let rowBg = '#FAFAF8'
  let rowBorder = '#E8E6E0'
  if (isActive)            { rowBg = '#EFF6FF'; rowBorder = '#BFDBFE' }
  else if (sub.needs_review){ rowBg = '#FFFBEB'; rowBorder = '#FDE68A' }
  else if (!speakerDisplay) { rowBg = '#FFFBF0'; rowBorder = '#E8E6E0' }

  return (
    <div
      className="flex items-stretch cursor-pointer group transition-colors"
      style={{
        background: rowBg,
        borderBottom: `1px solid ${rowBorder}`,
      }}
      onClick={() => {
        if (!editing) {
          onActivate()
          setEditing(true)
        }
      }}
    >
      {/* Col 1: index + mic */}
      <div className="w-9 flex-shrink-0 flex flex-col items-center justify-center gap-1 py-2 select-none">
        <span style={{ fontSize: 11, fontFamily: 'monospace', color: '#9CA3AF', fontWeight: 600 }}>
          {sub.index}
        </span>
        <MicIcon active={!!sub.tts_done} />
      </div>

      {/* Col 2: color bar */}
      <div className="w-[3px] flex-shrink-0 my-2 rounded-full"
           style={{ background: sub.needs_review ? '#F59E0B' : char?.color || '#D1D5DB' }} />

      {/* Col 3: main content */}
      <div className="flex-1 min-w-0 flex flex-col justify-center py-1.5 px-2.5" style={{ gap: 3 }}>

        {/* Row 1: time + character badge + emotion + CPS */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span style={{ fontSize: 10, fontFamily: 'monospace', fontWeight: 700, color: '#6B7280', whiteSpace: 'nowrap' }}>
            {fmt(sub.start_time)}
          </span>
          <span style={{ fontSize: 9, color: '#D1D5DB' }}>→</span>
          <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#9CA3AF', whiteSpace: 'nowrap' }}>
            {fmt(sub.end_time)}
          </span>
          <span style={{ fontSize: 10, color: '#D1D5DB' }}>·</span>
          <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#9CA3AF' }}>
            {(sub.end_time - sub.start_time).toFixed(1)}s
          </span>

          {/* speaker badge */}
          {speakerDisplay ? (
            <span style={{
              fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
              background: speakerDisplay.bg, color: speakerDisplay.color,
              whiteSpace: 'nowrap', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis',
            }}>
              {speakerDisplay.label}
            </span>
          ) : (
            <span style={{
              fontSize: 10, fontWeight: 600, padding: '1px 6px', borderRadius: 4,
              background: '#FEF3C7', color: '#92400E',
            }}>
              chưa gán
            </span>
          )}

          {/* emotion badge */}
          {emo && (
            <span style={{
              fontSize: 10, fontWeight: 600, padding: '1px 5px', borderRadius: 4,
              background: emo.color + '15', color: emo.color, whiteSpace: 'nowrap',
            }}>
              {emo.label}{sub.intensity > 5 && <span style={{ opacity: 0.6 }}> ·{sub.intensity}</span>}
            </span>
          )}

          <div className="flex-1" />

          {/* CPS */}
          {sub.cps_value != null && (
            <span style={{
              fontSize: 10, fontFamily: 'monospace', fontWeight: 600,
              color: cpsColor(sub.cps_value),
            }}>
              CPS {sub.cps_value.toFixed(1)}
            </span>
          )}
          {sub.is_hook && <span title="Hook line" style={{ fontSize: 11 }}>🎣</span>}
          {sub.needs_review && (
            <span title={sub.review_reason || 'Cần review'} style={{ fontSize: 11 }}>⚠</span>
          )}
        </div>

        {/* Row 2: ZH (tiếng Trung) — chỉ khi có */}
        {sub.original_text && (
          <span style={{
            fontSize: 11, color: '#9CA3AF',
            fontFamily: 'system-ui,sans-serif', letterSpacing: '0.02em',
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block',
          }}>
            {sub.original_text}
          </span>
        )}

        {/* Row 3: VI bản dịch — click để edit */}
        {editing ? (
          <div onClick={e => e.stopPropagation()} className="flex flex-col gap-1.5 py-0.5">
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={e => {
                setDraft(e.target.value)
                e.target.style.height = 'auto'
                e.target.style.height = e.target.scrollHeight + 'px'
              }}
              onKeyDown={handleKeyDown}
              className="w-full text-[14px] leading-snug resize-none bg-white dark:bg-zinc-950 border border-blue-300 dark:border-blue-700 rounded px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              style={{ fontSize: 14, fontWeight: 500, color: '#1F2937', lineHeight: 1.4 }}
              rows={1}
            />
            <div className="flex items-center gap-1.5 text-[10px] text-zinc-500">
              <button
                onClick={handleSave}
                className="px-2 py-0.5 rounded bg-blue-500 hover:bg-blue-600 text-white font-medium"
              >
                ✓ Lưu
              </button>
              <button
                onClick={handleCancel}
                className="px-2 py-0.5 rounded bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700"
              >
                ✕ Hủy
              </button>
              <span className="text-zinc-400 ml-1">
                {draft.length} chars · {(sub.end_time - sub.start_time) > 0
                  ? (draft.length / (sub.end_time - sub.start_time)).toFixed(1)
                  : '—'} CPS
              </span>
              <span className="ml-auto text-zinc-400 text-[10px]">
                <kbd className="px-1 rounded bg-zinc-100 dark:bg-zinc-800">⌘+Enter</kbd> lưu ·
                <kbd className="px-1 rounded bg-zinc-100 dark:bg-zinc-800 ml-0.5">Esc</kbd> hủy
              </span>
            </div>
          </div>
        ) : (
          (() => {
            const v1 = sub.text_v1 || sub.text || ''
            const v2 = sub.text_v2 || ''
            const hasV2 = !!v2 && v2 !== v1
            const sel = sub.variant_selected || 1

            if (!hasV2) {
              // Chỉ 1 bản — render đơn giản
              // Chỉ coi là "đã dịch" khi text khác original_text (TQ) và khác rỗng
              const displayText = sub.text && sub.text !== sub.original_text ? sub.text : ''
              return (
                <span style={{
                  fontSize: 14, lineHeight: 1.4,
                  color: '#1F2937',
                  fontWeight: 500,
                  overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', display: 'block',
                }}>
                  {displayText || <span style={{ fontStyle: 'italic', opacity: 0.4, fontSize: 13 }}>Chưa dịch — click để thêm</span>}
                </span>
              )
            }

            // Có 2 bản → hiển thị compact bản đang active + bản còn lại nhỏ phía dưới
            const switchTo = async (v: 1 | 2) => {
              try {
                await translateApi.selectVariant(sub.project_id, sub.id, v)
                // Reload sub trong list (parent quản lý)
                window.dispatchEvent(new CustomEvent('subtitle-variant-changed', { detail: { id: sub.id, variant: v } }))
              } catch (e) { console.warn(e) }
            }

            return (
              <div className="flex flex-col gap-0.5" onClick={e => e.stopPropagation()}>
                {/* Bản active — lớn */}
                <div className="flex items-baseline gap-1.5">
                  <span style={{
                    fontSize: 9, fontWeight: 700, padding: '0px 4px', borderRadius: 3,
                    background: sel === 1 ? '#DBEAFE' : '#F3E8FF',
                    color: sel === 1 ? '#1D4ED8' : '#7E22CE',
                    flexShrink: 0,
                  }}>
                    v{sel}
                  </span>
                  <span style={{
                    fontSize: 14, lineHeight: 1.35, color: '#1F2937', fontWeight: 500,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {sel === 2 ? v2 : v1}
                  </span>
                </div>
                {/* Bản còn lại — nhỏ, click để switch */}
                <div className="flex items-baseline gap-1.5 opacity-60 hover:opacity-100 transition-opacity cursor-pointer"
                     onClick={() => switchTo(sel === 1 ? 2 : 1)}
                     title="Click để chuyển sang bản này">
                  <span style={{
                    fontSize: 9, fontWeight: 600, padding: '0px 4px', borderRadius: 3,
                    background: sel === 1 ? '#F3E8FF' : '#DBEAFE',
                    color: sel === 1 ? '#7E22CE' : '#1D4ED8',
                    flexShrink: 0,
                  }}>
                    v{sel === 1 ? 2 : 1}
                  </span>
                  <span style={{
                    fontSize: 12, lineHeight: 1.3, color: '#6B7280', fontStyle: 'italic',
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>
                    {sel === 1 ? v2 : v1}
                  </span>
                </div>
              </div>
            )
          })()
        )}

        {/* Review reason (chỉ khi không editing) */}
        {sub.needs_review && sub.review_reason && !editing && (
          <span style={{ fontSize: 10, color: '#B45309', fontStyle: 'italic' }}>
            ↳ {sub.review_reason}
          </span>
        )}
      </div>
    </div>
  )
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function Divider() {
  return <span className="w-px h-3 bg-zinc-300 dark:bg-zinc-700 select-none" />
}

function Toggle({ checked, onChange, label, warning, danger }: {
  checked: boolean
  onChange: (v: boolean) => void
  label: string
  warning?: boolean
  danger?: boolean
}) {
  const activeClass = danger
    ? 'bg-red-100 text-red-700 border-red-300 dark:bg-red-900/30 dark:text-red-300 dark:border-red-700'
    : warning
    ? 'bg-amber-100 text-amber-700 border-amber-300 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-700'
    : 'bg-blue-100 text-blue-700 border-blue-300 dark:bg-blue-900/30 dark:text-blue-300 dark:border-blue-700'
  return (
    <button
      onClick={() => onChange(!checked)}
      className={`text-[11px] px-2 py-1 rounded border transition-colors ${
        checked
          ? activeClass
          : 'bg-zinc-50 text-zinc-600 border-zinc-200 hover:bg-zinc-100 dark:bg-zinc-900 dark:text-zinc-400 dark:border-zinc-700 dark:hover:bg-zinc-800'
      }`}
    >
      {label}
    </button>
  )
}