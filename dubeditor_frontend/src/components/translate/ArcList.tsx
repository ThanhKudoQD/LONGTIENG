/**
 * ArcList — v4.4 (replace cho SceneList/ChunkList legacy)
 *
 * Hiển thị bản dịch nhóm theo Arc (từ Bible) thay vì theo Chunk.
 * Workflow v4.x không dùng DB chunks/scenes nữa — chỉ dùng arcs.
 *
 * Mỗi dòng thoại hiện CẢ v1 + v2 SONG SONG để user so sánh khi review.
 *
 * Cấu trúc:
 *   ArcList
 *    ├── Filter bar (arc selector + speaker filter + search)
 *    └── Arc cards (1 card/arc)
 *         ├── Header: title + tone + summary + line range
 *         └── Lines (mỗi dòng):
 *              ├── index + time + speaker badge + CPS
 *              ├── original_text (Trung)
 *              └── [v1 sát nghĩa] [v2 thoát ý]  ← song song
 */
import React, { useEffect, useMemo, useState } from 'react'
import api from '../../api'
import type { StoryArc, Subtitle } from '../../types'
import { ARC_TONE_LABELS } from '../../types'

interface Props {
  projectId: number
  arcs: StoryArc[]
}

// ─── Slot badge (giống SubtitlesView) ────────────────────────────────────────

const SLOT_BADGE: Record<string, { label: string; color: string; bg: string }> = {
  M: { label: 'Nam', color: '#1D4ED8', bg: '#DBEAFE' },
  F: { label: 'Nữ', color: '#BE185D', bg: '#FCE7F3' },
  NAM_CHINH:     { label: 'Nam chính',     color: '#1E3A8A', bg: '#DBEAFE' },
  NU_CHINH:      { label: 'Nữ chính',      color: '#9D174D', bg: '#FCE7F3' },
  PHAN_DIEN_NAM: { label: 'P.diện nam',    color: '#7C2D12', bg: '#FED7AA' },
  PHAN_DIEN_NU:  { label: 'P.diện nữ',     color: '#86198F', bg: '#F5D0FE' },
  NAM_PHU:       { label: 'Nam phụ',       color: '#0E7490', bg: '#CFFAFE' },
  NU_PHU:        { label: 'Nữ phụ',        color: '#A16207', bg: '#FEF3C7' },
  NARRATION:     { label: 'Voice-over',    color: '#374151', bg: '#E5E7EB' },
}

function getSpeakerDisplay(s: any): { key: string; label: string; color: string; bg: string } | null {
  if (s.speaker_slot && SLOT_BADGE[s.speaker_slot]) {
    const b = SLOT_BADGE[s.speaker_slot]
    return { key: s.speaker_slot, label: b.label, color: b.color, bg: b.bg }
  }
  if (s.character?.name) {
    const c = s.character.color || '#6B7280'
    return { key: s.character.name, label: s.character.name, color: c, bg: c + '22' }
  }
  if (s.speaker_zh) {
    return { key: s.speaker_zh, label: s.speaker_zh, color: '#6B7280', bg: '#F3F4F6' }
  }
  return null
}

// ─── Time format ─────────────────────────────────────────────────────────────

function fmt(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = sec % 60
  return `${String(m).padStart(2, '0')}:${s.toFixed(1).padStart(4, '0')}`
}

function cpsColor(cps: number | null | undefined): string {
  if (!cps) return '#9CA3AF'
  if (cps > 22) return '#DC2626'
  if (cps > 18) return '#D97706'
  if (cps > 14) return '#6B7280'
  return '#059669'
}

// ─── Main ────────────────────────────────────────────────────────────────────

