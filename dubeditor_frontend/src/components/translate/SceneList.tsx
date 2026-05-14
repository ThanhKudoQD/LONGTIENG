/**
 * ChunkList v3 (final redesign) — UI rõ ràng theo phong cách Bible mới.
 *
 *  - Outer card lớn có border + shadow
 *  - Mỗi block (header / issues / thoại) là card riêng
 *  - Text 13-14px, hàng cao thoáng, border-bottom rõ giữa các thoại
 *  - 2 phiên bản v1/v2 song song với floating label
 *
 * Giữ tên file SceneList.tsx.
 */
import React, { useEffect, useMemo, useState } from 'react'
import api, { translateApi } from '../../api'
import type {
  Chunk, Scene, StoryArc, PolishIssue, Subtitle,
} from '../../types'
import {
  EMOTION_LABELS, ARC_TONE_LABELS,
} from '../../types'

interface Props {
  projectId: number
  chunks: Chunk[]
  scenes: Scene[]
  arcs: StoryArc[]
  issues: PolishIssue[]
  onIssuesUpdate: () => void
}

// ─── Emotion → tag ngắn cho sidebar ──────────────────────────────────────────

const EMOTION_SHORT: Record<string, string> = {
  neutral: 'Bình', happy: 'Vui', sad: 'Buồn', angry: 'Giận',
  cold: 'Lạnh', tense: 'Căng', intimate: 'Thân', fearful: 'Sợ',
  sarcastic: 'Mỉa', shocked: 'Sốc', determined: 'Quyết',
  regretful: 'Hối', humorous: 'Hài', threatening: 'Đe dọa',
}

function emoBadgeClass(emotion: string): string {
  const m: Record<string, string> = {
    neutral: 'bg-zinc-100 text-zinc-600 border-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700',
    happy: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-800',
    sad: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/40 dark:text-blue-300 dark:border-blue-800',
    angry: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/40 dark:text-red-300 dark:border-red-800',
    cold: 'bg-slate-50 text-slate-700 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700',
    tense: 'bg-orange-50 text-orange-700 border-orange-200 dark:bg-orange-900/40 dark:text-orange-300 dark:border-orange-800',
    intimate: 'bg-pink-50 text-pink-700 border-pink-200 dark:bg-pink-900/40 dark:text-pink-300 dark:border-pink-800',
    fearful: 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-900/40 dark:text-purple-300 dark:border-purple-800',
    sarcastic: 'bg-cyan-50 text-cyan-700 border-cyan-200 dark:bg-cyan-900/40 dark:text-cyan-300 dark:border-cyan-800',
    shocked: 'bg-orange-50 text-orange-800 border-orange-200 dark:bg-orange-900/40 dark:text-orange-300 dark:border-orange-800',
    determined: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-300 dark:border-emerald-800',
    regretful: 'bg-indigo-50 text-indigo-700 border-indigo-200 dark:bg-indigo-900/40 dark:text-indigo-300 dark:border-indigo-800',
    humorous: 'bg-lime-50 text-lime-700 border-lime-200 dark:bg-lime-900/40 dark:text-lime-300 dark:border-lime-800',
    threatening: 'bg-red-50 text-red-800 border-red-200 dark:bg-red-900/40 dark:text-red-300 dark:border-red-800',
  }
  return m[emotion] || m.neutral
}

