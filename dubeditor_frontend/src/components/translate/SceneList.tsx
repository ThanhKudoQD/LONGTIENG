/**
 * SceneList — danh sách phân cảnh với detail view.
 *
 * Layout: 2 cột (sidebar scenes + main detail) hoặc full list khi không chọn.
 *
 * Tích hợp issues:
 *   - Sidebar: badge số issue trên mỗi scene (đỏ nếu có)
 *   - Arc filter dropdown: badge số issue tổng của arc
 *   - Filter chip "🔧 Có vấn đề"
 *   - Detail: hiển thị section issues riêng + đánh dấu dòng nào có vấn đề trong list thoại
 */
import React, { useEffect, useMemo, useState } from 'react'
import { translateApi } from '../../api'
import type { Scene, StoryArc, PolishIssue } from '../../types'
import { EMOTION_LABELS, EMOTION_COLORS } from '../../types'

export default function SceneList({
  projectId, scenes, arcs, issues, onIssuesUpdate,
}: {
  projectId: number
  scenes: Scene[]
  arcs: StoryArc[]
  issues: PolishIssue[]
  onIssuesUpdate: () => void
}) {
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [filter, setFilter] = useState<'all' | 'hook' | 'peak' | 'issue'>('all')
  const [arcFilter, setArcFilter] = useState<number | null>(null)

  // Tính số issues unresolved cho mỗi scene + arc
  const { issuesByScene, issuesByArc } = useMemo(() => {
    const byScene: Record<number, PolishIssue[]> = {}
    const byArc: Record<number, number> = {}
    for (const iss of issues) {
      if (iss.resolved) continue
      const scene = scenes.find(s => iss.line_index >= s.start_line && iss.line_index <= s.end_line)
      if (!scene) continue
      if (!byScene[scene.id]) byScene[scene.id] = []
      byScene[scene.id].push(iss)
      if (scene.story_arc_id != null) {
        byArc[scene.story_arc_id] = (byArc[scene.story_arc_id] || 0) + 1
      }
    }
    return { issuesByScene: byScene, issuesByArc: byArc }
  }, [issues, scenes])

  const totalIssues = issues.filter(i => !i.resolved).length

  if (scenes.length === 0) {
    return (
      <div className="p-8 text-center text-zinc-500">
        <div className="text-4xl mb-3">🎬</div>
        <div className="text-sm">Chưa có phân cảnh. Chạy Stage 2.</div>
      </div>
    )
  }

  let filtered = scenes
  if (arcFilter !== null) filtered = filtered.filter(s => s.story_arc_id === arcFilter)
  if (filter === 'hook') filtered = filtered.filter(s => s.is_hook)
  if (filter === 'peak') filtered = filtered.filter(s => s.is_emotion_peak)
  if (filter === 'issue') filtered = filtered.filter(s => (issuesByScene[s.id]?.length || 0) > 0)

  return (
    <div className="flex h-full">
      {/* SIDEBAR */}
      <div className="w-96 border-r border-zinc-200 dark:border-zinc-800 flex flex-col">
        {/* Filters */}
        <div className="p-3 border-b border-zinc-200 dark:border-zinc-800 space-y-2 bg-white dark:bg-zinc-950">
          <div className="flex gap-1 flex-wrap">
            <FilterChip active={filter === 'all'} onClick={() => setFilter('all')}>
              Tất cả ({scenes.length})
            </FilterChip>
            <FilterChip active={filter === 'hook'} onClick={() => setFilter('hook')}>
              🎯 Hook ({scenes.filter(s => s.is_hook).length})
            </FilterChip>
            <FilterChip active={filter === 'peak'} onClick={() => setFilter('peak')}>
              🔥 Peak ({scenes.filter(s => s.is_emotion_peak).length})
            </FilterChip>
            {totalIssues > 0 && (
              <FilterChip
                active={filter === 'issue'}
                onClick={() => setFilter('issue')}
                tone="danger"
              >
                🔧 Vấn đề ({Object.keys(issuesByScene).length} scenes)
              </FilterChip>
            )}
          </div>
          {arcs.length > 0 && (
            <select
              value={arcFilter ?? ''}
              onChange={e => setArcFilter(e.target.value ? Number(e.target.value) : null)}
              className="input w-full text-[11px]"
            >
              <option value="">Tất cả arcs</option>
              {arcs.map(a => {
                const arcIssues = issuesByArc[a.id] || 0
                return (
                  <option key={a.id} value={a.id}>
                    Arc {a.arc_index + 1}: {a.title} ({a.scene_count} scenes
                    {arcIssues > 0 ? `, ⚠ ${arcIssues}` : ''})
                  </option>
                )
              })}
            </select>
          )}
        </div>

        {/* List */}
        <div className="flex-1 overflow-auto">
          {filtered.map(scene => (
            <SceneRow
              key={scene.id}
              scene={scene}
              selected={scene.id === selectedId}
              issueCount={issuesByScene[scene.id]?.length || 0}
              onClick={() => setSelectedId(scene.id)}
            />
          ))}
        </div>
      </div>

      {/* DETAIL */}
      <div className="flex-1 overflow-auto">
        {selectedId === null ? (
          <div className="h-full flex items-center justify-center text-zinc-400 text-sm">
            Chọn 1 phân cảnh để xem chi tiết
          </div>
        ) : (
          <SceneDetail
            projectId={projectId}
            sceneId={selectedId}
            sceneIssues={issuesByScene[selectedId] || []}
            onIssuesUpdate={onIssuesUpdate}
            key={selectedId}
          />
        )}
      </div>
    </div>
  )
}

