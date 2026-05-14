/**
 * ChunkList v3 (redesign) — danh sách 3 tầng: Arc → Chunk → Scene + thoại 2 bản.
 *
 * Layout:
 *  ┌──────────────────────────────────────────────────────────────┐
 *  │ Sidebar (320px)          │  Main detail                       │
 *  │ ├ Arc 1 (5 chunks)       │  Chunk title + meta               │
 *  │ │   ├ Chunk 1.1 [88 d]   │  Scenes con                       │
 *  │ │   ├ Chunk 1.2 [120 d]  │  Thoại: hiển thị v1 + v2 song song │
 *  │ │   └ ...                │                                    │
 *  │ └ Arc 2 (4 chunks)       │                                    │
 *  └──────────────────────────────────────────────────────────────┘
 *
 * Giữ tên file SceneList.tsx để không break imports khác.
 */
import React, { useEffect, useMemo, useState } from 'react'
import { translateApi } from '../../api'
import api from '../../api'
import type {
  Chunk, Scene, StoryArc, PolishIssue, Subtitle,
} from '../../types'
import {
  EMOTION_LABELS, EMOTION_COLORS, ARC_TONE_LABELS,
} from '../../types'

interface Props {
  projectId: number
  chunks: Chunk[]
  scenes: Scene[]
  arcs: StoryArc[]
  issues: PolishIssue[]
  onIssuesUpdate: () => void
}

