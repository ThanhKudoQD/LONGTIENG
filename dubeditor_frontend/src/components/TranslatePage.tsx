/**
 * TranslatePage v2
 *
 * Trang điều khiển pipeline dịch 5-stage. Layout:
 *
 *  ┌─────────────────────────────────────────────────────────────┐
 *  │  Header: ← Back · Project name · Status badge                │
 *  ├─────────────────────────────────────────────────────────────┤
 *  │  [Cấu hình] · [▶ Bắt đầu] · [Hủy] · [Reset]                 │
 *  │  Progress bar + log SSE realtime                            │
 *  ├─────────────────────────────────────────────────────────────┤
 *  │  Tabs: [Tổng quan] [Bible] [Phân cảnh] [Vấn đề] [Logs]      │
 *  │                                                              │
 *  │  Content theo tab                                            │
 *  └─────────────────────────────────────────────────────────────┘
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import api, { translateApi, openProgressSSE, type ProgressMessage, type LLMCallMessage } from '../api'
import type {
  Project, TranslateStatus, Bible, Scene, StoryArc,
  PolishIssue, GenrePackInfo, TranslateConfig,
} from '../types'
import {
  EMOTION_LABELS, EMOTION_COLORS, ROLE_LABELS,
  GENRE_MAIN_LABELS, GENRE_SUB_LABELS, ISSUE_TYPE_LABELS,
} from '../types'

import ConfigPanel from './translate/ConfigPanel'
import BibleViewer from './translate/BibleViewer'
import SceneList from './translate/SceneList'
import SubtitlesView from './translate/SubtitlesView'
import IssueQueue from './translate/IssueQueue'
import ProgressLog from './translate/ProgressLog'

type Tab = 'overview' | 'bible' | 'scenes' | 'subtitles' | 'issues' | 'logs'

export default function TranslatePage({
  projectId, onBack,
}: { projectId: number; onBack: () => void }) {

  const [project, setProject] = useState<Project | null>(null)
  const [status, setStatus] = useState<TranslateStatus | null>(null)
  const [bible, setBible] = useState<Bible | null>(null)
  const [scenes, setScenes] = useState<Scene[]>([])
  const [arcs, setArcs] = useState<StoryArc[]>([])
  const [issues, setIssues] = useState<PolishIssue[]>([])
  const [genrePacks, setGenrePacks] = useState<GenrePackInfo[]>([])

  const [tab, setTab] = useState<Tab>('overview')
  const [showConfig, setShowConfig] = useState(false)

  // Progress events feed
  const [progressEvents, setProgressEvents] = useState<ProgressMessage[]>([])
  const [llmCalls, setLlmCalls] = useState<LLMCallMessage[]>([])
  const [currentProgress, setCurrentProgress] = useState(0)
  const [currentMessage, setCurrentMessage] = useState('')
  const [isRunning, setIsRunning] = useState(false)
  const sseCloseRef = useRef<(() => void) | null>(null)

  // ─── Load initial data ────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [proj, st, bib, scs, ars, iss, packs] = await Promise.all([
          api.get<Project>(`/projects/${projectId}`).then(r => r.data),
          translateApi.getStatus(projectId),
          translateApi.getBible(projectId).catch(() => null),
          translateApi.listScenes(projectId).catch(() => []),
          translateApi.listStoryArcs(projectId).catch(() => []),
          translateApi.listIssues(projectId, { resolved: false }).catch(() => []),
          translateApi.listGenrePacks().catch(() => []),
        ])
        if (cancelled) return
        setProject(proj)
        setStatus(st)
        setBible(bib)
        setScenes(scs)
        setArcs(ars)
        setIssues(iss)
        setGenrePacks(packs)
        setCurrentProgress(st.progress)
        setIsRunning(st.status === 'running')
      } catch (e: any) {
        console.error('[Translate] load error', e)
      }
    }
    load()
    return () => { cancelled = true }
  }, [projectId])

  // ─── SSE progress stream ──────────────────────────────────────────────────

  useEffect(() => {
    const close = openProgressSSE(
      projectId,
      (msg) => {
        setProgressEvents(prev => [...prev.slice(-199), msg])  // keep last 200
        setCurrentProgress(msg.progress)
        setCurrentMessage(msg.message)

        // Chỉ tắt isRunning khi nhận terminal event.
        if (msg.stage === 'done') {
          setIsRunning(false)
          refreshAll()
        } else if (msg.stage === 'error' || msg.stage === 'cancelled') {
          setIsRunning(false)
          refreshStatus()
        }

        // Auto-refresh key data when corresponding stage completes
        if (msg.stage === 'bible_done') refreshBible()
        if (msg.stage === 'scenes_done') refreshScenes()
        if (msg.stage === 'speaker_done' || msg.stage === 'translate_done')
          refreshStatus()
        if (msg.stage === 'polish_done') refreshAll()
      },
      (call) => {
        // LLM call event — append vào danh sách
        setLlmCalls(prev => [...prev.slice(-99), call])  // keep last 100
      },
      (err) => {
        console.warn('[SSE] error', err)
      },
    )
    sseCloseRef.current = close
    return close
  }, [projectId])

  // ─── Refresh helpers ──────────────────────────────────────────────────────

  async function refreshAll() {
    const [st, bib, scs, ars, iss] = await Promise.all([
      translateApi.getStatus(projectId),
      translateApi.getBible(projectId).catch(() => null),
      translateApi.listScenes(projectId).catch(() => []),
      translateApi.listStoryArcs(projectId).catch(() => []),
      translateApi.listIssues(projectId, { resolved: false }).catch(() => []),
    ])
    setStatus(st)
    setBible(bib)
    setScenes(scs)
    setArcs(ars)
    setIssues(iss)
  }

  async function refreshStatus() {
    const st = await translateApi.getStatus(projectId)
    setStatus(st)
  }

  async function refreshBible() {
    const bib = await translateApi.getBible(projectId).catch(() => null)
    setBible(bib)
    refreshStatus()
  }

  async function refreshScenes() {
    const [scs, ars] = await Promise.all([
      translateApi.listScenes(projectId).catch(() => []),
      translateApi.listStoryArcs(projectId).catch(() => []),
    ])
    setScenes(scs)
    setArcs(ars)
    refreshStatus()
  }

  // ─── Actions ──────────────────────────────────────────────────────────────

  function _extractError(e: any): string {
    const detail = e?.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail?.code === 'SOURCE_NOT_CHINESE') {
      return `⚠ ${detail.message}\n\nNếu original_text đã bị overwrite, hãy: Reset translate → Re-import SRT tiếng Trung gốc → chạy lại.`
    }
    return detail?.message || e?.message || 'Unknown error'
  }

  async function handleStart(config: TranslateConfig) {
    try {
      setProgressEvents([])
      setCurrentMessage('Khởi động...')
      setIsRunning(true)
      setShowConfig(false)
      await translateApi.start(projectId, config)
      setTab('logs')  // chuyển tab Logs để xem realtime
    } catch (e: any) {
      alert(`Start failed:\n\n${_extractError(e)}`)
      setIsRunning(false)
    }
  }

  async function handleRunStage(config: TranslateConfig, stage: string) {
    try {
      setProgressEvents([])
      setCurrentMessage(`Khởi động stage ${stage}...`)
      setIsRunning(true)
      setShowConfig(false)
      await translateApi.runStage(projectId, { ...config, stage })
      setTab('logs')
    } catch (e: any) {
      alert(`Start stage failed:\n\n${_extractError(e)}`)
      setIsRunning(false)
    }
  }

  async function handleCancel() {
    if (!confirm('Hủy pipeline đang chạy?')) return
    try {
      await translateApi.cancel(projectId)
    } catch (e: any) {
      alert(`Cancel failed: ${e?.response?.data?.detail || e.message}`)
    }
  }

  async function handleReset() {
    if (!confirm('Xóa toàn bộ Bible + Scenes + Issues? Subtitles giữ nguyên.')) return
    try {
      await translateApi.reset(projectId)
      await refreshAll()
      setProgressEvents([])
      setCurrentMessage('Đã reset')
    } catch (e: any) {
      alert(`Reset failed: ${e?.response?.data?.detail || e.message}`)
    }
  }

  // ─── Render ───────────────────────────────────────────────────────────────

  if (!project) {
    return (
      <div className="h-full flex items-center justify-center bg-zinc-50 dark:bg-zinc-900">
        <div className="text-zinc-500">Đang tải project...</div>
      </div>
    )
  }

  const stageDoneIcon = (stage: string) => {
    if (stage === 'bible')     return status?.has_bible ? '✅' : '⚪'
    if (stage === 'scenes')    return (status?.scene_count ?? 0) > 0 ? '✅' : '⚪'
    if (stage === 'speaker')   return (status?.speaker_assigned_count ?? 0) > 0 ? '✅' : '⚪'
    if (stage === 'translate') return (status?.translated_count ?? 0) > 0 ? '✅' : '⚪'
    if (stage === 'polish')    return (status?.avg_cps ?? 0) > 0 ? '✅' : '⚪'
    return '⚪'
  }

  return (
    <div className="h-full flex flex-col bg-zinc-50 dark:bg-zinc-900">

      {/* HEADER */}
      <div className="flex items-center gap-3 px-4 py-3 bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800">
        <button onClick={onBack} className="btn">← Editor</button>
        <h1 className="text-base font-semibold text-zinc-800 dark:text-zinc-100">
          {project.name}
        </h1>
        <StatusBadge status={status} isRunning={isRunning} />
        <div className="flex-1" />

        {/* Control buttons */}
        <button
          onClick={() => setShowConfig(true)}
          disabled={isRunning}
          className="btn"
        >
          ⚙ Cấu hình
        </button>

        {isRunning ? (
          <button onClick={handleCancel} className="btn bg-red-50 text-red-700 hover:bg-red-100">
            ⏹ Hủy
          </button>
        ) : (
          <>
            <button
              onClick={() => setShowConfig(true)}
              className="btn-primary"
              title="Bắt đầu pipeline 5 stage"
            >
              ▶ Bắt đầu
            </button>
            {(status?.has_bible || (status?.scene_count ?? 0) > 0) && (
              <button onClick={handleReset} className="btn text-zinc-500">
                ↻ Reset
              </button>
            )}
          </>
        )}
      </div>

      {/* PROGRESS BAR */}
      {(isRunning || currentProgress > 0) && (
        <div className="px-4 py-2 bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800">
          <div className="flex items-center gap-3 mb-1">
            <div className="text-xs font-medium text-zinc-600 dark:text-zinc-400">
              {currentMessage || 'Đang xử lý...'}
            </div>
            <div className="flex-1" />
            <div className="text-xs text-zinc-500">
              {currentProgress.toFixed(0)}%
            </div>
          </div>
          <div className="h-1.5 bg-zinc-100 dark:bg-zinc-800 rounded overflow-hidden">
            <div
              className={`h-full transition-all duration-300 ${
                isRunning ? 'bg-blue-500' : 'bg-green-500'
              }`}
              style={{ width: `${Math.max(2, currentProgress)}%` }}
            />
          </div>
        </div>
      )}

      {/* TABS */}
      <div className="flex items-center gap-1 px-4 bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800">
        <TabButton active={tab === 'overview'} onClick={() => setTab('overview')}>
          📊 Tổng quan
        </TabButton>
        <TabButton active={tab === 'bible'} onClick={() => setTab('bible')}>
          📖 Bible {bible && <Pill>{bible.cast?.characters?.length || 0}</Pill>}
        </TabButton>
        <TabButton active={tab === 'scenes'} onClick={() => setTab('scenes')}>
          🎬 Phân cảnh {scenes.length > 0 && <Pill>{scenes.length}</Pill>}
        </TabButton>
        <TabButton active={tab === 'subtitles'} onClick={() => setTab('subtitles')}>
          📝 Phụ đề {project.subtitle_count > 0 && <Pill>{project.subtitle_count}</Pill>}
        </TabButton>
        <TabButton active={tab === 'issues'} onClick={() => setTab('issues')}>
          ⚠ Vấn đề {issues.length > 0 && <Pill className="bg-amber-500/20 text-amber-700">{issues.length}</Pill>}
        </TabButton>
        <TabButton active={tab === 'logs'} onClick={() => setTab('logs')}>
          📜 Logs {(progressEvents.length + llmCalls.length) > 0 && (
            <Pill>{progressEvents.length}+{llmCalls.length}</Pill>
          )}
        </TabButton>
      </div>

      {/* CONTENT */}
      <div className="flex-1 overflow-auto">
        {tab === 'overview' && (
          <Overview
            project={project}
            status={status}
            bible={bible}
            scenes={scenes}
            arcs={arcs}
            issues={issues}
            stageDoneIcon={stageDoneIcon}
          />
        )}

        {tab === 'bible' && (
          <BibleViewer
            projectId={projectId}
            bible={bible}
            onUpdate={refreshBible}
          />
        )}

        {tab === 'scenes' && (
          <SceneList
            projectId={projectId}
            scenes={scenes}
            arcs={arcs}
            issues={issues}
            onIssuesUpdate={() => translateApi.listIssues(projectId, { resolved: false }).then(setIssues)}
          />
        )}

        {tab === 'subtitles' && (
          <SubtitlesView projectId={projectId} />
        )}

        {tab === 'issues' && (
          <IssueQueue
            projectId={projectId}
            issues={issues}
            onUpdate={() => translateApi.listIssues(projectId, { resolved: false }).then(setIssues)}
          />
        )}

        {tab === 'logs' && (
          <ProgressLog events={progressEvents} llmCalls={llmCalls} />
        )}
      </div>

      {/* CONFIG MODAL */}
      {showConfig && (
        <ConfigPanel
          project={project}
          status={status}
          genrePacks={genrePacks}
          onClose={() => setShowConfig(false)}
          onStart={handleStart}
          onRunStage={handleRunStage}
        />
      )}
    </div>
  )
}