function FilterChip({ active, onClick, children, tone }: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
  tone?: 'danger'
}) {
  const activeClass = tone === 'danger'
    ? 'bg-red-500 text-white'
    : 'bg-blue-500 text-white'
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 rounded-full text-[11px] font-medium transition-all ${
        active
          ? activeClass
          : 'bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700'
      }`}
    >
      {children}
    </button>
  )
}

function SceneRow({ scene, selected, issueCount, onClick }: {
  scene: Scene
  selected: boolean
  issueCount: number
  onClick: () => void
}) {
  const statusColor = scene.status === 'polished' ? 'bg-green-500'
    : scene.status === 'translated' ? 'bg-blue-500'
    : scene.status === 'speaker' ? 'bg-amber-500'
    : scene.status === 'error' ? 'bg-red-500'
    : 'bg-zinc-300 dark:bg-zinc-600'

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2.5 border-b border-zinc-100 dark:border-zinc-800 transition-colors ${
        selected
          ? 'bg-blue-50 dark:bg-blue-900/20'
          : issueCount > 0
          ? 'bg-red-50/30 dark:bg-red-900/10 hover:bg-red-50/60 dark:hover:bg-red-900/20'
          : 'hover:bg-zinc-50 dark:hover:bg-zinc-900'
      }`}
    >
      <div className="flex items-center gap-2 mb-1">
        <span className={`w-1.5 h-1.5 rounded-full ${statusColor}`} />
        <span className="text-[11px] font-mono text-zinc-400">#{scene.scene_index + 1}</span>
        <span className="text-[10px] text-zinc-400">L{scene.start_line}-{scene.end_line}</span>
        <div className="flex-1" />
        {issueCount > 0 && (
          <span className="inline-flex items-center gap-0.5 px-1.5 py-0 rounded text-[10px] font-bold bg-red-500 text-white">
            🔧 {issueCount}
          </span>
        )}
        {scene.is_hook && <span className="text-[10px]">🎯</span>}
        {scene.is_emotion_peak && <span className="text-[10px]">🔥</span>}
        <EmotionBadge emotion={scene.emotion_primary} />
      </div>
      <div className="text-[12px] font-medium text-zinc-800 dark:text-zinc-100 truncate">
        {scene.location || '(chưa có địa điểm)'}
      </div>
      <div className="text-[11px] text-zinc-500 line-clamp-2 mt-0.5">
        {scene.summary || '(chưa có summary)'}
      </div>
    </button>
  )
}

function EmotionBadge({ emotion }: { emotion: string }) {
  const color = EMOTION_COLORS[emotion] || '#9CA3AF'
  return (
    <span
      className="inline-flex px-1.5 py-0 rounded text-[9px] font-medium text-white"
      style={{ backgroundColor: color }}
      title={EMOTION_LABELS[emotion] || emotion}
    >
      {(EMOTION_LABELS[emotion] || emotion).slice(0, 4)}
    </span>
  )
}

