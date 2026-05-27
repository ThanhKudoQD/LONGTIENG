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
  Project, TranslateStatus, Bible, Scene, StoryArc, Chunk,
  PolishIssue, TranslateConfig,
} from '../types'
import {
  EMOTION_LABELS, EMOTION_COLORS, ROLE_LABELS,
  ISSUE_TYPE_LABELS,
} from '../types'

import ConfigPanel from './translate/ConfigPanel'
import BibleViewer from './translate/BibleViewer'
import SceneList from './translate/SceneList'
import ArcList from './translate/ArcList'  // v4.4: thay SceneList khi không có chunks
import SubtitlesView from './translate/SubtitlesView'
import CleanedView from './translate/CleanedView'
import IssueQueue from './translate/IssueQueue'
import ProgressLog from './translate/ProgressLog'
import ManualTranslatePanel from './translate/ManualTranslatePanel'  // v3.15
import ManualTranslatePanelMega from './translate/ManualTranslatePanelMega'  // v4 mega

type Tab = 'overview' | 'bible' | 'cleaned' | 'scenes' | 'subtitles' | 'issues' | 'logs' | 'manual' | 'manual_mega'

// v3: Map next_stage code → label hiển thị (module scope để SSE closure dùng ổn định)
const NEXT_STAGE_LABEL: Record<string, string> = {
  normalize: 'Stage 0 (Chuẩn hóa)',
  bible_1a:  'Stage 1A (Cast + Glossary — legacy)',
  bible_cast:     'Stage 1A (Cast)',
  bible_glossary: 'Stage 1A.2 (Glossary)',
  bible_1b:  'Stage 1B (World + Arcs)',
  bible:     'Stage 1 (Bible — legacy combined)',
  chunks:    'Stage 2 (Chunks + Scenes)',
  scenes:    'Stage 2 (Chunks + Scenes)',
  speaker:   'Stage 3 (Speaker)',
  translate: 'Stage 4 (Translate ⭐)',
  polish:    'Stage 5 (Polish)',
}