export default function ChunkList({
  projectId, chunks, scenes, arcs, issues, onIssuesUpdate,
}: Props) {
  const [selectedChunkId, setSelectedChunkId] = useState<number | null>(null)
  const [filter, setFilter] = useState<'all' | 'hook' | 'peak' | 'issue'>('all')
  const [arcFilter, setArcFilter] = useState<number | null>(null)

  const issuesByChunk = useMemo(() => {
    const map: Record<number, PolishIssue[]> = {}
    for (const iss of issues) {
      if (iss.resolved) continue
      const chunk = chunks.find(c =>
        iss.line_index >= c.start_line && iss.line_index <= c.end_line
      )
      if (chunk) {
        if (!map[chunk.id]) map[chunk.id] = []
        map[chunk.id].push(iss)
      }
    }
    return map
  }, [issues, chunks])

  const issuesByArc = useMemo(() => {
    const map: Record<number, number> = {}
    for (const chunkId in issuesByChunk) {
      const chunk = chunks.find(c => c.id === parseInt(chunkId))
      if (chunk) {
        map[chunk.arc_index] = (map[chunk.arc_index] || 0) +
          issuesByChunk[chunkId].length
      }
    }
    return map
  }, [issuesByChunk, chunks])

  const emotionByChunk = useMemo(() => {
    const map: Record<number, string> = {}
    for (const c of chunks) {
      const cScenes = scenes.filter(s => s.chunk_id === c.id)
      map[c.id] = cScenes.length > 0 ? (cScenes[0].emotion_primary || 'neutral') : 'neutral'
    }
    return map
  }, [chunks, scenes])

  const hookChunkIds = useMemo(() => {
    const set = new Set<number>()
    for (const s of scenes) {
      if (s.is_hook && s.chunk_id) set.add(s.chunk_id)
    }
    return set
  }, [scenes])

  const peakChunkIds = useMemo(() => {
    const set = new Set<number>()
    for (const s of scenes) {
      if (s.is_emotion_peak && s.chunk_id) set.add(s.chunk_id)
    }
    return set
  }, [scenes])

  useEffect(() => {
    if (chunks.length > 0 && selectedChunkId === null) {
      setSelectedChunkId(chunks[0].id)
    }
  }, [chunks.length])

  if (chunks.length === 0) {
    return (
      <div className="p-8">
        <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm p-12 text-center">
          <div className="text-5xl mb-4">🎬</div>
          <div className="text-zinc-500 dark:text-zinc-400">Chưa có chunks. Chạy Stage 2 (Chia Chunks).</div>
        </div>
      </div>
    )
  }

  let filteredChunks = chunks
  if (arcFilter !== null) filteredChunks = filteredChunks.filter(c => c.arc_index === arcFilter)
  if (filter === 'hook') filteredChunks = filteredChunks.filter(c => hookChunkIds.has(c.id))
  if (filter === 'peak') filteredChunks = filteredChunks.filter(c => peakChunkIds.has(c.id))
  if (filter === 'issue') filteredChunks = filteredChunks.filter(c => (issuesByChunk[c.id]?.length || 0) > 0)

  const totalIssues = issues.filter(i => !i.resolved).length
  const selectedChunk = selectedChunkId ? chunks.find(c => c.id === selectedChunkId) : null
  const scenesOfSelected = selectedChunk
    ? scenes.filter(s => s.chunk_id === selectedChunk.id)
    : []

  return (
    <div className="flex h-full">
      {/* SIDEBAR */}
      <div className="w-[360px] border-r border-zinc-200 dark:border-zinc-800 flex flex-col bg-white dark:bg-zinc-900">
        {/* Sidebar header */}
        <div className="p-3 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/70 space-y-2">
          <div className="flex gap-1 flex-wrap">
            <FilterChip active={filter === 'all'} onClick={() => setFilter('all')}>
              Tất cả ({chunks.length})
            </FilterChip>
            <FilterChip active={filter === 'hook'} onClick={() => setFilter('hook')}>
              🎯 Hook ({hookChunkIds.size})
            </FilterChip>
            <FilterChip active={filter === 'peak'} onClick={() => setFilter('peak')}>
              🔥 Peak ({peakChunkIds.size})
            </FilterChip>
            {totalIssues > 0 && (
              <FilterChip active={filter === 'issue'} onClick={() => setFilter('issue')} variant="warn">
                ⚠ Vấn đề ({totalIssues})
              </FilterChip>
            )}
          </div>
          {arcs.length > 0 && (
            <select
              value={arcFilter ?? ''}
              onChange={e => setArcFilter(e.target.value === '' ? null : parseInt(e.target.value))}
              className="input w-full text-[12px]"
            >
              <option value="">Tất cả arcs</option>
              {arcs.map(a => (
                <option key={a.id} value={a.arc_index}>
                  Arc {a.arc_index + 1}: {a.title} {issuesByArc[a.arc_index] ? `⚠️${issuesByArc[a.arc_index]}` : ''}
                </option>
              ))}
            </select>
          )}
        </div>

        <div className="flex-1 overflow-auto bg-zinc-50/30 dark:bg-zinc-950/30">
          {filteredChunks.map((c, idx) => (
            <ChunkSidebarRow
              key={c.id}
              chunk={c}
              indexNum={idx + 1}
              emotion={emotionByChunk[c.id] || 'neutral'}
              isHook={hookChunkIds.has(c.id)}
              isPeak={peakChunkIds.has(c.id)}
              issueCount={issuesByChunk[c.id]?.length || 0}
              selected={selectedChunkId === c.id}
              onClick={() => setSelectedChunkId(c.id)}
            />
          ))}
        </div>
      </div>

      {/* MAIN */}
      <div className="flex-1 overflow-auto bg-[#FAFAF7] dark:bg-zinc-950/30">
        {!selectedChunk ? (
          <div className="p-8 text-center text-zinc-500">
            <div className="text-3xl mb-3">📖</div>
            <div className="text-sm">Chọn 1 chunk từ sidebar</div>
          </div>
        ) : (
          <ChunkDetail
            projectId={projectId}
            chunk={selectedChunk}
            scenes={scenesOfSelected}
            arc={arcs.find(a => a.arc_index === selectedChunk.arc_index)}
            issues={issuesByChunk[selectedChunk.id] || []}
            onIssuesUpdate={onIssuesUpdate}
            chunkPosInArc={
              chunks
                .filter(c => c.arc_index === selectedChunk.arc_index)
                .findIndex(c => c.id === selectedChunk.id) + 1
            }
          />
        )}
      </div>
    </div>
  )
}