// ─── Small helper components ─────────────────────────────────────────────────

function StatusBadge({ status, isRunning }: { status: TranslateStatus | null; isRunning: boolean }) {
  if (!status) return null
  if (isRunning || status.status === 'running') {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-[11px] font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300">
        <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
        Đang chạy
      </span>
    )
  }
  if (status.status === 'done') {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded text-[11px] font-medium bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300">
        ✓ Hoàn tất
      </span>
    )
  }
  if (status.status === 'error') {
    return (
      <span className="inline-flex items-center px-2 py-1 rounded text-[11px] font-medium bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300">
        ✗ Lỗi
      </span>
    )
  }
  return (
    <span className="inline-flex items-center px-2 py-1 rounded text-[11px] font-medium bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400">
      Sẵn sàng
    </span>
  )
}

function TabButton({ active, onClick, children }: {
  active: boolean; onClick: () => void; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-4 py-2.5 text-[13px] font-medium transition-colors border-b-2 -mb-px flex items-center gap-1.5 ${
        active
          ? 'border-blue-500 text-blue-600 dark:text-blue-400'
          : 'border-transparent text-zinc-500 hover:text-zinc-800 dark:hover:text-zinc-200'
      }`}
    >
      {children}
    </button>
  )
}

function Pill({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center px-1.5 rounded text-[10px] font-semibold bg-zinc-200 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-300 ${className}`}>
      {children}
    </span>
  )
}