export default function TranslatePage({
  projectId, onBack,
}: { projectId: number; onBack: () => void }) {

  const [project, setProject] = useState<Project | null>(null)
  const [status, setStatus] = useState<TranslateStatus | null>(null)
  const [bible, setBible] = useState<Bible | null>(null)
  const [chunks, setChunks] = useState<Chunk[]>([])
  const [scenes, setScenes] = useState<Scene[]>([])
  const [arcs, setArcs] = useState<StoryArc[]>([])
  const [issues, setIssues] = useState<PolishIssue[]>([])

  const [tab, setTab] = useState<Tab>('overview')
  const [showConfig, setShowConfig] = useState(false)

  // Progress events feed
  const [progressEvents, setProgressEvents] = useState<ProgressMessage[]>([])
  const [llmCalls, setLlmCalls] = useState<LLMCallMessage[]>([])
  const [currentProgress, setCurrentProgress] = useState(0)
  const [currentMessage, setCurrentMessage] = useState('')
  const [isRunning, setIsRunning] = useState(false)
  const sseCloseRef = useRef<(() => void) | null>(null)

  // v3: auto-chain — khi true, sau khi 1 stage xong (event 'done') sẽ tự chạy
  // stage tiếp theo dựa trên status.next_stage. Tắt khi pipeline xong/lỗi/cancel.
  const autoChainRef = useRef(false)
  const lastConfigRef = useRef<TranslateConfig | null>(null)

  // ─── Load initial data ────────────────────────────────────────────────────

  useEffect(() => {
    let cancelled = false
    async function load() {
      try {
        const [proj, st, bib, chks, scs, ars, iss, evts, calls] = await Promise.all([
          api.get<Project>(`/projects/${projectId}`).then(r => r.data),
          translateApi.getStatus(projectId),
          translateApi.getBible(projectId).catch(() => null),
          translateApi.listChunks(projectId).catch(() => []),
          translateApi.listScenes(projectId).catch(() => []),
          translateApi.listStoryArcs(projectId).catch(() => []),
          translateApi.listIssues(projectId, { resolved: false }).catch(() => []),
          // v3.9: load history (events + LLM calls) đã persist trong DB
          translateApi.listEvents(projectId).catch(() => []),
          translateApi.listLlmCalls(projectId).catch(() => []),
        ])
        if (cancelled) return
        setProject(proj)
        setStatus(st)
        setBible(bib)
        setChunks(chks)
        setScenes(scs)
        setArcs(ars)
        setIssues(iss)
        // v3.9: hydrate logs từ DB. SSE sẽ append tiếp các event mới sau đó.
        setProgressEvents(evts as any[])
        setLlmCalls(calls as any[])
        setCurrentProgress(st.progress)
        setIsRunning(st.status === 'running')
        // Nếu đang running và đã có event cuối, hiển thị message gần nhất
        if (evts.length > 0) {
          const last = evts[evts.length - 1] as any
          if (last?.message) setCurrentMessage(last.message)
        }
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

        if (msg.stage === 'done') {
          setIsRunning(false)
          // v3: auto-chain — refresh status rồi chạy stage tiếp theo nếu còn
          ;(async () => {
            await refreshAll()
            if (autoChainRef.current && lastConfigRef.current) {
              try {
                const st = await translateApi.getStatus(projectId)
                if (st.next_stage) {
                  setCurrentMessage(`Auto-chain: chuyển sang ${NEXT_STAGE_LABEL[st.next_stage] || st.next_stage}...`)
                  setIsRunning(true)
                  await translateApi.runStage(projectId, {
                    ...lastConfigRef.current,
                    stage: st.next_stage,
                  })
                } else {
                  autoChainRef.current = false
                  setCurrentMessage('✅ Pipeline hoàn tất toàn bộ!')
                }
              } catch (e: any) {
                console.error('[auto-chain] failed:', e)
                autoChainRef.current = false
                setCurrentMessage(`Auto-chain lỗi: ${e?.message || e}`)
              }
            }
          })()
        } else if (msg.stage === 'error' || msg.stage === 'cancelled') {
          setIsRunning(false)
          // Tắt auto-chain khi có lỗi/cancel
          autoChainRef.current = false
          refreshStatus()
        }

        // Auto-refresh key data when corresponding stage completes
        // v3: thêm event 1A/1B; v3.14: thêm bible_cast / bible_glossary
        if (msg.stage === 'bible_done'
            || msg.stage === 'bible_1a_done' || msg.stage === 'bible_1a_saved'
            || msg.stage === 'bible_cast_done' || msg.stage === 'bible_cast_saved'
            || msg.stage === 'bible_glossary_done' || msg.stage === 'bible_glossary_saved'
            || msg.stage === 'bible_1b_done' || msg.stage === 'bible_1b_saved') {
          refreshBible()
        }
        if (msg.stage === 'chunks_done' || msg.stage === 'scenes_done') refreshChunks()
        if (msg.stage === 'speaker_done' || msg.stage === 'translate_done')
          refreshStatus()
        if (msg.stage === 'polish_done') refreshAll()
        if (msg.stage === 'normalize_done') refreshStatus()
      },
      (call) => {
        setLlmCalls(prev => [...prev.slice(-99), call])
      },
      (err) => {
        console.warn('[SSE] error', err)
      },
    )
    sseCloseRef.current = close
    return close
  }, [projectId])

  // Listen event stage0-done từ CleanedView (chạy chuẩn hóa sync, không qua SSE)
  useEffect(() => {
    function onStage0Done() {
      refreshAll()
    }
    window.addEventListener('stage0-done', onStage0Done)
    return () => window.removeEventListener('stage0-done', onStage0Done)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectId])

  // ─── Refresh helpers ──────────────────────────────────────────────────────

  async function refreshAll() {
    const [st, bib, chks, scs, ars, iss] = await Promise.all([
      translateApi.getStatus(projectId),
      translateApi.getBible(projectId).catch(() => null),
      translateApi.listChunks(projectId).catch(() => []),
      translateApi.listScenes(projectId).catch(() => []),
      translateApi.listStoryArcs(projectId).catch(() => []),
      translateApi.listIssues(projectId, { resolved: false }).catch(() => []),
    ])
    setStatus(st)
    setBible(bib)
    setChunks(chks)
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

  async function refreshChunks() {
    const [chks, scs, ars] = await Promise.all([
      translateApi.listChunks(projectId).catch(() => []),
      translateApi.listScenes(projectId).catch(() => []),
      translateApi.listStoryArcs(projectId).catch(() => []),
    ])
    setChunks(chks)
    setScenes(scs)
    setArcs(ars)
    refreshStatus()
  }

  // Alias backwards compat
  const refreshScenes = refreshChunks

  // ─── Actions ──────────────────────────────────────────────────────────────

  function _extractError(e: any): string {
    const detail = e?.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (detail?.code === 'SOURCE_NOT_CHINESE') {
      return `⚠ ${detail.message}\n\nNếu original_text đã bị overwrite, hãy: Reset translate → Re-import SRT tiếng Trung gốc → chạy lại.`
    }
    return detail?.message || e?.message || 'Unknown error'
  }

  // v3: thứ tự stages để auto-chain — sau khi stage hiện tại xong, refresh status
  // và xem next_stage còn không → chạy tiếp đến hết.
  // (NEXT_STAGE_LABEL ở module scope phía trên)

  /** v3: Auto-chain — chạy từ stage hiện tại đến hết pipeline.
   * Mỗi lần một stage xong (SSE 'done' event), TranslatePage sẽ refresh status
   * và auto trigger stage tiếp theo qua effect bên dưới.
   */
  async function handleStart(config: TranslateConfig) {
    try {
      // Đã chạy xong toàn bộ → hỏi reset
      if (status && !status.next_stage && status.status !== 'running') {
        const reallyRestart = window.confirm(
          'Pipeline đã hoàn tất toàn bộ.\n\n' +
          'Bạn muốn CHẠY LẠI từ đầu? (Bible + Chunks + Translations sẽ bị XÓA)'
        )
        if (!reallyRestart) return
        try {
          await translateApi.reset(projectId)
          await refreshAll()
          setProgressEvents([])
          setLlmCalls([])
          setCurrentMessage('Đã reset, bắt đầu chạy lại từ đầu...')
        } catch (e: any) {
          alert(`Reset failed: ${e?.response?.data?.detail || e.message}`)
          return
        }
        // Sau reset, status sẽ refresh → next_stage = 'normalize' → fall through
      }

      // Auto-chain: bật flag để effect tự chain các stage kế tiếp
      autoChainRef.current = true
      lastConfigRef.current = config

      // Lấy stage cần chạy
      const nextStage = (status?.next_stage) || 'normalize'

      setCurrentMessage(`Auto-chain: bắt đầu từ ${NEXT_STAGE_LABEL[nextStage] || nextStage}...`)
      setIsRunning(true)
      setShowConfig(false)
      await translateApi.runStage(projectId, { ...config, stage: nextStage })
      setTab('logs')
    } catch (e: any) {
      autoChainRef.current = false
      alert(`Start failed:\n\n${_extractError(e)}`)
      setIsRunning(false)
    }
  }

  async function handleRunStage(config: TranslateConfig, stage: string) {
    try {
      // Manual run 1 stage → KHÔNG auto-chain (chỉ chạy stage user yêu cầu)
      autoChainRef.current = false
      lastConfigRef.current = config
      setCurrentMessage(`Khởi động ${NEXT_STAGE_LABEL[stage] || stage}...`)
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
    // v3.9: dialog rõ ràng về hậu quả
    const ok = window.confirm(
      'Hủy pipeline đang chạy?\n\n' +
      '⚠ Lưu ý:\n' +
      '• API call LLM đang dở sẽ bị hủy thô → log của call đó có thể KHÔNG được lưu.\n' +
      '• Dữ liệu các stage đã hoàn thành (Bible/Chunks/...) sẽ ĐƯỢC GIỮ — có thể tiếp tục sau.\n' +
      '• Muốn xóa hết để chạy lại từ đầu → dùng nút "Reset" thay vì Cancel.'
    )
    if (!ok) return
    try {
      await translateApi.cancel(projectId)
    } catch (e: any) {
      alert(`Cancel failed: ${e?.response?.data?.detail || e.message}`)
    }
  }

  async function handleClearLogs() {
    if (!window.confirm('Xóa toàn bộ log + LLM history? Không ảnh hưởng dữ liệu pipeline.')) return
    try {
      await translateApi.clearLogs(projectId)
      setProgressEvents([])
      setLlmCalls([])
    } catch (e: any) {
      alert(`Clear logs failed: ${e?.response?.data?.detail || e.message}`)
    }
  }

  async function handleReset() {
    if (!confirm('Xóa toàn bộ Bible + Scenes + Issues + Logs? Subtitles giữ nguyên.')) return
    try {
      await translateApi.reset(projectId)
      await refreshAll()
      // v3.9: backend đã clear_logs trong reset → đồng bộ FE
      setProgressEvents([])
      setLlmCalls([])
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
    // v3 FIX: Stage 0 — không chỉ dựa vào cleaned/removed (AI có thể quyết định
    // keep hết), mà còn check progressEvents có 'normalize_done' không.
    if (stage === 'normalize') {
      const stage0Done = (status?.stage0_ran ?? false)
        || (status?.cleaned_count ?? 0) > 0
        || (status?.removed_count ?? 0) > 0
        || progressEvents.some(e => e.stage === 'normalize_done')
      return stage0Done ? '✅' : '⚪'
    }
    // v3: Bible split — 1A có cast, 1B có world
    if (stage === 'bible_1a') return (status?.has_cast ?? false) ? '✅' : '⚪'
    if (stage === 'bible_cast') return (status?.has_cast ?? false) ? '✅' : '⚪'
    if (stage === 'bible_glossary') return (status?.has_glossary ?? false) ? '✅' : '⚪'
    if (stage === 'bible_1b') return (status?.has_world ?? false) ? '✅' : '⚪'
    // Legacy 'bible' — vẫn dùng has_bible
    if (stage === 'bible')     return status?.has_bible ? '✅' : '⚪'
    if (stage === 'scenes')    return (status?.scene_count ?? 0) > 0 ? '✅' : '⚪'
    if (stage === 'chunks')    return (status?.chunk_count ?? 0) > 0 ? '✅' : '⚪'
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
              title={
                status?.next_stage
                  ? `Tiếp tục từ ${NEXT_STAGE_LABEL[status.next_stage] || status.next_stage} → chạy hết pipeline`
                  : status?.status === 'done'
                  ? 'Pipeline đã xong toàn bộ. Bấm để reset + chạy lại từ đầu.'
                  : 'Bắt đầu pipeline (auto-chain từ stage hiện tại đến hết)'
              }
            >
              {status?.next_stage
                ? `▶ Tiếp tục từ ${NEXT_STAGE_LABEL[status.next_stage]?.replace(/Stage\s+/, '') || status.next_stage}`
                : status?.can_resume === false && (status?.translated_count ?? 0) > 0
                ? '▶ Chạy lại từ đầu'
                : '▶ Bắt đầu'}
            </button>
            {(status?.has_bible || (status?.scene_count ?? 0) > 0 || (status?.stage0_ran ?? false)) && (
              <button onClick={handleReset} className="btn text-zinc-500"
                title="Xóa Bible + Chunks + Translations + Logs">
                ↻ Reset
              </button>
            )}
            {(progressEvents.length > 0 || llmCalls.length > 0) && (
              <button onClick={handleClearLogs} className="btn text-zinc-500"
                title="Xóa log + LLM history (không ảnh hưởng pipeline data)">
                🗑 Clear logs
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
        <TabButton active={tab === 'cleaned'} onClick={() => setTab('cleaned')}>
          🧹 Chuẩn hóa
          {((status?.cleaned_count ?? 0) + (status?.removed_count ?? 0)) > 0 && (
            <Pill className="bg-emerald-500/20 text-emerald-700">
              {(status?.cleaned_count ?? 0) + (status?.removed_count ?? 0)}
            </Pill>
          )}
        </TabButton>
        <TabButton active={tab === 'bible'} onClick={() => setTab('bible')}>
          📖 Bible {bible && <Pill>{bible.cast?.characters?.length || 0}</Pill>}
        </TabButton>
        <TabButton active={tab === 'scenes'} onClick={() => setTab('scenes')}>
          {chunks.length > 0 ? (
            <>🎬 Chunks <Pill>{chunks.length}</Pill></>
          ) : (
            <>🎬 Arcs {arcs.length > 0 && <Pill>{arcs.length}</Pill>}</>
          )}
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
        <TabButton active={tab === 'manual'} onClick={() => setTab('manual')}>
          🛠️ Thủ công
        </TabButton>
        <TabButton active={tab === 'manual_mega'} onClick={() => setTab('manual_mega')}>
          🚀 Thủ công Mega <span className="ml-1 text-[10px] px-1 rounded bg-gradient-to-r from-purple-500 to-pink-500 text-white">v4</span>
        </TabButton>
      </div>

      {/* CONTENT */}
      <div className="flex-1 overflow-auto">
        {tab === 'overview' && (
          <Overview
            project={project}
            status={status}
            bible={bible}
            chunks={chunks}
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

        {tab === 'cleaned' && (
          <CleanedView projectId={projectId} />
        )}

        {tab === 'scenes' && (
          chunks.length > 0 ? (
            <SceneList
              projectId={projectId}
              chunks={chunks}
              scenes={scenes}
              arcs={arcs}
              issues={issues}
              onIssuesUpdate={() => translateApi.listIssues(projectId, { resolved: false }).then(setIssues)}
              onChunksRefresh={refreshChunks}
            />
          ) : (
            <ArcList projectId={projectId} arcs={arcs} />
          )
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

        {tab === 'manual' && (
          <ManualTranslatePanel
            projectId={projectId}
            onDataChanged={() => {
              // Refresh tất cả data sau khi user apply 1 stage thành công
              refreshStatus()
              refreshBible()
              refreshChunks()
            }}
          />
        )}

        {tab === 'manual_mega' && (
          <ManualTranslatePanelMega
            projectId={projectId}
            onDataChanged={() => {
              refreshStatus()
              refreshBible()
              refreshChunks()
            }}
          />
        )}
      </div>

      {/* CONFIG MODAL */}
      {showConfig && (
        <ConfigPanel
          project={project}
          status={status}
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

function Overview({ project, status, bible, chunks, scenes, arcs, issues, stageDoneIcon }: {
  project: Project
  status: TranslateStatus | null
  bible: Bible | null
  chunks: Chunk[]
  scenes: Scene[]
  arcs: StoryArc[]
  issues: PolishIssue[]
  stageDoneIcon: (stage: string) => string
}) {
  const totalLines = project.subtitle_count
  const speakerAssigned = status?.speaker_assigned_count || 0
  const translated = status?.translated_count || 0
  const variants = status?.variants_count || 0
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
          Pipeline (v3)
        </div>
        <div className="grid grid-cols-3 md:grid-cols-8 gap-2">
          <StageCard icon={stageDoneIcon('normalize')} title="0. Chuẩn hóa"
            desc={
              (status?.cleaned_count ?? 0) > 0 || (status?.removed_count ?? 0) > 0
                ? `${status?.cleaned_count ?? 0} sửa · ${status?.removed_count ?? 0} bỏ`
                : (status?.stage0_ran ? 'Đã chạy · phụ đề sạch' : 'Làm sạch phụ đề')
            } />
          <StageCard icon={stageDoneIcon('bible_cast')} title="1A. Cast"
            desc={status?.has_cast
              ? `${status?.cast_count ?? bible?.cast.characters.length ?? 0} nhân vật`
              : 'Trích nhân vật'} />
          <StageCard icon={stageDoneIcon('bible_glossary')} title="1A.2 Glossary"
            desc={status?.has_glossary
              ? `${status?.glossary_count ?? bible?.glossary.terms?.length ?? 0} thuật ngữ`
              : 'Trích thuật ngữ'} />
          <StageCard icon={stageDoneIcon('bible_1b')} title="1B. World"
            desc={status?.has_world
              ? `${status?.world_arcs_count ?? bible?.world.arcs?.length ?? 0} arcs · ${bible?.world.genre_id || 'other'}`
              : 'Bối cảnh + arcs'} />
          <StageCard icon={stageDoneIcon('chunks')} title="2. Chunks"
            desc={`${chunks.length} chunks · ${arcs.length} arcs · ${scenes.length} scenes`} />
          <StageCard icon={stageDoneIcon('speaker')} title="3. Speaker"
            desc={speakerAssigned > 0
              ? `${speakerAssigned}/${totalLines} dòng`
              : 'Gán nhân vật'} />
          <StageCard icon={stageDoneIcon('translate')} title="4. Dịch"
            desc={translated > 0 ? `${translated} dòng${variants > 0 ? ` · ${variants} v2` : ''}` : 'Dịch per chunk'} />
          <StageCard icon={stageDoneIcon('polish')} title="5. Retry"
            desc={avgCps > 0 ? `CPS ${avgCps.toFixed(1)}` : 'Retry dòng thiếu'} />
        </div>
      </div>

      {/* Stats grid */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <StatCard
          label="Tổng dòng"
          value={totalLines.toString()}
          sub={(status?.removed_count ?? 0) > 0
            ? `+${status?.removed_count} dòng đã xóa ở Stage 0`
            : 'subtitles'}
        />
        <StatCard
          label="Đã dịch"
          value={`${translated}/${totalLines}`}
          sub={totalLines > 0 ? `${((translated/totalLines)*100).toFixed(0)}%` : ''}
        />
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
          </div>

          {/* Genre */}
          {bible.world && bible.world.genre && bible.world.genre.length > 0 && (
            <div className="mb-3 text-sm">
              <span className="text-zinc-500">Thể loại: </span>
              <span className="font-medium text-zinc-800 dark:text-zinc-200">
                {bible.world.genre.join(' · ')}
              </span>
              {bible.world.era && (
                <span className="text-zinc-500"> · {bible.world.era}</span>
              )}
            </div>
          )}

          {/* Plot */}
          {bible.world?.plot && (
            <div className="text-sm text-zinc-700 dark:text-zinc-300 mb-3">
              {bible.world.plot}
            </div>
          )}

          {/* Main characters */}
          {bible.cast?.characters && bible.cast.characters.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              {bible.cast.characters.slice(0, 8).map((c, i) => (
                <span key={i} className="px-2 py-1 rounded text-[11px] bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
                  <span className="font-medium">{c.vi}</span>
                  <span className="ml-1 text-zinc-400">({ROLE_LABELS[c.role || 'phu'] || c.role || 'phụ'})</span>
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