// ─── Sidebar pieces ────────────────────────────────────────────────────────

function FilterChip({ active, onClick, children, variant = 'normal' }: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
  variant?: 'normal' | 'warn'
}) {
  const baseColor = variant === 'warn'
    ? (active
        ? 'bg-amber-500 text-white border-amber-500'
        : 'bg-white text-amber-700 border-amber-200 hover:bg-amber-50 dark:bg-zinc-800 dark:text-amber-300 dark:border-amber-900')
    : (active
        ? 'bg-blue-600 text-white border-blue-600'
        : 'bg-white text-zinc-600 border-zinc-200 hover:bg-zinc-50 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700 dark:hover:bg-zinc-700')
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 text-[11px] rounded-md border font-medium transition-all ${baseColor}`}
    >
      {children}
    </button>
  )
}

function ChunkSidebarRow({ chunk, indexNum, emotion, isHook, isPeak, issueCount, selected, onClick }: {
  chunk: Chunk
  indexNum: number
  emotion: string
  isHook: boolean
  isPeak: boolean
  issueCount: number
  selected: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left border-b-2 border-zinc-200 dark:border-zinc-800 px-3 py-3 transition-all ${
        selected
          ? 'bg-white dark:bg-zinc-900 border-l-[4px] border-l-blue-500 shadow-sm'
          : 'border-l-[4px] border-l-transparent hover:bg-white dark:hover:bg-zinc-900'
      }`}
    >
      {/* Row 1: # range + badges */}
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-[12px] font-mono font-semibold text-zinc-600 dark:text-zinc-400 flex-shrink-0">
          #{indexNum}
        </span>
        <span className="text-[12px] font-mono font-semibold text-zinc-500 dark:text-zinc-500">
          L{chunk.start_line}-{chunk.end_line}
        </span>
        <div className="flex-1" />
        {isHook && (
          <span className="text-[11px] px-1.5 py-0.5 rounded border bg-amber-50 text-amber-700 border-amber-300 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-700 font-bold">
            🎯
          </span>
        )}
        {isPeak && (
          <span className="text-[11px] px-1.5 py-0.5 rounded border bg-rose-50 text-rose-700 border-rose-300 dark:bg-rose-900/40 dark:text-rose-300 dark:border-rose-700 font-bold">
            🔥
          </span>
        )}
        <span className={`text-[11px] px-2 py-0.5 rounded border font-bold ${emoBadgeClass(emotion)}`}>
          {EMOTION_SHORT[emotion] || emotion}
        </span>
        {issueCount > 0 && (
          <span className="text-[11px] px-1.5 py-0.5 rounded border bg-amber-50 text-amber-700 border-amber-300 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-700 font-bold">
            ⚠ {issueCount}
          </span>
        )}
      </div>

      {/* Row 2: title — to + đậm */}
      <div className="text-[14px] font-semibold text-zinc-900 dark:text-zinc-100 leading-snug line-clamp-2">
        {chunk.title || `Chunk ${chunk.chunk_index + 1}`}
      </div>
    </button>
  )
}