// ─── Overview tab ────────────────────────────────────────────────────────────

function Overview({ project, status, bible, scenes, arcs, issues, stageDoneIcon }: {
  project: Project
  status: TranslateStatus | null
  bible: Bible | null
  scenes: Scene[]
  arcs: StoryArc[]
  issues: PolishIssue[]
  stageDoneIcon: (stage: string) => string
}) {
  const totalLines = project.subtitle_count
  const speakerAssigned = status?.speaker_assigned_count || 0
  const translated = status?.translated_count || 0
  const review = status?.review_count || 0
  const avgCps = status?.avg_cps || 0
  const cost = status?.cost_usd || 0
  const tokensIn = status?.tokens_in || 0
  const tokensOut = status?.tokens_out || 0

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">

      {/* Stage pipeline */}
      <div className="bg-white dark:bg-zinc-950 rounded-xl border border-zinc-200 dark:border-zinc-800 p-5">
        <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-widest mb-3">
          Pipeline 5 stage
        </div>
        <div className="grid grid-cols-5 gap-2">
          <StageCard icon={stageDoneIcon('bible')} title="1. Bible" desc={bible ? `${bible.cast.characters.length} nhân vật · ${bible.glossary.terms?.length || 0} thuật ngữ` : 'Phân tích phim'} />
          <StageCard icon={stageDoneIcon('scenes')} title="2. Phân cảnh" desc={`${scenes.length} scenes · ${arcs.length} arcs`} />
          <StageCard icon={stageDoneIcon('speaker')} title="3. Speaker" desc={speakerAssigned > 0 ? `${speakerAssigned}/${totalLines} dòng` : 'Gán nhân vật'} />
          <StageCard icon={stageDoneIcon('translate')} title="4. Dịch" desc={translated > 0 ? `${translated} dòng` : 'Dịch per scene'} />
          <StageCard icon={stageDoneIcon('polish')} title="5. Polish" desc={avgCps > 0 ? `CPS ${avgCps.toFixed(1)}` : 'CPS + QC'} />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard label="Tổng dòng" value={totalLines.toString()} sub="subtitles" />
        <StatCard label="Đã dịch" value={`${translated}/${totalLines}`}
                  sub={totalLines > 0 ? `${((translated/totalLines)*100).toFixed(0)}%` : ''} />
        <StatCard label="Cần review" value={review.toString()}
                  sub={review > 0 ? 'kiểm tra tay' : 'OK'}
                  warning={review > 0} />
        <StatCard
          label="Tokens"
          value={tokensIn + tokensOut > 0
            ? formatTokens(tokensIn + tokensOut)
            : '—'}
          sub={tokensIn + tokensOut > 0
            ? `${formatTokens(tokensIn)} in · ${formatTokens(tokensOut)} out`
            : 'chưa chạy'}
        />
        <StatCard label="Chi phí" value={`$${cost.toFixed(4)}`} sub="USD" />
      </div>

      {/* Bible quick view */}
      {bible && (
        <div className="bg-white dark:bg-zinc-950 rounded-xl border border-zinc-200 dark:border-zinc-800 p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-widest">
              Bible v{bible.version}
            </div>
            {bible.genre_pack_id && (
              <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300">
                🎭 {bible.genre_pack_id}
              </span>
            )}
          </div>

          {/* Genre */}
          {bible.world && (
            <div className="mb-3 text-sm">
              <span className="text-zinc-500">Thể loại: </span>
              <span className="font-medium text-zinc-800 dark:text-zinc-200">
                {GENRE_MAIN_LABELS[bible.world.genre_main] || bible.world.genre_main}
              </span>
              {bible.world.genre_sub?.length > 0 && (
                <span className="text-zinc-500">
                  {' · '}{bible.world.genre_sub.map(g => GENRE_SUB_LABELS[g] || g).join(', ')}
                </span>
              )}
            </div>
          )}

          {/* Plot */}
          {bible.world?.plot_summary && (
            <div className="text-sm text-zinc-700 dark:text-zinc-300 mb-3">
              {bible.world.plot_summary}
            </div>
          )}

          {/* Main characters */}
          {bible.cast?.characters && bible.cast.characters.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {bible.cast.characters.slice(0, 8).map((c, i) => (
                <span key={i} className="px-2 py-1 rounded text-[11px] bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
                  <span className="font-medium">{c.vi}</span>
                  <span className="ml-1 text-zinc-400">({ROLE_LABELS[c.role] || c.role})</span>
                </span>
              ))}
              {bible.cast.characters.length > 8 && (
                <span className="text-[11px] text-zinc-400">+{bible.cast.characters.length - 8}</span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Issues summary */}
      {issues.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-900/20 rounded-xl border border-amber-200 dark:border-amber-800 p-5">
          <div className="text-[11px] font-semibold text-amber-700 dark:text-amber-300 uppercase tracking-widest mb-2">
            Có {issues.length} vấn đề cần xem
          </div>
          <div className="text-sm text-amber-900 dark:text-amber-200">
            {Object.entries(
              issues.reduce<Record<string, number>>((acc, iss) => {
                acc[iss.issue_type] = (acc[iss.issue_type] || 0) + 1
                return acc
              }, {}),
            ).map(([type, count]) => (
              <span key={type} className="inline-block mr-3">
                {ISSUE_TYPE_LABELS[type] || type}: <strong>{count}</strong>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Error */}
      {status?.error_message && (
        <div className="bg-red-50 dark:bg-red-900/20 rounded-xl border border-red-200 dark:border-red-800 p-5">
          <div className="text-[11px] font-semibold text-red-700 dark:text-red-300 uppercase tracking-widest mb-2">
            Lỗi
          </div>
          <div className="text-sm text-red-900 dark:text-red-200 font-mono whitespace-pre-wrap">
            {status.error_message}
          </div>
        </div>
      )}
    </div>
  )
}

function StageCard({ icon, title, desc }: { icon: string; title: string; desc: string }) {
  return (
    <div className="text-center p-3 rounded-lg bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800">
      <div className="text-2xl mb-1">{icon}</div>
      <div className="text-[12px] font-semibold text-zinc-700 dark:text-zinc-300">{title}</div>
      <div className="text-[10px] text-zinc-500 mt-0.5 leading-tight">{desc}</div>
    </div>
  )
}

function StatCard({ label, value, sub, warning }: {
  label: string; value: string; sub?: string; warning?: boolean
}) {
  return (
    <div className={`bg-white dark:bg-zinc-950 rounded-xl border p-4 ${
      warning ? 'border-amber-300 dark:border-amber-800' : 'border-zinc-200 dark:border-zinc-800'
    }`}>
      <div className="text-[10px] font-semibold text-zinc-400 uppercase tracking-widest mb-1">
        {label}
      </div>
      <div className={`text-2xl font-semibold ${
        warning ? 'text-amber-700 dark:text-amber-300' : 'text-zinc-800 dark:text-zinc-100'
      }`}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-zinc-500 mt-0.5">{sub}</div>}
    </div>
  )
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return n.toString()
}