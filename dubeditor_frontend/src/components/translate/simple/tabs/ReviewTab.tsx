/**
 * ReviewTab v2 — AI review bản dịch (clone luồng batch dịch).
 *
 * Trái: danh sách review group (mỗi group 1 batch) + prompt + Auto/paste
 * Phải/dưới: bảng suggestions — zh | vi cũ→mới | speaker A→B | reason | apply
 */
import React, { useState, useMemo } from 'react'
import api from '../../../../api'

interface ReviewGroup {
  id: number
  group_index: number
  range_start: number
  range_end: number
  prompt: string
  response: string | null
  status: string
  error_msg: string | null
  est_tokens: number
}

interface Suggestion {
  id: number
  group_index: number
  subtitle_index: number
  zh: string
  vi_old: string
  vi_new: string
  speaker_old: string
  speaker_new: string
  reason: string
  change_type: 'text' | 'speaker' | 'both'
  status: 'pending' | 'applied' | 'dismissed'
}

interface ReviewState {
  config: { review_batch_size: number; review_context_lines: number }
  groups: ReviewGroup[]
  suggestions: Suggestion[]
  pending_count: number
  applied_count: number
}

interface Props {
  projectId: number
  runningTasks: Set<string>
  onRunGroup: (idx: number) => void
  onRunAll: () => void
}