// ─── Main detail ───────────────────────────────────────────────────────────

function ChunkDetail({ projectId, chunk, scenes, arc, issues, onIssuesUpdate, chunkPosInArc }: {
  projectId: number
  chunk: Chunk
  scenes: Scene[]
  arc?: StoryArc
  issues: PolishIssue[]
  onIssuesUpdate: () => void
  chunkPosInArc: number
}) {
  const [subs, setSubs] = useState<Subtitle[]>([])
  const [loading, setLoading] = useState(false)
  const [showOnlyIssues, setShowOnlyIssues] = useState(false)

  useEffect(() => {
    setLoading(true)
    api.get<Subtitle[]>(`/subtitles/project/${projectId}`)
      .then(r => {
        const filtered = r.data.filter(s =>
          s.index >= chunk.start_line && s.index <= chunk.end_line
        )
        setSubs(filtered)
      })
      .catch(e => console.error('Load subs failed', e))
      .finally(() => setLoading(false))
  }, [chunk.id, projectId])

  const issueLineSet = useMemo(() => new Set(issues.map(i => i.line_index)), [issues])
  const visible = showOnlyIssues
    ? subs.filter(s => issueLineSet.has(s.index))
    : subs

  const emotionChain = scenes.map(s => s.emotion_primary).filter(Boolean)
  const uniqueEmotions: string[] = []
  for (const e of emotionChain) {
    if (uniqueEmotions[uniqueEmotions.length - 1] !== e) uniqueEmotions.push(e)
  }

  return (
    <div className="p-5 space-y-4 max-w-6xl">

      {/* HEADER CARD */}
      <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm overflow-hidden">
        {/* Header strip */}
        <div className="px-5 py-2.5 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/70 flex items-center gap-3">
          <span className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider">
            Scene #{chunkPosInArc}
          </span>
          <span className="text-[11px] text-zinc-400">·</span>
          <span className="text-[11px] font-mono text-zinc-500">
            Dòng {chunk.start_line}–{chunk.end_line}
          </span>
          <span className="text-[11px] text-zinc-400">·</span>
          <span className="text-[11px] text-zinc-500">
            {chunk.line_count} lines
          </span>
          <div className="flex-1" />
          {issues.length > 0 && (
            <span className="text-[11px] px-2 py-0.5 rounded-md border bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-800 font-medium">
              ⚠ {issues.length} vấn đề
            </span>
          )}
        </div>

        {/* Title + emotion chain */}
        <div className="p-5">
          <h2 className="text-xl font-semibold text-zinc-800 dark:text-zinc-100 flex items-center gap-2 mb-2">
            <span className="text-rose-500">📍</span>
            <span>{chunk.title || `Chunk ${chunk.chunk_index + 1}`}</span>
          </h2>

          {arc && (
            <div className="text-[12px] text-zinc-500 mb-3 flex items-center gap-2">
              <span className="text-zinc-400">Arc:</span>
              <strong className="text-zinc-700 dark:text-zinc-300">{arc.title}</strong>
              {arc.emotional_tone && (
                <>
                  <span className="text-zinc-400">·</span>
                  <span className="text-zinc-600 dark:text-zinc-400">
                    {ARC_TONE_LABELS[arc.emotional_tone] || arc.emotional_tone}
                  </span>
                </>
              )}
            </div>
          )}

          {uniqueEmotions.length > 0 && (
            <div className="flex items-center gap-1.5 flex-wrap">
              <span className="text-[11px] text-zinc-500 uppercase tracking-wider font-semibold mr-1">
                Cảm xúc:
              </span>
              {uniqueEmotions.map((e, i) => (
                <React.Fragment key={i}>
                  {i > 0 && <span className="text-zinc-300 dark:text-zinc-600">→</span>}
                  <span className={`px-2 py-0.5 rounded-md border text-[12px] font-medium ${emoBadgeClass(e)}`}>
                    {EMOTION_LABELS[e] || e}
                  </span>
                </React.Fragment>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ISSUES CARD */}
      {issues.length > 0 && (
        <div className="bg-white dark:bg-zinc-900 rounded-xl border border-amber-300 dark:border-amber-800/60 shadow-sm overflow-hidden">
          <div className="px-5 py-2.5 border-b border-amber-200 dark:border-amber-900/50 bg-amber-50 dark:bg-amber-950/30 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-500" />
            <span className="text-[11px] font-bold text-amber-700 dark:text-amber-300 uppercase tracking-wider">
              Vấn đề trong cảnh
            </span>
            <span className="text-[11px] text-amber-700 dark:text-amber-400 opacity-70">
              ({issues.length})
            </span>
          </div>
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {issues.map(iss => (
              <IssueRow
                key={iss.id}
                issue={iss}
                onApply={() => translateApi.applyIssue(projectId, iss.id).then(onIssuesUpdate)}
                onDismiss={() => translateApi.dismissIssue(projectId, iss.id).then(onIssuesUpdate)}
              />
            ))}
          </div>
        </div>
      )}

      {/* DIALOGS CARD */}
      <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-800 shadow-sm overflow-hidden">
        <div className="px-5 py-2.5 border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50/60 dark:bg-zinc-900/70 flex items-center gap-3">
          <span className="w-2 h-2 rounded-full bg-blue-500" />
          <span className="text-[11px] font-bold text-zinc-500 uppercase tracking-wider">
            Thoại trong cảnh
          </span>
          <span className="text-[11px] text-zinc-500 opacity-70">
            ({visible.length}/{subs.length})
          </span>
          <div className="flex-1" />
          <button
            onClick={() => setShowOnlyIssues(false)}
            className={`text-[11px] px-2.5 py-1 rounded-md border font-medium transition-all ${
              !showOnlyIssues
                ? 'bg-blue-600 text-white border-blue-600'
                : 'bg-white text-zinc-600 border-zinc-200 hover:bg-zinc-50 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700'
            }`}
          >
            Tất cả
          </button>
          {issues.length > 0 && (
            <button
              onClick={() => setShowOnlyIssues(true)}
              className={`text-[11px] px-2.5 py-1 rounded-md border font-medium transition-all ${
                showOnlyIssues
                  ? 'bg-amber-500 text-white border-amber-500'
                  : 'bg-white text-amber-700 border-amber-200 hover:bg-amber-50 dark:bg-zinc-800 dark:text-amber-300 dark:border-amber-900'
              }`}
            >
              ⚠ Chỉ có vấn đề ({issues.length})
            </button>
          )}
        </div>

        {loading ? (
          <div className="p-8 text-[12px] text-zinc-400 italic text-center">Đang tải...</div>
        ) : (
          <div className="divide-y divide-zinc-200 dark:divide-zinc-800">
            {visible.map(s => (
              <SubtitleDualRow
                key={s.id}
                sub={s}
                projectId={projectId}
                hasIssue={issueLineSet.has(s.index)}
                onUpdate={(u) => setSubs(prev => prev.map(p => p.id === s.id ? { ...p, ...u } : p))}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── Issue row ─────────────────────────────────────────────────────────────

function IssueRow({ issue, onApply, onDismiss }: {
  issue: PolishIssue
  onApply: () => void
  onDismiss: () => void
}) {
  const conf = (issue.confidence || '').toLowerCase()
  const confLabel = (conf === 'h' || conf === 'high') ? 'high'
    : (conf === 'm' || conf === 'mid') ? 'mid' : 'low'
  const confClass = (conf === 'h' || conf === 'high')
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-300 dark:border-emerald-800'
    : (conf === 'm' || conf === 'mid')
    ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/40 dark:text-blue-300 dark:border-blue-800'
    : 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-800'

  return (
    <div className="px-5 py-3.5 hover:bg-zinc-50/60 dark:hover:bg-zinc-900/40">
      <div className="flex items-center gap-2 mb-2 text-[11px]">
        <span className="font-mono text-zinc-500">⚠ line #{issue.line_index}</span>
        <span className={`px-1.5 py-0.5 rounded border font-medium ${confClass}`}>
          {issue.issue_type}
        </span>
        <span className={`px-1.5 py-0.5 rounded border font-medium ${confClass}`}>
          {confLabel}
        </span>
        <div className="flex-1" />
        {issue.suggested_text && (
          <button onClick={onApply}
            className="px-3 py-1 text-[11px] rounded-md bg-emerald-600 hover:bg-emerald-700 text-white font-medium transition-colors">
            ✓ Áp dụng
          </button>
        )}
        <button onClick={onDismiss}
          className="px-3 py-1 text-[11px] rounded-md text-zinc-600 border border-zinc-200 hover:bg-zinc-50 dark:text-zinc-400 dark:border-zinc-700 dark:hover:bg-zinc-800 transition-colors">
          ✕ Bỏ qua
        </button>
      </div>
      <div className="text-[13px] text-zinc-700 dark:text-zinc-300 mb-2">
        {issue.description}
      </div>
      {issue.current_text && (
        <div className="text-[13px] text-red-700 dark:text-red-400 line-through opacity-80 mb-1 px-2 py-1 bg-red-50/50 dark:bg-red-950/20 rounded border border-red-100 dark:border-red-900/40">
          − {issue.current_text}
        </div>
      )}
      {issue.suggested_text && (
        <div className="text-[13px] text-emerald-700 dark:text-emerald-400 px-2 py-1 bg-emerald-50/50 dark:bg-emerald-950/20 rounded border border-emerald-100 dark:border-emerald-900/40">
          + {issue.suggested_text}
        </div>
      )}
      {issue.evidence && (
        <div className="text-[11px] text-zinc-500 italic mt-2 border-l-2 border-zinc-300 dark:border-zinc-700 pl-2">
          💡 {issue.evidence}
        </div>
      )}
    </div>
  )
}

// ─── Dual variant row ──────────────────────────────────────────────────────

function SubtitleDualRow({ sub, projectId, hasIssue, onUpdate }: {
  sub: Subtitle
  projectId: number
  hasIssue: boolean
  onUpdate: (u: Partial<Subtitle>) => void
}) {
  const speaker = sub.character?.name || sub.speaker_zh || '?'
  const v1 = sub.text_v1 || sub.text || ''
  const v2 = sub.text_v2 || ''
  const hasV2 = !!v2 && v2 !== v1
  const selectedVariant = sub.variant_selected || 1
  const cps = sub.cps_value
  const cpsOver = cps != null && cps > 22

  const conf = (sub.speaker_confidence || '').toLowerCase()
  const confLetter = conf === 'h' || conf === 'high' ? 'h'
    : conf === 'm' || conf === 'mid' ? 'm' : 'l'
  const confClass = (conf === 'h' || conf === 'high')
    ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/40 dark:text-emerald-300 dark:border-emerald-800'
    : (conf === 'm' || conf === 'mid')
    ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/40 dark:text-blue-300 dark:border-blue-800'
    : 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-800'

  async function switchVariant(v: 1 | 2) {
    try {
      const res = await translateApi.selectVariant(projectId, sub.id, v)
      onUpdate({
        text: res.text,
        variant_selected: v,
        cps_value: res.cps_value,
      })
    } catch (e) {
      console.warn(e)
    }
  }

  const emotion = sub.emotion || 'neutral'

  return (
    <div className={`px-5 py-3 ${hasIssue ? 'bg-amber-50/40 dark:bg-amber-950/10' : ''} hover:bg-zinc-50/60 dark:hover:bg-zinc-900/40 transition-colors`}>
      {/* Header row */}
      <div className="flex items-center gap-2 mb-2 text-[11px] flex-wrap">
        <span className="font-mono text-zinc-400 font-medium w-8">
          #{sub.index}
        </span>
        <span className="text-[13px] font-semibold text-zinc-800 dark:text-zinc-200">
          {speaker}
        </span>
        {sub.speaker_confidence && (
          <span className={`px-1.5 py-0.5 rounded border font-medium text-[10px] ${confClass}`}>
            [{confLetter}]
          </span>
        )}
        <span className={`px-1.5 py-0.5 rounded border font-medium ${emoBadgeClass(emotion)}`}>
          {EMOTION_LABELS[emotion] || emotion}
          {sub.intensity ? `·${sub.intensity}` : ''}
        </span>
        {cps != null && (
          <span className={`px-1.5 py-0.5 rounded border font-medium font-mono ${
            cpsOver
              ? 'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/40 dark:text-red-300 dark:border-red-800'
              : 'bg-zinc-50 text-zinc-600 border-zinc-200 dark:bg-zinc-800 dark:text-zinc-400 dark:border-zinc-700'
          }`}>
            CPS {cps.toFixed(1)}
          </span>
        )}
        {hasIssue && (
          <span className="px-1.5 py-0.5 rounded border font-medium bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/40 dark:text-amber-300 dark:border-amber-800">
            ⚠ vấn đề
          </span>
        )}
      </div>

      {/* Original TQ — to + đậm để dễ đọc */}
      {sub.original_text && (
        <div className="text-[14px] text-zinc-700 dark:text-zinc-300 mb-2 pl-8 font-medium leading-relaxed">
          {sub.original_text}
        </div>
      )}

      {/* v1 + v2 */}
      <div className="pl-8 grid grid-cols-2 gap-3">
        {/* v1 */}
        <div
          onClick={() => v1 && switchVariant(1)}
          className={`relative px-3 py-2.5 rounded-lg border-2 cursor-pointer transition-all ${
            selectedVariant === 1
              ? 'bg-blue-50/70 dark:bg-blue-900/20 border-blue-400 dark:border-blue-600 shadow-sm'
              : 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700 hover:border-zinc-300 dark:hover:border-zinc-600'
          }`}
        >
          <span className={`absolute -top-2 left-2 px-1.5 text-[10px] font-bold rounded ${
            selectedVariant === 1
              ? 'bg-blue-600 text-white'
              : 'bg-white dark:bg-zinc-900 text-blue-600 dark:text-blue-400 border border-blue-300 dark:border-blue-700'
          }`}>
            v1 SÁT NGHĨA
          </span>
          {v1 ? (
            <span className="text-[14px] text-zinc-800 dark:text-zinc-100 leading-snug">{v1}</span>
          ) : (
            <span className="text-[12px] text-zinc-400 italic">(chưa có)</span>
          )}
        </div>

        {/* v2 */}
        <div
          onClick={() => hasV2 && switchVariant(2)}
          className={`relative px-3 py-2.5 rounded-lg border-2 transition-all ${
            hasV2 ? 'cursor-pointer' : ''
          } ${
            selectedVariant === 2 && hasV2
              ? 'bg-purple-50/70 dark:bg-purple-900/20 border-purple-400 dark:border-purple-600 shadow-sm'
              : hasV2
                ? 'bg-white dark:bg-zinc-900 border-zinc-200 dark:border-zinc-700 hover:border-zinc-300 dark:hover:border-zinc-600'
                : 'bg-zinc-50/50 dark:bg-zinc-900/30 border-dashed border-zinc-200 dark:border-zinc-800 opacity-60'
          }`}
        >
          <span className={`absolute -top-2 left-2 px-1.5 text-[10px] font-bold rounded ${
            selectedVariant === 2 && hasV2
              ? 'bg-purple-600 text-white'
              : hasV2
                ? 'bg-white dark:bg-zinc-900 text-purple-600 dark:text-purple-400 border border-purple-300 dark:border-purple-700'
                : 'bg-white dark:bg-zinc-900 text-zinc-400 border border-zinc-200 dark:border-zinc-700'
          }`}>
            v2 THOÁT Ý
          </span>
          {hasV2 ? (
            <span className="text-[14px] text-zinc-800 dark:text-zinc-100 leading-snug">{v2}</span>
          ) : (
            <span className="text-[12px] text-zinc-400 italic">(không có)</span>
          )}
        </div>
      </div>
    </div>
  )
}