// ─── DETAIL ──────────────────────────────────────────────────────────────────

function SceneDetail({ projectId, sceneId, sceneIssues, onIssuesUpdate }: {
  projectId: number
  sceneId: number
  sceneIssues: PolishIssue[]
  onIssuesUpdate: () => void
}) {
  const [data, setData] = useState<{ scene: Scene; subtitles: any[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [activeFilter, setActiveFilter] = useState<'all' | 'issues'>('all')

  useEffect(() => {
    let cancelled = false
    setLoading(true); setErr('')
    translateApi.getSceneDetail(projectId, sceneId)
      .then(d => { if (!cancelled) { setData(d); setLoading(false) } })
      .catch(e => { if (!cancelled) { setErr(e?.message || 'load failed'); setLoading(false) } })
    return () => { cancelled = true }
  }, [projectId, sceneId])

  if (loading) return <div className="p-8 text-center text-zinc-500">Loading...</div>
  if (err) return <div className="p-4 text-red-600">{err}</div>
  if (!data) return null

  const s = data.scene

  // Map: line_index → issues của line đó
  const issuesByLine: Record<number, PolishIssue[]> = {}
  for (const iss of sceneIssues) {
    if (!issuesByLine[iss.line_index]) issuesByLine[iss.line_index] = []
    issuesByLine[iss.line_index].push(iss)
  }

  // Set: line_index có vấn đề (issue HOẶC needs_review)
  const linesWithIssues = new Set<number>()
  for (const sub of data.subtitles) {
    if (issuesByLine[sub.index]?.length || sub.needs_review) {
      linesWithIssues.add(sub.index)
    }
  }

  const visibleSubs = activeFilter === 'issues'
    ? data.subtitles.filter(sub => linesWithIssues.has(sub.index))
    : data.subtitles

  const handleApply = async (issueId: number) => {
    try {
      await translateApi.applyIssue(projectId, issueId)
      onIssuesUpdate()
      // Reload scene để cập nhật text
      const d = await translateApi.getSceneDetail(projectId, sceneId)
      setData(d)
    } catch (e: any) {
      alert(`Apply fail: ${e?.response?.data?.detail || e.message}`)
    }
  }

  const handleDismiss = async (issueId: number) => {
    try {
      await translateApi.dismissIssue(projectId, issueId)
      onIssuesUpdate()
    } catch (e: any) {
      alert(`Dismiss fail: ${e?.response?.data?.detail || e.message}`)
    }
  }

  return (
    <div className="p-5 max-w-4xl">
      {/* Header */}
      <div className="bg-white dark:bg-zinc-950 rounded-lg border border-zinc-200 dark:border-zinc-800 p-4 mb-4">
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm font-mono text-zinc-400">Scene #{s.scene_index + 1}</span>
          <span className="text-[12px] text-zinc-400">· Dòng {s.start_line}-{s.end_line}</span>
          <span className="text-[12px] text-zinc-400">· {s.line_count} lines</span>
          <div className="flex-1" />
          {sceneIssues.length > 0 && (
            <span className="px-2 py-0.5 rounded text-[11px] font-bold bg-red-500 text-white">
              🔧 {sceneIssues.length} vấn đề
            </span>
          )}
          {s.is_hook && (
            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">
              🎯 Hook
            </span>
          )}
          {s.is_emotion_peak && (
            <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300">
              🔥 Peak
            </span>
          )}
        </div>

        {s.location && (
          <div className="text-lg font-semibold text-zinc-800 dark:text-zinc-100 mb-1">
            📍 {s.location}{s.time_of_day && <span className="text-zinc-500 text-sm font-normal"> · {s.time_of_day}</span>}
          </div>
        )}

        {s.summary && (
          <div className="text-sm text-zinc-700 dark:text-zinc-300 mb-2">{s.summary}</div>
        )}

        {s.purpose && (
          <div className="text-[12px] text-zinc-500 italic mb-2">
            <strong className="not-italic text-zinc-600 dark:text-zinc-400">Mục đích kịch: </strong>
            {s.purpose}
          </div>
        )}

        <div className="flex flex-wrap gap-2 text-[11px]">
          <span className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800">
            <strong>Cảm xúc:</strong> {EMOTION_LABELS[s.emotion_primary] || s.emotion_primary}
          </span>
          {s.emotion_arc && (
            <span className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800">
              {s.emotion_arc}
            </span>
          )}
          {s.characters_present?.map((c, i) => (
            <span key={i} className="px-2 py-0.5 rounded bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300">
              {c}
            </span>
          ))}
        </div>
      </div>

      {/* Issues section — chỉ hiện nếu có */}
      {sceneIssues.length > 0 && (
        <div className="bg-red-50/50 dark:bg-red-900/10 border border-red-200 dark:border-red-800 rounded-lg p-4 mb-4">
          <div className="flex items-center gap-2 mb-3">
            <span className="text-[12px] font-bold text-red-700 dark:text-red-400 uppercase tracking-wider">
              🔧 Vấn đề trong cảnh ({sceneIssues.length})
            </span>
          </div>
          <div className="space-y-2">
            {sceneIssues.map(iss => (
              <IssueCard
                key={iss.id}
                issue={iss}
                onApply={() => handleApply(iss.id)}
                onDismiss={() => handleDismiss(iss.id)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Filter thoại */}
      <div className="flex items-center gap-2 mb-2 px-2">
        <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">
          Thoại trong cảnh ({visibleSubs.length}{visibleSubs.length !== data.subtitles.length ? `/${data.subtitles.length}` : ''})
        </span>
        <div className="flex-1" />
        {linesWithIssues.size > 0 && (
          <div className="flex gap-1">
            <FilterChip active={activeFilter === 'all'} onClick={() => setActiveFilter('all')}>
              Tất cả
            </FilterChip>
            <FilterChip
              active={activeFilter === 'issues'}
              onClick={() => setActiveFilter('issues')}
              tone="danger"
            >
              ⚠ Chỉ có vấn đề ({linesWithIssues.size})
            </FilterChip>
          </div>
        )}
      </div>

      <div className="space-y-1.5">
        {visibleSubs.map(sub => (
          <SubtitleRow
            key={sub.id}
            sub={sub}
            issues={issuesByLine[sub.index] || []}
            onApply={handleApply}
            onDismiss={handleDismiss}
          />
        ))}
      </div>
    </div>
  )
}

// ─── Issue card (apply/dismiss) ──────────────────────────────────────────────

function IssueCard({ issue, onApply, onDismiss }: {
  issue: PolishIssue
  onApply: () => void
  onDismiss: () => void
}) {
  const typeIcon: Record<string, string> = {
    name_inconsistent: '👤',
    pronoun_inconsistent: '🗣',
    terminology: '📚',
    style_drift: '🎭',
    cps_exceed: '⚡',
    other: '❓',
  }
  const confColor =
    issue.confidence === 'high' ? 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'
    : issue.confidence === 'mid' ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300'
    : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'

  return (
    <div className="bg-white dark:bg-zinc-950 rounded border border-red-200 dark:border-red-800 p-3">
      <div className="flex items-center gap-2 mb-2 text-[11px]">
        <span className="text-[14px]">{typeIcon[issue.issue_type] || '⚠'}</span>
        <span className="font-mono text-zinc-400">line #{issue.line_index}</span>
        <span className="font-semibold text-zinc-700 dark:text-zinc-300">{issue.issue_type}</span>
        <span className={`px-1.5 py-0 rounded text-[10px] font-medium ${confColor}`}>
          {issue.confidence}
        </span>
        <div className="flex-1" />
        {issue.suggested_text && (
          <button
            onClick={onApply}
            className="px-2.5 py-1 rounded text-[11px] font-medium bg-green-500 hover:bg-green-600 text-white"
          >
            ✓ Áp dụng
          </button>
        )}
        <button
          onClick={onDismiss}
          className="px-2.5 py-1 rounded text-[11px] font-medium bg-zinc-100 hover:bg-zinc-200 dark:bg-zinc-800 dark:hover:bg-zinc-700"
        >
          ✕ Bỏ qua
        </button>
      </div>

      <div className="text-[12px] text-zinc-700 dark:text-zinc-300 mb-1.5">
        {issue.description}
      </div>

      {(issue.current_text || issue.suggested_text) && (
        <div className="text-[11px] space-y-0.5 font-mono bg-zinc-50 dark:bg-zinc-900 rounded p-2">
          {issue.current_text && (
            <div className="text-red-600 dark:text-red-400">
              − {issue.current_text}
            </div>
          )}
          {issue.suggested_text && (
            <div className="text-green-600 dark:text-green-400">
              + {issue.suggested_text}
            </div>
          )}
        </div>
      )}

      {issue.evidence && (
        <div className="text-[10px] text-zinc-500 italic mt-1.5">
          💡 {issue.evidence}
        </div>
      )}
    </div>
  )
}

// ─── Subtitle row (with issue indicator) ─────────────────────────────────────

function SubtitleRow({ sub, issues, onApply, onDismiss }: {
  sub: any
  issues: PolishIssue[]
  onApply: (id: number) => void
  onDismiss: (id: number) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const conf = sub.speaker_confidence as 'high' | 'mid' | 'low'
  const confColor =
    conf === 'high' ? 'text-green-700 bg-green-50 dark:bg-green-900/30 dark:text-green-300'
    : conf === 'mid' ? 'text-blue-700 bg-blue-50 dark:bg-blue-900/30 dark:text-blue-300'
    : 'text-amber-700 bg-amber-50 dark:bg-amber-900/30 dark:text-amber-300'

  const cpsColor = !sub.cps_value ? '' :
    sub.cps_value > 18 ? 'text-red-600' :
    sub.cps_value > 15 ? 'text-amber-600' :
    'text-zinc-500'

  const hasIssue = issues.length > 0
  const hasReview = sub.needs_review

  return (
    <div className={`rounded-lg border ${
      hasIssue
        ? 'bg-red-50/30 dark:bg-red-900/10 border-red-300 dark:border-red-800'
        : hasReview
        ? 'bg-amber-50/30 dark:bg-amber-900/10 border-amber-300 dark:border-amber-800'
        : 'bg-white dark:bg-zinc-950 border-zinc-200 dark:border-zinc-800'
    } px-3 py-2`}>
      <div className="flex items-center gap-2 text-[11px] mb-1">
        <span className="font-mono text-zinc-400">#{sub.index}</span>
        {sub.speaker_vi && (
          <span className={`px-1.5 py-0 rounded font-medium ${confColor}`}>
            {sub.speaker_vi} <span className="opacity-60">[{conf}]</span>
          </span>
        )}
        {sub.emotion && (
          <span className="px-1.5 py-0 rounded text-white" style={{ backgroundColor: EMOTION_COLORS[sub.emotion] || '#9CA3AF' }}>
            {EMOTION_LABELS[sub.emotion] || sub.emotion}
            {sub.intensity != null && <span className="opacity-70"> ·{sub.intensity}</span>}
          </span>
        )}
        {sub.cps_value && (
          <span className={cpsColor}>CPS {sub.cps_value.toFixed(1)}</span>
        )}
        <div className="flex-1" />
        {hasIssue && (
          <button
            onClick={() => setExpanded(v => !v)}
            className="px-1.5 py-0 rounded text-[10px] font-bold bg-red-500 text-white hover:bg-red-600"
          >
            🔧 {issues.length} {expanded ? '▾' : '▸'}
          </button>
        )}
        {hasReview && <span className="text-amber-600" title={sub.review_reason}>⚠</span>}
      </div>
      <div className="text-[12px] text-zinc-500 mb-0.5">{sub.text_zh}</div>
      <div className="text-[13px] text-zinc-800 dark:text-zinc-100">
        {sub.text_vi || <em className="text-zinc-400">(chưa dịch)</em>}
      </div>
      {hasReview && sub.review_reason && (
        <div className="text-[11px] text-amber-600 mt-1 italic">↳ {sub.review_reason}</div>
      )}

      {/* Inline issue list khi expand */}
      {expanded && hasIssue && (
        <div className="mt-2 pt-2 border-t border-red-200 dark:border-red-800/50 space-y-1.5">
          {issues.map(iss => (
            <IssueCard
              key={iss.id}
              issue={iss}
              onApply={() => onApply(iss.id)}
              onDismiss={() => onDismiss(iss.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}