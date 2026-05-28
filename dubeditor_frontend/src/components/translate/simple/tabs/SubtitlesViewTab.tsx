/**
 * SubtitlesViewTab v2 — bảng phụ đề full-width với:
 *   - Cột Ghi chú (lỗi từ code scan, chỉ refresh khi bấm "Quét lỗi")
 *   - Inline edit Speaker + Tiếng Việt, lưu từng dòng
 *   - Filter status + "Có vấn đề" + search
 *   - KHÔNG fallback text legacy (chưa dịch → để trống)
 */
import React, { useState, useEffect, useMemo, useCallback } from 'react'
import api from '../../../../api'

interface ErrorNote {
  type: string
  label: string
  severity: string
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
  notes: ErrorNote[]
  has_issue: boolean
}

interface Props {
  projectId: number
}

type StatusFilter = 'all' | 'pending' | 'translated' | 'has_error' | 'fixed' | 'has_issue'

export default function SubtitlesViewTab({ projectId }: Props) {
  const [subs, setSubs] = useState<SimpleSubtitle[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('all')
  const [speakerFilter, setSpeakerFilter] = useState<string>('all')
  const [savingIdx, setSavingIdx] = useState<number | null>(null)
  const [lastScanInfo, setLastScanInfo] = useState<string | null>(null)

  // Inline edit state
  const [editingCell, setEditingCell] = useState<{ index: number; field: 'speaker' | 'vi' } | null>(null)
  const [editValue, setEditValue] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    api.get(`/projects/${projectId}/simple/subtitles`)
      .then(r => setSubs(r.data.subtitles || []))
      .catch(err => {
        console.error('[SubtitlesView] load error', err)
        setSubs([])
      })
      .finally(() => setLoading(false))
  }, [projectId])

  useEffect(() => { load() }, [load])

  // Scan errors
  const handleScan = async () => {
    setScanning(true)
    try {
      const r = await api.post(`/projects/${projectId}/simple/subtitles/scan-errors`)
      setSubs(r.data.subtitles || [])
      setLastScanInfo(`Quét ${r.data.scanned} dòng · ${r.data.errors_found} lỗi`)
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message
      setLastScanInfo('Lỗi quét: ' + detail)
    } finally {
      setScanning(false)
    }
  }

  // Save 1 dòng
  const saveCell = async (index: number, field: 'speaker' | 'vi', value: string) => {
    setSavingIdx(index)
    try {
      const body = field === 'speaker'
        ? { simple_speaker_zh: value }
        : { simple_text_vi: value }
      await api.patch(`/projects/${projectId}/simple/subtitles/${index}`, body)
      // Update local state
      setSubs(prev => prev?.map(s => {
        if (s.index !== index) return s
        return field === 'speaker'
          ? { ...s, simple_speaker_zh: value, simple_status: s.simple_status === 'pending' && s.simple_text_vi ? 'translated' : s.simple_status }
          : { ...s, simple_text_vi: value, simple_status: s.simple_status === 'pending' && value ? 'translated' : s.simple_status }
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

  const cancelEdit = () => {
    setEditingCell(null)
    setEditValue('')
  }

  // Speakers list
  const allSpeakers = useMemo(() => {
    if (!subs) return []
    const set = new Set<string>()
    for (const s of subs) if (s.simple_speaker_zh) set.add(s.simple_speaker_zh)
    return Array.from(set).sort()
  }, [subs])

  // Filter
  const filtered = useMemo(() => {
    if (!subs) return []
    const q = search.trim().toLowerCase()
    return subs.filter(s => {
      if (statusFilter === 'has_issue') {
        if (!s.has_issue) return false
      } else if (statusFilter !== 'all') {
        if ((s.simple_status || 'pending') !== statusFilter) return false
      }
      if (speakerFilter !== 'all' && s.simple_speaker_zh !== speakerFilter) return false
      if (q) {
        const hay = `${s.original_text || ''} ${s.simple_text_vi || ''}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [subs, search, statusFilter, speakerFilter])

  // Stats
  const stats = useMemo(() => {
    if (!subs) return { total: 0, pending: 0, translated: 0, has_error: 0, fixed: 0, has_issue: 0 }
    return {
      total: subs.length,
      pending: subs.filter(s => (s.simple_status || 'pending') === 'pending').length,
      translated: subs.filter(s => s.simple_status === 'translated').length,
      has_error: subs.filter(s => s.simple_status === 'has_error').length,
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
      {/* Stats bar — clickable filters */}
      <div className="grid grid-cols-3 sm:grid-cols-6 gap-2">
        <StatBox label="Tổng" value={stats.total} tone="neutral"
          active={statusFilter === 'all'} onClick={() => setStatusFilter('all')} />
        <StatBox label="Chưa dịch" value={stats.pending} tone="zinc"
          active={statusFilter === 'pending'} onClick={() => setStatusFilter('pending')} />
        <StatBox label="Đã dịch" value={stats.translated} tone="blue"
          active={statusFilter === 'translated'} onClick={() => setStatusFilter('translated')} />
        <StatBox label="Có lỗi" value={stats.has_error} tone="amber"
          active={statusFilter === 'has_error'} onClick={() => setStatusFilter('has_error')} />
        <StatBox label="Đã sửa" value={stats.fixed} tone="emerald"
          active={statusFilter === 'fixed'} onClick={() => setStatusFilter('fixed')} />
        <StatBox label="⚠ Có vấn đề" value={stats.has_issue} tone="red"
          active={statusFilter === 'has_issue'} onClick={() => setStatusFilter('has_issue')} />
      </div>

      {/* Toolbar */}
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
        <button
          onClick={handleScan}
          disabled={scanning}
          className={`btn ${scanning ? 'opacity-60' : ''}`}
          title="Quét lỗi code-based (chinese leak, CPS, speaker sai, rỗng) → gắn vào cột Ghi chú"
        >
          {scanning ? '⏳ Đang quét...' : '🔍 Quét lỗi'}
        </button>
        {lastScanInfo && (
          <span className="text-[11px] text-zinc-500">{lastScanInfo}</span>
        )}
        <span className="text-[12px] text-zinc-500 ml-auto">
          {filtered.length} / {subs.length} dòng
        </span>
      </div>

      {/* Table — full width */}
      <div className="surface-card overflow-hidden">
        <div className="overflow-x-auto max-h-[calc(100vh-330px)] overflow-y-auto">
          <table className="w-full text-[12.5px]">
            <thead className="bg-zinc-50 dark:bg-zinc-900 text-zinc-500 text-[11px] uppercase sticky top-0 z-10">
              <tr>
                <th className="text-left px-3 py-2 font-medium w-14">#</th>
                <th className="text-left px-3 py-2 font-medium w-16">Time</th>
                <th className="text-left px-3 py-2 font-medium w-32">Speaker</th>
                <th className="text-left px-3 py-2 font-medium w-1/4">Tiếng Trung</th>
                <th className="text-left px-3 py-2 font-medium w-1/4">Tiếng Việt</th>
                <th className="text-left px-3 py-2 font-medium">Ghi chú</th>
                <th className="text-center px-2 py-2 font-medium w-14">St</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {filtered.map(s => {
                const isSaving = savingIdx === s.index
                const editingSpeaker = editingCell?.index === s.index && editingCell.field === 'speaker'
                const editingVi = editingCell?.index === s.index && editingCell.field === 'vi'
                return (
                  <tr
                    key={s.id}
                    className={`group hover:bg-zinc-50 dark:hover:bg-zinc-900/40 ${
                      s.has_issue ? 'bg-amber-50/40 dark:bg-amber-900/10' : ''
                    } ${isSaving ? 'opacity-60' : ''}`}
                  >
                    <td className="px-3 py-2 font-mono text-zinc-400 text-[11px] align-top">{s.index}</td>
                    <td className="px-3 py-2 font-mono text-zinc-400 text-[11px] whitespace-nowrap align-top">
                      {formatTime(s.start_time)}
                    </td>

                    {/* Speaker — inline edit */}
                    <td className="px-2 py-1.5 align-top">
                      {editingSpeaker ? (
                        <input
                          autoFocus
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={e => {
                            if (e.key === 'Enter') commitEdit()
                            if (e.key === 'Escape') cancelEdit()
                          }}
                          className="w-full px-1.5 py-1 text-[12px] border border-blue-400 rounded bg-white dark:bg-zinc-900 font-mono"
                          placeholder="speaker_zh hoặc UNKNOWN"
                        />
                      ) : (
                        <button
                          onClick={() => startEdit(s.index, 'speaker', s.simple_speaker_zh || '')}
                          className="w-full text-left"
                        >
                          <SpeakerBadge speaker={s.simple_speaker_zh} />
                        </button>
                      )}
                    </td>

                    {/* Tiếng Trung — read only */}
                    <td className="px-3 py-2 text-zinc-700 dark:text-zinc-300 align-top">
                      {s.original_text || <span className="text-zinc-300 italic">—</span>}
                    </td>

                    {/* Tiếng Việt — inline edit, KHÔNG fallback text legacy */}
                    <td className="px-2 py-1.5 align-top">
                      {editingVi ? (
                        <textarea
                          autoFocus
                          value={editValue}
                          onChange={e => setEditValue(e.target.value)}
                          onBlur={commitEdit}
                          onKeyDown={e => {
                            if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commitEdit() }
                            if (e.key === 'Escape') cancelEdit()
                          }}
                          rows={2}
                          className="w-full px-1.5 py-1 text-[12.5px] border border-blue-400 rounded bg-white dark:bg-zinc-900 resize-y"
                          placeholder="Bản dịch tiếng Việt..."
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

                    {/* Ghi chú — error notes */}
                    <td className="px-3 py-2 align-top">
                      {s.notes.length === 0 ? (
                        <span className="text-zinc-300 dark:text-zinc-700">—</span>
                      ) : (
                        <div className="flex flex-wrap gap-1">
                          {s.notes.map((n, i) => (
                            <NoteBadge key={i} note={n} />
                          ))}
                        </div>
                      )}
                    </td>

                    {/* Status */}
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
        💡 Click vào ô Speaker hoặc Tiếng Việt để sửa. Enter để lưu, Esc để hủy.
        Ghi chú chỉ cập nhật khi bấm "🔍 Quét lỗi".
      </p>
    </div>
  )
}


// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${String(s).padStart(2, '0')}`
}

function StatBox({
  label, value, tone, active, onClick,
}: {
  label: string; value: number;
  tone: 'neutral' | 'zinc' | 'blue' | 'amber' | 'emerald' | 'red';
  active?: boolean; onClick?: () => void;
}) {
  const tones: Record<string, string> = {
    neutral: 'border-zinc-200 dark:border-zinc-700',
    zinc:    'border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-300',
    blue:    'border-blue-200 dark:border-blue-900 text-blue-700 dark:text-blue-300',
    amber:   'border-amber-200 dark:border-amber-900 text-amber-700 dark:text-amber-300',
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
  if (!speaker) {
    return <span className="text-zinc-300 dark:text-zinc-600 text-[11px] italic hover:text-blue-500">+ gán</span>
  }
  const special = ['UNKNOWN', 'CROWD', 'NARRATOR', 'OFF_SCREEN', 'PHONE']
  const isSpecial = special.includes(speaker)
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-mono whitespace-nowrap ${
      isSpecial
        ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400'
        : 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
    }`}>
      {speaker}
    </span>
  )
}

function NoteBadge({ note }: { note: ErrorNote }) {
  const cls = note.severity === 'error' || note.severity === 'critical'
    ? 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800'
    : 'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800'
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[10.5px] font-medium border ${cls}`}>
      {note.label}
    </span>
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
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${info.cls}`}>
      {info.label}
    </span>
  )
}
