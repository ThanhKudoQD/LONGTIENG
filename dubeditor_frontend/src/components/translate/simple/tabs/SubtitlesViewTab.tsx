/**
 * SubtitlesViewTab v3 — bảng phụ đề full-width.
 *   - Cột Ghi chú = đề xuất AI review (vi cũ→mới, speaker, lý do)
 *   - Filter "Có vấn đề" → hiện sub có suggestion + N dòng ngữ cảnh trước/sau
 *   - Inline edit Speaker + Tiếng Việt, lưu từng dòng
 *   - KHÔNG fallback text legacy (chưa dịch → trống)
 */
import React, { useState, useEffect, useMemo, useCallback } from 'react'
import api from '../../../../api'

interface Suggestion {
  id: number
  vi_old: string
  vi_new: string
  speaker_old: string
  speaker_new: string
  reason: string
  change_type: string
}

interface SimpleSubtitle {
  id: number
  index: number
  start_time: number
  end_time: number
  original_text: string
  simple_text_vi: string | null
  simple_speaker_zh: string | null
  simple_status: string
  batch_index: number | null
  suggestion: Suggestion | null
  has_issue: boolean
}

interface Props {
  projectId: number
}

type StatusFilter = 'all' | 'pending' | 'translated' | 'fixed' | 'has_issue'

const CONTEXT_LINES = 3