export default function ReviewTab({ projectId, runningTasks, onRunGroup, onRunAll }: Props) {
  const [state, setState] = useState<ReviewState | null>(null)
  const [loading, setLoading] = useState(true)
  const [activeGroup, setActiveGroup] = useState(0)
  const [busy, setBusy] = useState(false)
  const [respDraft, setRespDraft] = useState('')

  // Reset draft khi đổi group
  React.useEffect(() => { setRespDraft('') }, [activeGroup])
  const [filterPending, setFilterPending] = useState(true)

  const load = React.useCallback(() => {
    setLoading(true)
    api.get(`/projects/${projectId}/simple/review`)
      .then(r => setState(r.data))
      .catch(() => setState(null))
      .finally(() => setLoading(false))
  }, [projectId])

  React.useEffect(() => { load() }, [load])

  // Poll khi có task review chạy
  React.useEffect(() => {
    const hasReview = Array.from(runningTasks).some(t => t.startsWith('review'))
    if (!hasReview) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [runningTasks, load])

  const rebuild = async () => {
    setBusy(true)
    try {
      const r = await api.post(`/projects/${projectId}/simple/review/rebuild`)
      setState(r.data)
    } finally { setBusy(false) }
  }

  const saveResponse = async (groupIndex: number) => {
    if (!respDraft.trim()) return
    setBusy(true)
    try {
      const r = await api.post(
        `/projects/${projectId}/simple/review/${groupIndex}/save`,
        { response: respDraft }
      )
      setState(r.data)
      setRespDraft('')
    } catch (err: any) {
      alert('Lỗi lưu: ' + (err?.response?.data?.detail || err?.message))
    } finally { setBusy(false) }
  }

  const applyOne = async (sid: number) => {
    const r = await api.post(`/projects/${projectId}/simple/review/suggestions/${sid}/apply`)
    setState(r.data)
  }
  const dismissOne = async (sid: number) => {
    const r = await api.post(`/projects/${projectId}/simple/review/suggestions/${sid}/dismiss`)
    setState(r.data)
  }
  const applyAll = async () => {
    setBusy(true)
    try {
      const r = await api.post(`/projects/${projectId}/simple/review/apply-all`, {})
      setState(r.data)
    } finally { setBusy(false) }
  }

  const suggestions = useMemo(() => {
    if (!state) return []
    return filterPending
      ? state.suggestions.filter(s => s.status === 'pending')
      : state.suggestions
  }, [state, filterPending])

  if (loading) {
    return <div className="py-20 text-center text-zinc-500">Đang tải...</div>
  }

  if (!state || state.groups.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
        <div className="text-5xl mb-4">🔍</div>
        <div className="text-[15px] font-medium mb-2">Chưa có review batch</div>
        <div className="text-[13px] mb-4">Chia bản dịch thành các batch để AI rà soát lại.</div>
        <button onClick={rebuild} disabled={busy} className="btn btn-primary">
          {busy ? 'Đang chia...' : '↻ Chia review batch'}
        </button>
      </div>
    )
  }

  const active = state.groups.find(g => g.group_index === activeGroup) || state.groups[0]
  const reviewRunning = Array.from(runningTasks).some(t => t.startsWith('review'))

  return (
    <div className="space-y-4">
      {/* Header actions */}
      <div className="flex flex-wrap items-center gap-2">
        <button onClick={rebuild} disabled={busy} className="btn">↻ Rebuild</button>
        <button onClick={onRunAll} disabled={reviewRunning} className="btn btn-primary">
          {reviewRunning ? '⏳ Đang review...' : '⚡ Review tất cả'}
        </button>
        <div className="text-[12px] text-zinc-500">
          {state.groups.length} batch · size {state.config.review_batch_size}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[12px] text-amber-600">{state.pending_count} chờ duyệt</span>
          <span className="text-[12px] text-emerald-600">{state.applied_count} đã áp dụng</span>
          {state.pending_count > 0 && (
            <button onClick={applyAll} disabled={busy} className="btn btn-primary text-[12px]">
              ✓ Apply tất cả ({state.pending_count})
            </button>
          )}
        </div>
      </div>

      {/* Group list + prompt */}
      <div className="grid grid-cols-1 lg:grid-cols-[260px_1fr] gap-3">
        {/* Batch list */}
        <div className="surface-card overflow-hidden">
          <div className="px-3 py-2 text-[11px] uppercase tracking-wider text-zinc-500 border-b border-zinc-200 dark:border-zinc-800">
            Review batches
          </div>
          <div className="max-h-[300px] overflow-y-auto divide-y divide-zinc-100 dark:divide-zinc-800">
            {state.groups.map(g => {
              const gSuggs = state.suggestions.filter(s => s.group_index === g.group_index && s.status === 'pending')
              const isRunning = runningTasks.has(`review.group.${g.group_index}`)
              return (
                <button
                  key={g.id}
                  onClick={() => setActiveGroup(g.group_index)}
                  className={`w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-zinc-50 dark:hover:bg-zinc-900/40 ${
                    g.group_index === activeGroup ? 'bg-blue-50 dark:bg-blue-900/20' : ''
                  }`}
                >
                  <span className="font-mono text-[11px] text-zinc-400 w-6">{String(g.group_index + 1).padStart(2, '0')}</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] text-zinc-700 dark:text-zinc-300">
                      {g.range_start} → {g.range_end}
                    </div>
                  </div>
                  {isRunning
                    ? <span className="w-3 h-3 border border-zinc-300 border-t-blue-500 rounded-full animate-spin" />
                    : <StatusDot status={g.status} count={gSuggs.length} />}
                </button>
              )
            })}
          </div>
        </div>

        {/* Active group: prompt (trái) + paste response (phải) */}
        <div className="surface-card p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[12px] font-medium">
              Batch {active.group_index + 1} · dòng {active.range_start}→{active.range_end} · ~{active.est_tokens} tok
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => navigator.clipboard.writeText(active.prompt)}
                className="btn text-[11px]"
              >📋 Copy prompt</button>
              <button
                onClick={() => onRunGroup(active.group_index)}
                disabled={runningTasks.has(`review.group.${active.group_index}`)}
                className="btn btn-primary text-[11px]"
              >⚡ Auto review</button>
            </div>
          </div>
          {active.error_msg && (
            <div className="text-[12px] text-red-600 bg-red-50 dark:bg-red-900/20 rounded px-2 py-1">
              {active.error_msg}
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {/* Prompt */}
            <div>
              <div className="text-[10px] uppercase tracking-wider text-zinc-400 mb-1">Prompt</div>
              <pre className="text-[11px] font-mono text-zinc-600 dark:text-zinc-400 bg-zinc-50 dark:bg-zinc-900 rounded p-2 h-[200px] overflow-y-auto whitespace-pre-wrap">
                {active.prompt}
              </pre>
            </div>
            {/* Response paste */}
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] uppercase tracking-wider text-zinc-400">
                  Response {active.response ? '(đã có)' : '(paste vào đây)'}
                </span>
                <div className="flex gap-1">
                  <button
                    onClick={() => { setRespDraft(''); }}
                    className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 hover:bg-zinc-200"
                  >Clear</button>
                  <button
                    onClick={() => saveResponse(active.group_index)}
                    disabled={busy || !respDraft.trim()}
                    className="text-[10px] px-2 py-0.5 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
                  >💾 Lưu</button>
                </div>
              </div>
              <textarea
                value={respDraft || active.response || ''}
                onChange={e => setRespDraft(e.target.value)}
                placeholder='Paste JSON response từ AI vào đây, hoặc bấm "⚡ Auto review" để tự gọi...'
                className="w-full h-[200px] text-[11px] font-mono border border-zinc-200 dark:border-zinc-700 rounded p-2 bg-white dark:bg-zinc-950 resize-none"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Suggestions table */}
      <div className="flex items-center gap-2">
        <h3 className="text-[13px] font-semibold text-zinc-800 dark:text-zinc-200">
          Đề xuất sửa ({suggestions.length})
        </h3>
        <label className="flex items-center gap-1.5 text-[12px] text-zinc-500 ml-auto cursor-pointer">
          <input type="checkbox" checked={filterPending} onChange={e => setFilterPending(e.target.checked)} />
          Chỉ hiện chờ duyệt
        </label>
      </div>

      {suggestions.length === 0 ? (
        <div className="surface-card p-6 text-center text-zinc-500 text-[13px]">
          {reviewRunning ? 'Đang review...' : 'Chưa có đề xuất. Bấm "⚡ Review tất cả" hoặc Auto từng batch.'}
        </div>
      ) : (
        <div className="surface-card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-[12.5px]">
              <thead className="bg-zinc-50 dark:bg-zinc-900 text-zinc-500 text-[11px] uppercase">
                <tr>
                  <th className="text-left px-2 py-2 w-12">#</th>
                  <th className="text-left px-3 py-2 w-1/5">Tiếng Trung</th>
                  <th className="text-left px-3 py-2">Tiếng Việt (cũ → AI gợi ý)</th>
                  <th className="text-left px-3 py-2 w-32">Speaker</th>
                  <th className="text-left px-3 py-2 w-1/5">Lý do</th>
                  <th className="text-center px-2 py-2 w-24">Hành động</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
                {suggestions.map(s => (
                  <tr key={s.id} className={`hover:bg-zinc-50 dark:hover:bg-zinc-900/40 ${
                    s.status === 'applied' ? 'opacity-50' : ''
                  }`}>
                    <td className="px-2 py-2 font-mono text-[11px] text-zinc-400 align-top">{s.subtitle_index}</td>
                    <td className="px-3 py-2 text-zinc-600 dark:text-zinc-400 align-top">{s.zh}</td>
                    <td className="px-3 py-2 align-top">
                      {s.vi_old !== s.vi_new ? (
                        <div className="space-y-1">
                          <div className="text-[12px] text-red-500 line-through opacity-70">{s.vi_old}</div>
                          <div className="text-[13px] text-emerald-700 dark:text-emerald-300 font-medium">{s.vi_new}</div>
                        </div>
                      ) : (
                        <div className="text-zinc-700 dark:text-zinc-300">{s.vi_new}</div>
                      )}
                    </td>
                    <td className="px-3 py-2 align-top">
                      {s.speaker_old !== s.speaker_new ? (
                        <div className="flex items-center gap-1 text-[11px] font-mono">
                          <span className="text-red-500 line-through">{s.speaker_old || '∅'}</span>
                          <span className="text-zinc-400">→</span>
                          <span className="text-emerald-700 dark:text-emerald-300 font-medium">{s.speaker_new || '∅'}</span>
                        </div>
                      ) : (
                        <span className="text-[11px] font-mono text-zinc-400">{s.speaker_new || '—'}</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-[11.5px] text-zinc-500 italic align-top">{s.reason || '—'}</td>
                    <td className="px-2 py-2 align-top">
                      {s.status === 'pending' ? (
                        <div className="flex gap-1 justify-center">
                          <button onClick={() => applyOne(s.id)}
                            className="px-2 py-1 rounded text-[11px] bg-emerald-600 text-white hover:bg-emerald-700">✓</button>
                          <button onClick={() => dismissOne(s.id)}
                            className="px-2 py-1 rounded text-[11px] bg-zinc-200 dark:bg-zinc-700 hover:bg-zinc-300">✕</button>
                        </div>
                      ) : (
                        <span className="text-[11px] text-center block text-emerald-600">
                          {s.status === 'applied' ? '✓ đã áp dụng' : 'đã bỏ'}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}

function StatusDot({ status, count }: { status: string; count: number }) {
  if (status === 'done') {
    return count > 0
      ? <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 font-medium">{count}</span>
      : <span className="text-emerald-500 text-[13px]">✓</span>
  }
  if (status === 'error') return <span className="text-red-500 text-[13px]">!</span>
  return <span className="w-2 h-2 rounded-full bg-zinc-300 dark:bg-zinc-600" />
}