export default function ArcList({ projectId, arcs }: Props) {
  const [subs, setSubs] = useState<Subtitle[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [search, setSearch] = useState('')
  const [speakerFilter, setSpeakerFilter] = useState<string>('all')
  const [selectedArc, setSelectedArc] = useState<number | null>(null)
  const [collapsedArcs, setCollapsedArcs] = useState<Set<number>>(new Set())

  useEffect(() => {
    setLoading(true)
    api.get<Subtitle[]>(`/subtitles/project/${projectId}`)
      .then(r => {
        setSubs(r.data || [])
        setError(null)
      })
      .catch(e => setError(e?.message || 'Load subtitles failed'))
      .finally(() => setLoading(false))
  }, [projectId])

  // Nhóm subs theo arc dựa trên subtitle.index ∈ [arc.start_line, arc.end_line]
  const subsByArc = useMemo(() => {
    const map = new Map<number, Subtitle[]>()
    if (!arcs.length || !subs.length) return map

    const arcsSorted = [...arcs].sort((a, b) => a.start_line - b.start_line)
    for (const arc of arcsSorted) {
      map.set(arc.arc_index, [])
    }

    for (const sub of subs) {
      const arc = arcsSorted.find(a => sub.index >= a.start_line && sub.index <= a.end_line)
      if (arc) {
        map.get(arc.arc_index)!.push(sub)
      }
    }
    return map
  }, [arcs, subs])

  // List speakers từ subs
  const speakers = useMemo(() => {
    const set = new Set<string>()
    for (const s of subs) {
      const d = getSpeakerDisplay(s)
      if (d) set.add(d.key)
    }
    const slotOrder = ['M', 'F', 'NAM_CHINH', 'NU_CHINH', 'PHAN_DIEN_NAM',
                       'PHAN_DIEN_NU', 'NAM_PHU', 'NU_PHU', 'NARRATION']
    const slots = slotOrder.filter(k => set.has(k))
    const others = Array.from(set).filter(k => !slotOrder.includes(k)).sort()
    return [...slots, ...others]
  }, [subs])

  // Filter subs theo arc + speaker + search
  const filterSub = (s: Subtitle): boolean => {
    if (speakerFilter !== 'all') {
      const d = getSpeakerDisplay(s)
      if (d?.key !== speakerFilter) return false
    }
    if (search.trim()) {
      const q = search.toLowerCase()
      const hay = [
        s.text, s.original_text, s.text_v1, s.text_v2,
        s.character?.name, s.speaker_zh, s.speaker_slot,
      ].join(' ').toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  }

  const visibleArcs = useMemo(() => {
    const arcsSorted = [...arcs].sort((a, b) => a.start_line - b.start_line)
    if (selectedArc === null) return arcsSorted
    return arcsSorted.filter(a => a.arc_index === selectedArc)
  }, [arcs, selectedArc])

  const toggleArc = (idx: number) => {
    setCollapsedArcs(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  // Stats tổng
  const stats = useMemo(() => {
    const total = subs.length
    let translated = 0
    let withV2 = 0
    for (const s of subs) {
      if ((s.text_v1 || s.text)?.trim()) translated++
      if (s.text_v2?.trim()) withV2++
    }
    return { total, translated, withV2 }
  }, [subs])

  if (loading) {
    return <div className="p-6 text-zinc-500">Đang tải...</div>
  }
  if (error) {
    return <div className="p-6 text-red-600">⚠ {error}</div>
  }
  if (!arcs.length) {
    return (
      <div className="p-6 text-zinc-500 dark:text-zinc-400">
        Chưa có arcs. Hãy chạy Stage 1 (Build Bible) trong tab "Thủ công Mega v4".
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full">
      {/* Header / Filter bar */}
      <div className="px-3 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 sticky top-0 z-10">
        <div className="flex items-center gap-2 flex-wrap text-xs">
          <span className="font-semibold">
            {arcs.length} arcs · {stats.total} dòng · {stats.translated} đã dịch · {stats.withV2} có v2
          </span>
          <div className="flex-1" />

          <select
            value={selectedArc === null ? 'all' : String(selectedArc)}
            onChange={e => setSelectedArc(e.target.value === 'all' ? null : parseInt(e.target.value))}
            className="px-2 py-1 rounded border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900"
          >
            <option value="all">Tất cả arc ({arcs.length})</option>
            {arcs.map(a => (
              <option key={a.arc_index} value={a.arc_index}>
                Arc {a.arc_index + 1}: {a.title}
              </option>
            ))}
          </select>

          <select
            value={speakerFilter}
            onChange={e => setSpeakerFilter(e.target.value)}
            className="px-2 py-1 rounded border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900"
          >
            <option value="all">Tất cả speaker</option>
            {speakers.map(s => {
              const info = SLOT_BADGE[s]
              return <option key={s} value={s}>{info ? `${info.label} (${s})` : s}</option>
            })}
          </select>

          <input
            type="text"
            placeholder="🔍 Tìm trong v1/v2/Trung..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="px-2 py-1 rounded border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 min-w-[200px]"
          />
        </div>
      </div>

      {/* Arc cards */}
      <div className="flex-1 overflow-auto p-3 space-y-3 bg-zinc-50 dark:bg-zinc-900">
        {visibleArcs.map(arc => {
          const arcSubs = (subsByArc.get(arc.arc_index) || []).filter(filterSub)
          const isCollapsed = collapsedArcs.has(arc.arc_index)
          const toneLabel = ARC_TONE_LABELS[arc.emotional_tone] || arc.emotional_tone

          return (
            <div key={arc.arc_index}
                 className="bg-white dark:bg-zinc-950 rounded-lg border border-zinc-200 dark:border-zinc-800 shadow-sm">
              {/* Arc header */}
              <div className="px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 cursor-pointer
                              hover:bg-zinc-50 dark:hover:bg-zinc-900 flex items-start gap-3"
                   onClick={() => toggleArc(arc.arc_index)}>
                <span className="text-xl select-none">{isCollapsed ? '▶' : '▼'}</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-baseline gap-2 flex-wrap">
                    <h3 className="text-base font-bold">
                      Arc {arc.arc_index + 1}: {arc.title}
                    </h3>
                    <span className="text-xs text-zinc-500">
                      dòng {arc.start_line}–{arc.end_line}
                      {' '}({arc.end_line - arc.start_line + 1} dòng,
                      {' '}<strong>{arcSubs.length}</strong> sau filter)
                    </span>
                    {toneLabel && (
                      <span className="text-xs px-1.5 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200">
                        {toneLabel}
                      </span>
                    )}
                  </div>
                  {arc.summary && !isCollapsed && (
                    <p className="text-xs text-zinc-600 dark:text-zinc-400 mt-1 italic">
                      {arc.summary}
                    </p>
                  )}
                </div>
              </div>

              {/* Lines */}
              {!isCollapsed && (
                <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
                  {arcSubs.length === 0 ? (
                    <div className="px-4 py-4 text-xs text-zinc-400 italic">
                      Không có dòng nào trong arc này (sau filter).
                    </div>
                  ) : (
                    arcSubs.map(sub => <LineRow key={sub.id} sub={sub} />)
                  )}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ─── 1 dòng thoại — v1 + v2 song song ────────────────────────────────────────

function LineRow({ sub }: { sub: Subtitle }) {
  const speakerDisp = getSpeakerDisplay(sub)
  const v1 = sub.text_v1 || sub.text || ''
  const v2 = sub.text_v2 || ''
  const dur = (sub.end_time || 0) - (sub.start_time || 0)

  return (
    <div className="px-4 py-2.5 hover:bg-zinc-50/50 dark:hover:bg-zinc-900/50">
      {/* Meta row */}
      <div className="flex items-center gap-2 text-[11px] text-zinc-500 mb-1.5 flex-wrap">
        <span className="font-mono font-bold text-zinc-700 dark:text-zinc-300">
          #{sub.index}
        </span>
        <span className="font-mono">
          {fmt(sub.start_time)} → {fmt(sub.end_time)}
        </span>
        <span className="font-mono">{dur.toFixed(1)}s</span>

        {speakerDisp ? (
          <span style={{
            fontSize: 10, fontWeight: 700, padding: '1px 6px', borderRadius: 4,
            background: speakerDisp.bg, color: speakerDisp.color,
          }}>
            {speakerDisp.label}
          </span>
        ) : (
          <span className="text-[10px] font-semibold px-1.5 py-0.5 rounded bg-amber-50 text-amber-800">
            chưa gán
          </span>
        )}

        {sub.cps_value != null && (
          <span className="font-mono ml-auto" style={{ color: cpsColor(sub.cps_value) }}>
            CPS {sub.cps_value.toFixed(1)}
          </span>
        )}
        {sub.needs_review && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-800">
            ⚠ Review
          </span>
        )}
      </div>

      {/* Trung */}
      {sub.original_text && (
        <div className="text-sm text-zinc-500 dark:text-zinc-400 mb-1.5">
          <span className="text-[10px] font-mono mr-1 text-zinc-400">ZH</span>
          {sub.original_text}
        </div>
      )}

      {/* v1 + v2 song song */}
      <div className="grid grid-cols-2 gap-2">
        {/* v1 */}
        <div className={`rounded border px-2.5 py-1.5 ${
          (sub.variant_selected || 1) === 1
            ? 'border-blue-300 bg-blue-50 dark:bg-blue-950/30'
            : 'border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/40'
        }`}>
          <div className="flex items-center gap-1 text-[10px] font-bold text-blue-700 dark:text-blue-300 mb-0.5">
            <span>v1 · sát nghĩa</span>
            {(sub.variant_selected || 1) === 1 && (
              <span className="text-[9px] px-1 rounded bg-blue-200 text-blue-900">đang dùng</span>
            )}
          </div>
          <div className="text-sm">
            {v1 || <span className="text-zinc-400 italic">(chưa dịch)</span>}
          </div>
        </div>

        {/* v2 */}
        <div className={`rounded border px-2.5 py-1.5 ${
          (sub.variant_selected || 1) === 2
            ? 'border-purple-300 bg-purple-50 dark:bg-purple-950/30'
            : v2
              ? 'border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900/40'
              : 'border-dashed border-zinc-300 dark:border-zinc-700 bg-transparent'
        }`}>
          <div className="flex items-center gap-1 text-[10px] font-bold text-purple-700 dark:text-purple-300 mb-0.5">
            <span>v2 · thoát ý</span>
            {(sub.variant_selected || 1) === 2 && (
              <span className="text-[9px] px-1 rounded bg-purple-200 text-purple-900">đang dùng</span>
            )}
          </div>
          <div className="text-sm">
            {v2 || <span className="text-zinc-400 italic">(không có)</span>}
          </div>
        </div>
      </div>
    </div>
  )
}