export default function SubtitlesViewTab({ projectId }: Props) {
  const [subs, setSubs] = useState<SimpleSubtitle[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [speakerFilter, setSpeakerFilter] = useState<string>('all')
  const [savingIdx, setSavingIdx] = useState<number | null>(null)

  const [editingCell, setEditingCell] = useState<{ index: number; field: 'speaker' | 'vi' } | null>(null)
  const [editValue, setEditValue] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/projects/${projectId}/simple/subtitles`)
      .then(r => setSubs(r.data.subtitles || []))
      .catch(() => setSubs([]))
      .finally(() => setLoading(false))
  }, [projectId])

  useEffect(() => { load() }, [load])

  const saveCell = async (index: number, field: 'speaker' | 'vi', value: string) => {
    setSavingIdx(index)
    try {
      const body = field === 'speaker' ? { simple_speaker_zh: value } : { simple_text_vi: value }
      await api.patch(`/projects/${projectId}/simple/subtitles/${index}`, body)
      setSubs(prev => prev?.map(s => {
        if (s.index !== index) return s
        return field === 'speaker'
          ? { ...s, simple_speaker_zh: value }
          : { ...s, simple_text_vi: value }
      }) || null)
    } catch (err) {
      console.error('[SubtitlesView] save error', err)
    } finally {
      setSavingIdx(null)
      setEditingCell(null)
    }
  }

  const startEdit = (index: number, field: 'speaker' | 'vi', current: string) => {
    setEditingCell({ index, field })
    setEditValue(current || '')
  }
  const commitEdit = () => {
    if (!editingCell) return
    saveCell(editingCell.index, editingCell.field, editValue)
  }
  const cancelEdit = () => { setEditingCell(null); setEditValue('') }

  const applySuggestion = async (sid: number) => {
    try {
      await api.post(`/projects/${projectId}/simple/review/suggestions/${sid}/apply`)
      load()
    } catch (err) { console.error(err) }
  }
  const dismissSuggestion = async (sid: number) => {
    try {
      await api.post(`/projects/${projectId}/simple/review/suggestions/${sid}/dismiss`)
      load()
    } catch (err) { console.error(err) }
  }

  const allSpeakers = useMemo(() => {
    if (!subs) return []
    const set = new Set<string>()
    for (const s of subs) if (s.simple_speaker_zh) set.add(s.simple_speaker_zh)
    return Array.from(set).sort()
  }, [subs])

  const filtered = useMemo(() => {
    if (!subs) return []
    const q = search.trim().toLowerCase()
    const matchSearchSpeaker = (s: SimpleSubtitle) => {
      if (speakerFilter !== 'all' && s.simple_speaker_zh !== speakerFilter) return false
      if (q) {
        const hay = `${s.original_text || ''} ${s.simple_text_vi || ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    }

    if (statusFilter === 'has_issue') {
      const issueIdx = new Set<number>()
      subs.forEach((s, i) => { if (s.has_issue) issueIdx.add(i) })
      const showIdx = new Set<number>()
      issueIdx.forEach(i => {
        for (let j = Math.max(0, i - CONTEXT_LINES); j <= Math.min(subs.length - 1, i + CONTEXT_LINES); j++) {
          showIdx.add(j)
        }
      })
      return subs.filter((s, i) => showIdx.has(i) && matchSearchSpeaker(s))
    }

    return subs.filter(s => {
      if (statusFilter !== 'all' && (s.simple_status || 'pending') !== statusFilter) return false
      return matchSearchSpeaker(s)
    })
  }, [subs, search, statusFilter, speakerFilter])

  const stats = useMemo(() => {
    if (!subs) return { total: 0, pending: 0, translated: 0, fixed: 0, has_issue: 0 }
    return {
      total: subs.length,
      pending: subs.filter(s => (s.simple_status || 'pending') === 'pending').length,
      translated: subs.filter(s => s.simple_status === 'translated').length,
      fixed: subs.filter(s => s.simple_status === 'fixed').length,
      has_issue: subs.filter(s => s.has_issue).length,
    }
  }, [subs])

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        <div className="w-8 h-8 border-2 border-zinc-300 border-t-blue-500 rounded-full animate-spin mb-3" />
        <div className="text-[13px]">Đang tải phụ đề...</div>
      </div>
    )
  }

  if (!subs || subs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        <div className="text-5xl mb-4">📝</div>
        <div className="text-[15px] font-medium">Chưa có phụ đề</div>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 sm:grid-cols-5 gap-2">
        <StatBox label="Tổng" value={stats.total} tone="neutral"
          active={statusFilter === 'all'} onClick={() => setStatusFilter('all')} />
        <StatBox label="Chưa dịch" value={stats.pending} tone="zinc"
          active={statusFilter === 'pending'} onClick={() => setStatusFilter('pending')} />
        <StatBox label="Đã dịch" value={stats.translated} tone="blue"
          active={statusFilter === 'translated'} onClick={() => setStatusFilter('translated')} />
        <StatBox label="Đã sửa" value={stats.fixed} tone="emerald"
          active={statusFilter === 'fixed'} onClick={() => setStatusFilter('fixed')} />
        <StatBox label="⚠ Có vấn đề" value={stats.has_issue} tone="red"
          active={statusFilter === 'has_issue'} onClick={() => setStatusFilter('has_issue')} />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="🔍 Tìm trong text (zh hoặc vi)..."
          className="flex-1 min-w-[200px] px-3 py-1.5 text-[13px] border border-zinc-200 dark:border-zinc-700 rounded-md bg-white dark:bg-zinc-900"
        />
        {allSpeakers.length > 0 && (
          <select
            value={speakerFilter}
            onChange={e => setSpeakerFilter(e.target.value)}
            className="px-3 py-1.5 text-[13px] border border-zinc-200 dark:border-zinc-700 rounded-md bg-white dark:bg-zinc-900"
          >
            <option value="all">Tất cả speakers ({allSpeakers.length})</option>
            {allSpeakers.map(sp => <option key={sp} value={sp}>{sp}</option>)}
          </select>
        )}
        <button onClick={load} className="btn text-[12px]">↻ Tải lại</button>
        <span className="text-[12px] text-zinc-500 ml-auto">
          {filtered.length} / {subs.length} dòng
        </span>
      </div>

      {statusFilter === 'has_issue' && (
        <div className="text-[12px] text-zinc-500 bg-amber-50 dark:bg-amber-900/10 rounded px-3 py-1.5">
          Đang xem các dòng có đề xuất từ AI review + {CONTEXT_LINES} dòng ngữ cảnh trước/sau.
          Dòng có vấn đề được tô nền vàng.
        </div>
      )}

      <div className="surface-card overflow-hidden">
        <div className="overflow-x-auto max-h-[calc(100vh-360px)] overflow-y-auto">
          <table className="w-full text-[12.5px]">
            <thead className="bg-zinc-50 dark:bg-zinc-900 text-zinc-500 text-[11px] uppercase sticky top-0 z-10">
              <tr>
                <th className="text-left px-3 py-2 font-medium w-14">#</th>
                <th className="text-left px-3 py-2 font-medium w-16">Time</th>
                <th className="text-left px-3 py-2 font-medium w-28">Speaker</th>
                <th className="text-left px-3 py-2 font-medium w-1/5">Tiếng Trung</th>
                <th className="text-left px-3 py-2 font-medium w-1/4">Tiếng Việt</th>
                <th className="text-left px-3 py-2 font-medium">Ghi chú (AI đề xuất)</th>
                <th className="text-center px-2 py-2 font-medium w-14">St</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {filtered.map(s => {
                const isSaving = savingIdx === s.index
                const editingSpeaker = editingCell?.index === s.index && editingCell.field === 'speaker'
                const editingVi = editingCell?.index === s.index && editingCell.field === 'vi'
                const sg = s.suggestion
                return (
                  <tr
                    key={s.id}
                    className={`group hover:bg-zinc-50 dark:hover:bg-zinc-900/40 ${
                      s.has_issue ? 'bg-amber-50/60 dark:bg-amber-900/10' : ''
                    } ${isSaving ? 'opacity-60' : ''}`}
                  >
                    <td className="px-3 py-2 font-mono text-zinc-400 text-[11px] align-top">{s.index}</td>
                    <td className="px-3 py-2 font-mono text-zinc-400 text-[11px] whitespace-nowrap align-top">
                      {formatTime(s.start_time)}
                    </td>

                    <td className="px-2 py-1.5 align-top">
                      {editingSpeaker ? (
                        <input
                          autoFocus value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={e => { if (e.key === 'Enter') commitEdit(); if (e.key === 'Escape') cancelEdit() }}
                          className="w-full px-1.5 py-1 text-[12px] border border-blue-400 rounded bg-white dark:bg-zinc-900 font-mono"
                        />
                      ) : (
                        <button onClick={() => startEdit(s.index, 'speaker', s.simple_speaker_zh || '')} className="w-full text-left">
                          <SpeakerBadge speaker={s.simple_speaker_zh} />
                        </button>
                      )}
                    </td>

                    <td className="px-3 py-2 text-zinc-700 dark:text-zinc-300 align-top">
                      {s.original_text || <span className="text-zinc-300 italic">—</span>}
                    </td>

                    <td className="px-2 py-1.5 align-top">
                      {editingVi ? (
                        <textarea
                          autoFocus value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={e => {
                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commitEdit() }
                            if (e.key === 'Escape') cancelEdit()
                          }}
                          rows={2}
                          className="w-full px-1.5 py-1 text-[12.5px] border border-blue-400 rounded bg-white dark:bg-zinc-900 resize-y"
                        />
                      ) : (
                        <button
                          onClick={() => startEdit(s.index, 'vi', s.simple_text_vi || '')}
                          className="w-full text-left text-zinc-900 dark:text-zinc-100 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded px-1 py-0.5 -mx-1 min-h-[1.5em] block"
                        >
                          {s.simple_text_vi || (
                            <span className="text-zinc-300 dark:text-zinc-600 italic">chưa dịch · click để nhập</span>
                          )}
                        </button>
                      )}
                    </td>

                    <td className="px-3 py-2 align-top">
                      {!sg ? (
                        <span className="text-zinc-300 dark:text-zinc-700">—</span>
                      ) : (
                        <div className="space-y-1">
                          {sg.vi_new !== sg.vi_old && (
                            <div className="text-[12px] text-emerald-700 dark:text-emerald-300">{sg.vi_new}</div>
                          )}
                          {sg.speaker_new !== sg.speaker_old && (
                            <div className="text-[11px] font-mono">
                              <span className="text-red-500 line-through">{sg.speaker_old || '∅'}</span>
                              <span className="text-zinc-400"> → </span>
                              <span className="text-emerald-700 dark:text-emerald-300">{sg.speaker_new || '∅'}</span>
                            </div>
                          )}
                          {sg.reason && <div className="text-[11px] text-zinc-500 italic">{sg.reason}</div>}
                          <div className="flex gap-1 pt-0.5">
                            <button onClick={() => applySuggestion(sg.id)}
                              className="px-2 py-0.5 rounded text-[10px] bg-emerald-600 text-white hover:bg-emerald-700">✓ Áp dụng</button>
                            <button onClick={() => dismissSuggestion(sg.id)}
                              className="px-2 py-0.5 rounded text-[10px] bg-zinc-200 dark:bg-zinc-700 hover:bg-zinc-300">✕ Bỏ</button>
                          </div>
                        </div>
                      )}
                    </td>

                    <td className="px-2 py-2 text-center align-top">
                      {isSaving ? (
                        <span className="inline-block w-3 h-3 border border-zinc-300 border-t-blue-500 rounded-full animate-spin" />
                      ) : (
                        <StatusBadge status={s.simple_status || 'pending'} />
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      </div>

      <p className="text-[11px] text-zinc-500">
        💡 Click ô Speaker / Tiếng Việt để sửa (Enter lưu, Esc hủy). Cột Ghi chú hiện đề xuất từ AI review (tab Review) — áp dụng hoặc bỏ ngay tại đây.
      </p>
    </div>
  )
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function StatBox({ label, value, tone, active, onClick }: {
  label: string; value: number;
  tone: 'neutral' | 'zinc' | 'blue' | 'emerald' | 'red'; active?: boolean; onClick?: () => void;
}) {
  const tones: Record<string, string> = {
    neutral: 'border-zinc-200 dark:border-zinc-700',
    zinc:    'border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300',
    blue:    'border-blue-200 dark:border-blue-900 text-blue-700 dark:text-blue-300',
    emerald: 'border-emerald-200 dark:border-emerald-900 text-emerald-700 dark:text-emerald-300',
    red:     'border-red-200 dark:border-red-900 text-red-700 dark:text-red-300',
  }
  return (
    <button
      onClick={onClick}
      className={`text-left px-3 py-2 rounded-md border bg-white dark:bg-zinc-950 transition-all ${tones[tone]} ${
        active ? 'ring-2 ring-blue-500 ring-offset-1 dark:ring-offset-zinc-950' : 'hover:border-zinc-300 dark:hover:border-zinc-600'
      }`}
    >
      <div className="text-[10px] uppercase tracking-wider font-medium opacity-70">{label}</div>
      <div className="text-[18px] font-semibold mt-0.5">{value}</div>
    </button>
  )
}

function SpeakerBadge({ speaker }: { speaker: string | null }) {
  if (!speaker) return <span className="text-zinc-300 dark:text-zinc-600 text-[11px] italic hover:text-blue-500">+ gán</span>
  const special = ['UNKNOWN', 'CROWD', 'NARRATOR', 'OFF_SCREEN', 'PHONE']
  const isSpecial = special.includes(speaker)
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-mono whitespace-nowrap ${
      isSpecial ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400'
                : 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
    }`}>{speaker}</span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const labels: Record<string, { label: string; cls: string }> = {
    pending:    { label: '·',  cls: 'bg-zinc-100 dark:bg-zinc-800 text-zinc-400' },
    translated: { label: '✓',  cls: 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300' },
    has_error:  { label: '!',  cls: 'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300' },
    fixed:      { label: '✓✓', cls: 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300' },
  }
  const info = labels[status] || labels.pending
  return <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${info.cls}`}>{info.label}</span>
}