export default function ChunkList({
  projectId, chunks, scenes, arcs, issues, onIssuesUpdate,
}: Props) {
  const [selectedChunkId, setSelectedChunkId] = useState<number | null>(null)
  const [expandedArcs, setExpandedArcs] = useState<Set<number>>(new Set())
  const [filter, setFilter] = useState<'all' | 'pending' | 'done' | 'issue'>('all')

  const chunksByArc = useMemo(() => {
    const map: Record<number, Chunk[]> = {}
    for (const c of chunks) {
      if (!map[c.arc_index]) map[c.arc_index] = []
      map[c.arc_index].push(c)
    }
    return map
  }, [chunks])

  const issuesByChunk = useMemo(() => {
    const map: Record<number, number> = {}
    for (const iss of issues) {
      if (iss.resolved) continue
      const chunk = chunks.find(c =>
        iss.line_index >= c.start_line && iss.line_index <= c.end_line
      )
      if (chunk) map[chunk.id] = (map[chunk.id] || 0) + 1
    }
    return map
  }, [issues, chunks])

  const totalIssues = issues.filter(i => !i.resolved).length

  useEffect(() => {
    if (arcs.length > 0 && expandedArcs.size === 0) {
      setExpandedArcs(new Set(arcs.map(a => a.arc_index)))
    }
    // Auto select first chunk
    if (chunks.length > 0 && selectedChunkId === null) {
      setSelectedChunkId(chunks[0].id)
    }
  }, [arcs.length, chunks.length])

  if (chunks.length === 0) {
    return (
      <div className="p-8 text-center text-zinc-500">
        <div className="text-4xl mb-3">🎬</div>
        <div className="text-sm">Chưa có chunks. Chạy Stage 2 (Chia Chunks).</div>
      </div>
    )
  }

  let filteredChunks = chunks
  if (filter === 'pending') filteredChunks = filteredChunks.filter(c => c.status === 'pending')
  if (filter === 'done') filteredChunks = filteredChunks.filter(c => c.status === 'done' || c.status === 'translated')
  if (filter === 'issue') filteredChunks = filteredChunks.filter(c => (issuesByChunk[c.id] || 0) > 0)

  const selectedChunk = selectedChunkId ? chunks.find(c => c.id === selectedChunkId) : null
  const scenesOfSelected = selectedChunk
    ? scenes.filter(s => s.chunk_id === selectedChunk.id)
    : []

  function toggleArc(arcIndex: number) {
    setExpandedArcs(prev => {
      const ns = new Set(prev)
      if (ns.has(arcIndex)) ns.delete(arcIndex)
      else ns.add(arcIndex)
      return ns
    })
  }

  return (
    <div className="flex h-full">
      {/* SIDEBAR */}
      <div className="w-80 border-r border-zinc-200 dark:border-zinc-800 flex flex-col bg-zinc-50/50 dark:bg-zinc-950">
        <div className="p-3 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 space-y-2">
          <div className="flex gap-1 flex-wrap">
            <FilterChip active={filter === 'all'} onClick={() => setFilter('all')}>
              Tất cả ({chunks.length})
            </FilterChip>
            <FilterChip active={filter === 'pending'} onClick={() => setFilter('pending')}>
              ⏳ Chờ
            </FilterChip>
            <FilterChip active={filter === 'done'} onClick={() => setFilter('done')}>
              ✓ Xong
            </FilterChip>
            {totalIssues > 0 && (
              <FilterChip active={filter === 'issue'} onClick={() => setFilter('issue')}>
                🔧 ({totalIssues})
              </FilterChip>
            )}
          </div>
          <div className="text-[10px] text-zinc-500">
            {arcs.length} arcs · {chunks.length} chunks · {scenes.length} scenes
          </div>
        </div>

        <div className="flex-1 overflow-auto">
          {arcs.length === 0 ? (
            <div className="p-2 space-y-0.5">
              {filteredChunks.map(c => (
                <ChunkRow key={c.id} chunk={c}
                  issueCount={issuesByChunk[c.id] || 0}
                  selected={selectedChunkId === c.id}
                  onClick={() => setSelectedChunkId(c.id)} />
              ))}
            </div>
          ) : (
            arcs.map(arc => {
              const arcChunks = (chunksByArc[arc.arc_index] || [])
                .filter(c => filteredChunks.some(fc => fc.id === c.id))
              const isExpanded = expandedArcs.has(arc.arc_index)

              return (
                <div key={arc.id}>
                  {/* Arc header */}
                  <button
                    onClick={() => toggleArc(arc.arc_index)}
                    className="w-full px-3 py-2 flex items-center gap-2 hover:bg-zinc-100 dark:hover:bg-zinc-900 text-left border-b border-zinc-100 dark:border-zinc-800"
                  >
                    <span className="text-[10px] text-zinc-400 w-3">
                      {isExpanded ? '▼' : '▶'}
                    </span>
                    <span className="text-[10px] font-mono text-zinc-400 w-12">
                      #{arc.arc_index + 1}
                    </span>
                    <span className="text-[12px] font-semibold text-zinc-800 dark:text-zinc-200 flex-1 truncate">
                      {arc.title || `Arc ${arc.arc_index + 1}`}
                    </span>
                    <span className="text-[10px] text-zinc-400">
                      {arcChunks.length}
                    </span>
                  </button>

                  {isExpanded && (
                    <div className="pb-1">
                      {arcChunks.length === 0 ? (
                        <div className="px-3 py-1.5 text-[11px] text-zinc-400 italic ml-5">
                          (Trống)
                        </div>
                      ) : arcChunks.map(c => (
                        <ChunkRow key={c.id} chunk={c}
                          issueCount={issuesByChunk[c.id] || 0}
                          selected={selectedChunkId === c.id}
                          onClick={() => setSelectedChunkId(c.id)} />
                      ))}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* MAIN */}
      <div className="flex-1 overflow-auto bg-white dark:bg-zinc-950">
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
            issues={issues.filter(i =>
              !i.resolved &&
              i.line_index >= selectedChunk.start_line &&
              i.line_index <= selectedChunk.end_line
            )}
            onIssuesUpdate={onIssuesUpdate}
          />
        )}
      </div>
    </div>
  )
}

// ─── Sidebar pieces ────────────────────────────────────────────────────────

function FilterChip({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-2 py-1 text-[11px] rounded transition-all ${
        active
          ? 'bg-blue-600 text-white'
          : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'
      }`}
    >
      {children}
    </button>
  )
}

function ChunkRow({ chunk, issueCount, selected, onClick }: {
  chunk: Chunk; issueCount: number; selected: boolean; onClick: () => void
}) {
  const isDone = chunk.status === 'done' || chunk.status === 'translated'
  return (
    <button
      onClick={onClick}
      className={`w-full pl-7 pr-3 py-1.5 text-left text-[12px] flex items-center gap-2 border-l-2 ${
        selected
          ? 'bg-blue-50 dark:bg-blue-900/30 border-l-blue-500'
          : 'border-l-transparent hover:bg-zinc-100 dark:hover:bg-zinc-900'
      }`}
    >
      <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
        isDone ? 'bg-green-500' :
        chunk.status === 'error' ? 'bg-red-500' :
        'bg-zinc-300 dark:bg-zinc-600'
      }`} />
      <span className="font-mono text-[10px] text-zinc-400 flex-shrink-0 w-16">
        {chunk.start_line}-{chunk.end_line}
      </span>
      <span className="flex-1 truncate text-zinc-700 dark:text-zinc-300">
        {chunk.title || `Chunk ${chunk.chunk_index + 1}`}
      </span>
      {chunk.scene_count > 0 && (
        <span className="text-[9px] text-zinc-400">
          {chunk.scene_count}c
        </span>
      )}
      {issueCount > 0 && (
        <span className="text-[10px] px-1.5 rounded-full bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300">
          {issueCount}
        </span>
      )}
    </button>
  )
}

// ─── Main detail ───────────────────────────────────────────────────────────

function ChunkDetail({ projectId, chunk, scenes, arc, issues, onIssuesUpdate }: {
  projectId: number
  chunk: Chunk
  scenes: Scene[]
  arc?: StoryArc
  issues: PolishIssue[]
  onIssuesUpdate: () => void
}) {
  const [subs, setSubs] = useState<Subtitle[]>([])
  const [loading, setLoading] = useState(false)
  const [hideEmpty, setHideEmpty] = useState(false)

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

  const visible = hideEmpty ? subs.filter(s => s.original_text || s.text) : subs

  return (
    <div className="p-5 space-y-5 max-w-5xl">
      {/* Header */}
      <div className="pb-4 border-b border-zinc-200 dark:border-zinc-800">
        <div className="text-[10px] uppercase tracking-wider text-zinc-400 mb-1">
          {arc ? `Arc ${arc.arc_index + 1} · ${arc.title}` : ''}
          {arc?.emotional_tone && (
            <span className="ml-2 text-zinc-500 normal-case">
              · {ARC_TONE_LABELS[arc.emotional_tone] || arc.emotional_tone}
            </span>
          )}
        </div>
        <h2 className="text-xl font-semibold text-zinc-800 dark:text-zinc-100">
          {chunk.title || `Chunk ${chunk.chunk_index + 1}`}
        </h2>
        <div className="text-[12px] text-zinc-500 mt-1 flex items-center gap-3">
          <span>Dòng <strong className="text-zinc-700 dark:text-zinc-300">{chunk.start_line}-{chunk.end_line}</strong></span>
          <span>·</span>
          <span><strong className="text-zinc-700 dark:text-zinc-300">{chunk.line_count}</strong> dòng</span>
          {chunk.scene_count > 0 && (
            <>
              <span>·</span>
              <span><strong className="text-zinc-700 dark:text-zinc-300">{chunk.scene_count}</strong> scenes</span>
            </>
          )}
          <span>·</span>
          <StatusBadge status={chunk.status} />
        </div>
      </div>

      {/* Scenes con */}
      {scenes.length > 0 && (
        <section>
          <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-2">
            Scenes con ({scenes.length})
          </div>
          <div className="space-y-1.5">
            {scenes.map(sc => (
              <SceneCard key={sc.id} scene={sc} />
            ))}
          </div>
        </section>
      )}

      {/* Issues */}
      {issues.length > 0 && (
        <section>
          <div className="text-[11px] font-semibold text-red-500 uppercase tracking-widest mb-2">
            ⚠️ Vấn đề ({issues.length})
          </div>
          <div className="space-y-1.5">
            {issues.map(iss => (
              <div key={iss.id}
                className="border border-red-200 dark:border-red-900/50 rounded p-2.5 bg-red-50/50 dark:bg-red-950/30 text-[12px]">
                <div className="flex items-center gap-2 mb-1">
                  <span className="font-mono text-[10px] text-red-600 dark:text-red-400">
                    #{iss.line_index}
                  </span>
                  <span className="text-[10px] px-1.5 rounded bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300">
                    {iss.issue_type}
                  </span>
                  <span className="text-zinc-500 flex-1 truncate">{iss.description}</span>
                  <button
                    onClick={() => translateApi.dismissIssue(projectId, iss.id).then(onIssuesUpdate)}
                    className="text-[10px] text-zinc-400 hover:text-zinc-700 px-1">
                    ✕
                  </button>
                </div>
                <div className="text-zinc-700 dark:text-zinc-300 truncate">
                  {iss.current_text}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* Thoại — hiển thị 2 phiên bản v1/v2 */}
      <section>
        <div className="flex items-center justify-between mb-2">
          <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest">
            Thoại ({visible.length}/{subs.length})
          </div>
          <label className="flex items-center gap-1.5 text-[11px] text-zinc-500 cursor-pointer">
            <input type="checkbox" checked={hideEmpty} onChange={e => setHideEmpty(e.target.checked)} />
            Ẩn dòng rỗng
          </label>
        </div>

        {loading ? (
          <div className="text-[12px] text-zinc-400 italic">Đang tải...</div>
        ) : (
          <div className="border border-zinc-200 dark:border-zinc-800 rounded-lg overflow-hidden">
            {/* Table header */}
            <div className="grid grid-cols-[60px_140px_1fr_1fr_60px] gap-2 px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800 text-[10px] font-semibold text-zinc-500 uppercase tracking-widest">
              <div>#</div>
              <div>Nhân vật</div>
              <div className="flex items-center gap-1.5">
                <span className="px-1.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 normal-case text-[10px] font-bold">v1</span>
                Sát nghĩa
              </div>
              <div className="flex items-center gap-1.5">
                <span className="px-1.5 rounded bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 normal-case text-[10px] font-bold">v2</span>
                Thoát ý
              </div>
              <div>CPS</div>
            </div>

            {/* Rows */}
            <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
              {visible.map(s => (
                <SubtitleDualRow key={s.id} sub={s} projectId={projectId}
                  onUpdate={(updated) => setSubs(prev => prev.map(p => p.id === s.id ? { ...p, ...updated } : p))} />
              ))}
            </div>
          </div>
        )}
      </section>
    </div>
  )
}

function StatusBadge({ status }: { status: string }) {
  const color =
    status === 'done' || status === 'translated' ? 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300' :
    status === 'error' ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300' :
    status === 'pending' ? 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400' :
    'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${color}`}>
      {status}
    </span>
  )
}

function SceneCard({ scene }: { scene: Scene }) {
  return (
    <div className="border border-zinc-200 dark:border-zinc-700 rounded p-2 bg-zinc-50/30 dark:bg-zinc-900/30">
      <div className="flex items-center gap-2 text-[11px] flex-wrap">
        <span className="font-mono text-zinc-400">
          {scene.start_line}-{scene.end_line}
        </span>
        <span
          className="px-1.5 py-0.5 rounded font-medium text-[10px]"
          style={{
            backgroundColor: (EMOTION_COLORS[scene.emotion_primary] || '#888') + '33',
            color: EMOTION_COLORS[scene.emotion_primary] || '#888',
          }}
        >
          {EMOTION_LABELS[scene.emotion_primary] || scene.emotion_primary}
        </span>
        {scene.is_hook && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 font-medium">
            🎯 HOOK
          </span>
        )}
        {scene.is_emotion_peak && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-rose-100 dark:bg-rose-900/40 text-rose-700 dark:text-rose-300 font-medium">
            🔥 PEAK
          </span>
        )}
        {scene.location && (
          <span className="text-zinc-500">@ {scene.location}</span>
        )}
        <div className="flex-1" />
        <span className="text-zinc-500 text-[11px]">
          {scene.characters_present.slice(0, 4).join(' · ')}
          {scene.characters_present.length > 4 && ` +${scene.characters_present.length - 4}`}
        </span>
      </div>
    </div>
  )
}

function SubtitleDualRow({ sub, projectId, onUpdate }: {
  sub: Subtitle
  projectId: number
  onUpdate: (u: Partial<Subtitle>) => void
}) {
  const speaker = sub.character?.name || sub.speaker_zh || '?'
  const v1 = sub.text_v1 || ''
  const v2 = sub.text_v2 || ''
  const hasV2 = !!v2 && v2 !== v1
  const selectedVariant = sub.variant_selected || 1
  const cps = sub.cps_value
  const cpsClass = cps && cps > 22 ? 'text-red-500 font-semibold' : 'text-zinc-400'

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

  return (
    <div className="grid grid-cols-[60px_140px_1fr_1fr_60px] gap-2 px-3 py-2 text-[12px] hover:bg-zinc-50/50 dark:hover:bg-zinc-900/30">
      {/* # */}
      <div className="font-mono text-zinc-400 text-[11px]">
        {sub.index}
      </div>

      {/* Speaker + meta */}
      <div className="min-w-0">
        <div className="font-medium text-zinc-700 dark:text-zinc-300 truncate">
          {speaker}
        </div>
        {sub.emotion && (
          <div className="text-[10px] truncate"
            style={{ color: EMOTION_COLORS[sub.emotion] || '#888' }}>
            {EMOTION_LABELS[sub.emotion] || sub.emotion}
          </div>
        )}
        {sub.original_text && (
          <div className="text-[10px] text-zinc-400 truncate font-mono mt-0.5">
            {sub.original_text}
          </div>
        )}
      </div>

      {/* v1 */}
      <div
        onClick={() => v1 && switchVariant(1)}
        className={`px-2 py-1 rounded cursor-pointer transition-all ${
          selectedVariant === 1
            ? 'bg-blue-50 dark:bg-blue-900/20 border border-blue-300 dark:border-blue-700'
            : 'border border-transparent hover:border-zinc-200 dark:hover:border-zinc-700'
        }`}
      >
        {v1 ? (
          <span className="text-zinc-800 dark:text-zinc-100">{v1}</span>
        ) : (
          <span className="text-zinc-400 italic">—</span>
        )}
      </div>

      {/* v2 */}
      <div
        onClick={() => hasV2 && switchVariant(2)}
        className={`px-2 py-1 rounded transition-all ${
          hasV2 ? 'cursor-pointer' : ''
        } ${
          selectedVariant === 2 && hasV2
            ? 'bg-purple-50 dark:bg-purple-900/20 border border-purple-300 dark:border-purple-700'
            : hasV2
              ? 'border border-transparent hover:border-zinc-200 dark:hover:border-zinc-700'
              : 'border border-dashed border-zinc-200 dark:border-zinc-800'
        }`}
      >
        {hasV2 ? (
          <span className="text-zinc-800 dark:text-zinc-100">{v2}</span>
        ) : (
          <span className="text-zinc-300 dark:text-zinc-600 italic text-[11px]">(không có v2)</span>
        )}
      </div>

      {/* CPS */}
      <div className={`text-right text-[11px] font-mono ${cpsClass}`}>
        {cps != null ? cps.toFixed(1) : '—'}
      </div>
    </div>
  )
}
