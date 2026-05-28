/**
 * TranslatePageSimple v3 — Pipeline dịch đơn giản, wire vào BE thật.
 *
 * Thay đổi từ v2:
 *  - Bỏ mockData
 *  - Load state qua simpleApi
 *  - Long-running tasks dùng WebSocket để update real-time
 *  - Config load từ DB + cache localStorage (fallback offline)
 *  - Error handling + toast
 */
import React, { useState, useEffect, useCallback } from 'react'

import BibleTab from './tabs/BibleTab'
import TranslateTab from './tabs/TranslateTab'
import ReviewTab from './tabs/ReviewTab'
import BibleViewTab from './tabs/BibleViewTab'
import SubtitlesViewTab from './tabs/SubtitlesViewTab'
import ConfigPanel, {
  loadSimpleConfig, saveSimpleConfig, defaultSimpleConfig,
} from './ConfigPanel'
import { TabBadge, TabNumber } from './shared/SharedUI'

import {
  bibleApi, batchesApi, reviewApi, configApi,
} from './simpleApi'
import { useSimpleWebSocket, type SimpleEvent } from './hooks/useSimpleWebSocket'

import api from '../../../api'
import type {
  SimpleTab, BibleState, TranslateState, ReviewState, SimpleConfig,
} from './types'


// ─── Tab metadata ────────────────────────────────────────────────────────────

const TAB_META: { key: SimpleTab; num: number; label: string }[] = [
  { key: 'bible',       num: 1, label: 'Bible' },
  { key: 'bible-view',  num: 2, label: 'Xem Bible' },
  { key: 'translate',   num: 3, label: 'Dịch batch' },
  { key: 'subtitles',   num: 4, label: 'Phụ đề' },
  { key: 'review',      num: 5, label: 'Review' },
]


// ─── Toast helpers (đơn giản) ────────────────────────────────────────────────

interface Toast {
  id: number
  type: 'info' | 'success' | 'error'
  message: string
}

let _toastSeq = 0


// ─── Main component ─────────────────────────────────────────────────────────

interface Props {
  projectId: number
  onBack: () => void
}

export default function TranslatePageSimple({ projectId, onBack }: Props) {
  const [activeTab, setActiveTab] = useState<SimpleTab>('bible')
  const [projectName, setProjectName] = useState<string>('Đang tải...')
  const [totalSrtLines, setTotalSrtLines] = useState<number>(0)
  const [totalSrtTokens, setTotalSrtTokens] = useState<number>(0)
  const [showConfig, setShowConfig] = useState(false)

  // Config: cache localStorage + override từ DB khi mount
  const [config, setConfig] = useState<SimpleConfig>(loadSimpleConfig())

  // States cho các tab — null = đang load lần đầu
  const [bible, setBible] = useState<BibleState | null>(null)
  const [translateState, setTranslateState] = useState<TranslateState | null>(null)
  const [reviewState, setReviewState] = useState<ReviewState | null>(null)

  // Toasts
  const [toasts, setToasts] = useState<Toast[]>([])
  const [wsConnected, setWsConnected] = useState(false)
  const [runningTasks, setRunningTasks] = useState<Set<string>>(new Set())

  const pushToast = useCallback((type: Toast['type'], message: string) => {
    const id = ++_toastSeq
    setToasts(t => [...t, { id, type, message }])
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4500)
  }, [])

  // ─── Load project info + initial states ───────────────────────────────────

  useEffect(() => {
    api.get(`/projects/${projectId}`)
      .then(r => {
        setProjectName(r.data.name || `Project ${projectId}`)
        setTotalSrtLines(r.data.subtitle_count || 0)
        // Rough token est
        setTotalSrtTokens(Math.round((r.data.subtitle_count || 0) * 17.5))
      })
      .catch(() => setProjectName(`Project ${projectId}`))
  }, [projectId])

  // Load config từ DB (override localStorage cache)
  useEffect(() => {
    configApi.get(projectId)
      .then(serverConfig => {
        // Merge — DB là source of truth, nhưng tránh ghi đè khi DB trả default rỗng
        if (serverConfig.api_keys.gemini || serverConfig.api_keys.openai ||
            serverConfig.api_keys.deepseek) {
          setConfig(serverConfig)
          saveSimpleConfig(serverConfig)   // sync localStorage
        }
      })
      .catch(err => {
        console.warn('[Config] Cannot load from BE, using local cache:', err)
      })
  }, [projectId])

  // Save config: cả DB + localStorage. Nếu batch settings thay đổi → rebuild batches.
  const saveConfigBoth = useCallback(async (newConfig: SimpleConfig) => {
    // Check xem batch settings có thay đổi không (để biết có cần rebuild)
    const oldCfg = config
    const batchChanged = (
      oldCfg.batch_size_target !== newConfig.batch_size_target ||
      oldCfg.batch_size_max !== newConfig.batch_size_max ||
      oldCfg.gap_threshold_seconds !== newConfig.gap_threshold_seconds ||
      oldCfg.previous_context_lines !== newConfig.previous_context_lines
    )

    setConfig(newConfig)
    saveSimpleConfig(newConfig)
    try {
      await configApi.save(projectId, newConfig)
    } catch (err) {
      pushToast('error', 'Không lưu được config lên server, chỉ lưu local')
      return
    }

    // Nếu batch settings đổi → rebuild batches để áp dụng config mới
    if (batchChanged) {
      try {
        const next = await batchesApi.rebuild(projectId)
        setTranslateState(next)
        pushToast('success', `Đã lưu config + rebuild ${next.batches.length} batches`)
      } catch (err: any) {
        const detail = err?.response?.data?.detail || err?.message
        pushToast('error', 'Config saved nhưng rebuild batches lỗi: ' + detail)
      }
    } else {
      pushToast('success', 'Đã lưu config')
    }
  }, [projectId, config, pushToast])

  // Load initial state cho tab Bible (vì là tab default)
  useEffect(() => {
    bibleApi.getState(projectId).then(setBible).catch(err => {
      console.error('[Bible] load error', err)
      pushToast('error', 'Không tải được Bible: ' + (err.response?.data?.detail || err.message))
    })
  }, [projectId, pushToast])

  // ─── Load state khi đổi tab ───────────────────────────────────────────────

  useEffect(() => {
    if (activeTab === 'translate' && !translateState) {
      batchesApi.getState(projectId).then(setTranslateState).catch(err => {
        pushToast('error', 'Lỗi tải batches: ' + (err.response?.data?.detail || err.message))
      })
    } else if (activeTab === 'review' && !reviewState) {
      reviewApi.getState(projectId).then(setReviewState).catch(err => {
        pushToast('error', 'Lỗi tải review: ' + (err.response?.data?.detail || err.message))
      })
    }
  }, [activeTab, projectId, translateState, reviewState, pushToast])

  // ─── WebSocket: nhận update từ background tasks ───────────────────────────

  useSimpleWebSocket(projectId, {
    onBibleUpdate: (state) => setBible(state),
    onTranslateUpdate: (state) => setTranslateState(prev =>
      prev ? { ...state, active_batch_index: prev.active_batch_index } : state
    ),
    onReviewUpdate: (state) => setReviewState(state),
    onEvent: (event: SimpleEvent) => {
      // Debug — xem event tới FE (mở Console để theo dõi)
      console.log('[simple WS]', event.section, event.phase, event.task_id, event.data ? '(+data)' : '(no data)')

      // Update running task set
      setRunningTasks(prev => {
        const next = new Set(prev)
        if (event.phase === 'started' || event.phase === 'progress') {
          next.add(event.task_id)
        } else {
          next.delete(event.task_id)
        }
        return next
      })

      // Khi done/error → refetch state của section đó (đảm bảo update
      // kể cả khi event.data rỗng / state_loader lỗi ở BE).
      if (event.phase === 'done' || event.phase === 'error') {
        if (event.section === 'bible') {
          bibleApi.getState(projectId).then(setBible).catch(() => {})
        } else if (event.section === 'batches') {
          batchesApi.getState(projectId).then(s =>
            setTranslateState(prev => prev ? { ...s, active_batch_index: prev.active_batch_index } : s)
          ).catch(() => {})
        } else if (event.section === 'review') {
          reviewApi.getState(projectId).then(setReviewState).catch(() => {})
        }
      }

      // Toast cho done / error
      if (event.phase === 'done') {
        pushToast('success', event.message || 'Hoàn tất')
      } else if (event.phase === 'error') {
        pushToast('error', event.error || event.message || 'Có lỗi')
      }
    },
    onConnectionChange: setWsConnected,
  })

  // ─── Polling fallback ─────────────────────────────────────────────────────
  // Nếu WS không gửi được event 'done' (loop mismatch, proxy nuốt frame...),
  // poll state mỗi 3s khi có task đang chạy. Đảm bảo UI luôn cập nhật.
  useEffect(() => {
    if (runningTasks.size === 0) return
    const timer = setInterval(() => {
      // Refetch state của các section có task đang chạy
      const tasks = Array.from(runningTasks)
      if (tasks.some(t => t.startsWith('bible'))) {
        bibleApi.getState(projectId).then(s => {
          setBible(s)
          // Nếu tất cả parts done + (single hoặc merge done) → clear bible tasks
          const allDone = s.parts.every(p => p.status === 'done' || p.status === 'error')
          if (allDone) {
            setRunningTasks(prev => {
              const n = new Set(prev)
              Array.from(n).forEach(t => { if (t.startsWith('bible')) n.delete(t) })
              return n
            })
          }
        }).catch(() => {})
      }
      if (tasks.some(t => t.startsWith('batches'))) {
        batchesApi.getState(projectId).then(s => {
          setTranslateState(prev => prev ? { ...s, active_batch_index: prev.active_batch_index } : s)
          const running = s.batches.some(b => b.status === 'running')
          if (!running) {
            setRunningTasks(prev => {
              const n = new Set(prev)
              Array.from(n).forEach(t => { if (t.startsWith('batches')) n.delete(t) })
              return n
            })
          }
        }).catch(() => {})
      }
      if (tasks.some(t => t.startsWith('review'))) {
        reviewApi.getState(projectId).then(s => {
          setReviewState(s)
          const running = s.groups.some(g => g.status === 'running')
          if (!running) {
            setRunningTasks(prev => {
              const n = new Set(prev)
              Array.from(n).forEach(t => { if (t.startsWith('review')) n.delete(t) })
              return n
            })
          }
        }).catch(() => {})
      }
    }, 3000)
    return () => clearInterval(timer)
  }, [runningTasks, projectId])

  // ─── Action handlers (call BE, BE sẽ broadcast WS) ────────────────────────

  // Helper wrap call API + handle error
  async function callApi<T>(fn: () => Promise<T>, errorMsg: string): Promise<T | null> {
    try {
      return await fn()
    } catch (err: any) {
      const detail = err?.response?.data?.detail || err?.message || 'Unknown error'
      pushToast('error', `${errorMsg}: ${detail}`)
      return null
    }
  }

  // ─── Bible handlers ───────────────────────────────────────────────────────

  const bibleHandlers = {
    onChangeMode: async (mode: 'single' | 'multi', multi_parts_count?: number) => {
      const next = await callApi(
        () => bibleApi.changeMode(projectId, mode, multi_parts_count),
        'Lỗi đổi mode'
      )
      if (next) setBible(next)
    },
    onResponseChange: (idx: number | 'merge', value: string) => {
      // Local edit — chỉ update state, save thật chạy ở onSavePart
      if (!bible) return
      if (idx === 'merge') {
        if (!bible.merge) return
        setBible({
          ...bible,
          merge: { ...bible.merge, response: value },
        })
      } else {
        setBible({
          ...bible,
          parts: bible.parts.map(p =>
            p.index === idx ? { ...p, response: value } : p
          ),
        })
      }
    },
    onSavePart: async (idx: number | 'merge') => {
      if (!bible) return
      let response: string | null = null
      if (idx === 'merge') {
        response = bible.merge?.response || null
      } else {
        response = bible.parts.find(p => p.index === idx)?.response || null
      }
      if (!response) {
        pushToast('error', 'Response rỗng — chưa paste hoặc auto')
        return
      }
      const next = await callApi(
        () => idx === 'merge'
          ? bibleApi.saveMerge(projectId, response!)
          : bibleApi.savePart(projectId, idx, response!),
        'Lỗi lưu'
      )
      if (next) {
        setBible(next)
        pushToast('success', 'Đã lưu')
      }
    },
    onClearPart: (idx: number | 'merge') => {
      // Local clear — không gọi BE (BE không có endpoint clear riêng cho part)
      if (!bible) return
      if (idx === 'merge') {
        if (!bible.merge) return
        setBible({
          ...bible,
          merge: { ...bible.merge, response: null, status: 'idle' },
        })
      } else {
        setBible({
          ...bible,
          parts: bible.parts.map(p =>
            p.index === idx ? { ...p, response: null, status: 'idle' } : p
          ),
        })
      }
    },
    onRunPart: async (idx: number | 'merge') => {
      // Optimistic: set status='running' ngay để UI phản hồi tức thì
      if (bible) {
        if (idx === 'merge') {
          if (bible.merge) setBible({ ...bible, merge: { ...bible.merge, status: 'running' } })
        } else {
          setBible({
            ...bible,
            parts: bible.parts.map(p => p.index === idx ? { ...p, status: 'running' } : p),
          })
        }
      }
      // Track task ngay (badge "đang chạy")
      const tid = idx === 'merge' ? 'bible.merge' : `bible.part.${idx}`
      setRunningTasks(prev => new Set(prev).add(tid))

      const result = await callApi(
        () => idx === 'merge'
          ? bibleApi.autoMerge(projectId)
          : bibleApi.autoPart(projectId, idx),
        'Lỗi khởi động Auto'
      )
      if (result) {
        const taskLabel = idx === 'merge' ? 'merge' : `Part ${idx + 1}`
        pushToast('info', `Đang gọi LLM cho ${taskLabel}...`)
      } else {
        // API fail → revert running
        setRunningTasks(prev => { const n = new Set(prev); n.delete(tid); return n })
        bibleApi.getState(projectId).then(setBible).catch(() => {})
      }
    },
    onRunAll: async () => {
      const result = await callApi(
        () => bibleApi.runAll(projectId),
        'Lỗi khởi động Run All'
      )
      if (result) {
        pushToast('info', 'Đã khởi động Run All — theo dõi qua WS')
      }
    },
    onCopyAllPrompts: () => {
      if (!bible) return
      const all = bible.parts.map((p, i) =>
        `=== PART ${i + 1} ===\n${p.prompt}\n`
      ).join('\n')
      navigator.clipboard.writeText(all)
      pushToast('success', `Đã copy ${bible.parts.length} prompts`)
    },
    onReset: async () => {
      if (!confirm('Xóa toàn bộ Bible? Phải build lại từ đầu.')) return
      const result = await callApi(() => bibleApi.reset(projectId), 'Lỗi reset')
      if (result) {
        // Reload state
        const next = await callApi(() => bibleApi.getState(projectId), 'Lỗi reload')
        if (next) setBible(next)
        pushToast('success', 'Đã reset')
      }
    },
  }

  // ─── Translate handlers ───────────────────────────────────────────────────

  const translateHandlers = {
    onChangeActive: (idx: number) => {
      if (!translateState) return
      setTranslateState({ ...translateState, active_batch_index: idx })
    },
    onChangeMode: async (mode: 'normal' | 'turbo') => {
      const next = await callApi(
        () => batchesApi.updateConfig(projectId, { concurrency_mode: mode }),
        'Lỗi đổi mode'
      )
      if (next) setTranslateState(next)
    },
    onResponseChange: (idx: number, value: string) => {
      if (!translateState) return
      setTranslateState({
        ...translateState,
        batches: translateState.batches.map(b =>
          b.index === idx ? { ...b, response: value } : b
        ),
      })
    },
    onSaveBatch: async (idx: number) => {
      if (!translateState) return
      const response = translateState.batches.find(b => b.index === idx)?.response
      if (!response) {
        pushToast('error', 'Response rỗng')
        return
      }
      const prevActive = translateState.active_batch_index
      const next = await callApi(
        () => batchesApi.saveBatch(projectId, idx, response),
        'Lỗi lưu batch'
      )
      if (next) {
        // Giữ nguyên batch đang xem (BE trả active_batch_index=0 mặc định)
        setTranslateState({ ...next, active_batch_index: prevActive })
        pushToast('success', 'Đã lưu batch')
      }
    },
    onClearBatch: (idx: number) => {
      if (!translateState) return
      setTranslateState({
        ...translateState,
        batches: translateState.batches.map(b =>
          b.index === idx ? { ...b, response: null, status: 'idle' } : b
        ),
      })
    },
    onRunBatch: async (idx: number) => {
      // Optimistic: set batch running ngay
      if (translateState) {
        setTranslateState({
          ...translateState,
          batches: translateState.batches.map(b => b.index === idx ? { ...b, status: 'running' } : b),
        })
      }
      setRunningTasks(prev => new Set(prev).add(`batches.${idx}`))

      const result = await callApi(
        () => batchesApi.autoBatch(projectId, idx),
        'Lỗi auto batch'
      )
      if (result) {
        pushToast('info', `Đang dịch batch ${idx + 1}...`)
      } else {
        setRunningTasks(prev => { const n = new Set(prev); n.delete(`batches.${idx}`); return n })
        batchesApi.getState(projectId).then(s =>
          setTranslateState(prev => prev ? { ...s, active_batch_index: prev.active_batch_index } : s)
        ).catch(() => {})
      }
    },
    onRunAllFromCurrent: async () => {
      if (!translateState) return
      const fromIdx = translateState.active_batch_index
      // Optimistic: set tất cả batch idle từ fromIdx → running
      setTranslateState({
        ...translateState,
        batches: translateState.batches.map(b =>
          b.index >= fromIdx && b.status === 'idle' ? { ...b, status: 'running' } : b
        ),
      })
      setRunningTasks(prev => new Set(prev).add('batches.run-from'))

      const result = await callApi(
        () => batchesApi.runFrom(projectId, fromIdx, true),
        'Lỗi Run All'
      )
      if (result) {
        pushToast('info', 'Đang chạy Run All từ batch hiện tại...')
      } else {
        setRunningTasks(prev => { const n = new Set(prev); n.delete('batches.run-from'); return n })
        batchesApi.getState(projectId).then(s =>
          setTranslateState(prev => prev ? { ...s, active_batch_index: prev.active_batch_index } : s)
        ).catch(() => {})
      }
    },
    onRetranslate: async (idx: number) => {
      // Reset batch + auto run lại
      const reset = await callApi(
        () => batchesApi.resetBatch(projectId, idx),
        'Lỗi reset batch'
      )
      if (reset) {
        setTranslateState(reset)
        await callApi(() => batchesApi.autoBatch(projectId, idx), 'Lỗi auto batch')
        pushToast('info', `Đang dịch lại batch ${idx + 1}...`)
      }
    },
    onOpenConfig: () => setShowConfig(true),
    onRebuild: async () => {
      const next = await callApi(
        () => batchesApi.rebuild(projectId),
        'Lỗi rebuild batches'
      )
      if (next) {
        setTranslateState(next)
        pushToast('success', `Đã rebuild ${next.batches.length} batches (size ${next.config.batch_size_target})`)
      }
    },
  }

  // ─── Review handlers ──────────────────────────────────────────────────────

  const reviewHandlers = {
    onRunGroup: async (idx: number) => {
      setRunningTasks(prev => new Set(prev).add(`review.group.${idx}`))
      const result = await callApi(
        () => reviewApi.autoGroup(projectId, idx),
        'Lỗi auto review'
      )
      if (result) pushToast('info', `Đang review batch ${idx + 1}...`)
      else setRunningTasks(prev => { const n = new Set(prev); n.delete(`review.group.${idx}`); return n })
    },
    onRunAll: async () => {
      setRunningTasks(prev => new Set(prev).add('review.run-all'))
      const result = await callApi(
        () => reviewApi.runAll(projectId),
        'Lỗi Review tất cả'
      )
      if (result) pushToast('info', 'Đang review toàn bộ...')
      else setRunningTasks(prev => { const n = new Set(prev); n.delete('review.run-all'); return n })
    },
  }

  // ─── Tab badges ───────────────────────────────────────────────────────────

  const renderTabBadge = (key: SimpleTab) => {
    switch (key) {
      case 'bible':
        if (!bible) return <TabBadge>...</TabBadge>
        if (bible.master_characters_count > 0) {
          return <TabBadge tone="ok">✓ {bible.master_characters_count}</TabBadge>
        }
        return <TabBadge>—</TabBadge>

      case 'bible-view':
        if (!bible || !bible.master_bible_json) return <TabBadge>—</TabBadge>
        return <TabBadge tone="ok">{bible.master_characters_count}</TabBadge>

      case 'translate': {
        if (!translateState) return <TabBadge>...</TabBadge>
        const done = translateState.batches.filter(b => b.status === 'done').length
        const running = translateState.batches.some(b => b.status === 'running')
          || runningTasks.has('batches.run-from')
          || Array.from(runningTasks).some(t => t.startsWith('batches.'))
        return (
          <TabBadge tone="info" pulse={running}>
            {done} / {translateState.batches.length}
          </TabBadge>
        )
      }

      case 'subtitles': {
        if (!translateState) return <TabBadge>—</TabBadge>
        return <TabBadge tone="info">{translateState.total_translated} / {translateState.total_translated + translateState.total_pending}</TabBadge>
      }

      case 'review': {
        if (!reviewState) return <TabBadge>—</TabBadge>
        const total = reviewState.groups.length
        if (total === 0) return <TabBadge>—</TabBadge>
        const done = reviewState.groups.filter(g => g.status === 'done').length
        return <TabBadge tone="info">{done} / {total}</TabBadge>
      }

      default:
        return null
    }
  }

  // ─── Tab content ──────────────────────────────────────────────────────────

  const renderActiveTab = () => {
    switch (activeTab) {
      case 'bible':
        if (!bible) return <Loading label="Bible" />
        return (
          <BibleTab
            state={bible}
            totalSrtLines={totalSrtLines}
            totalSrtTokens={totalSrtTokens}
            {...bibleHandlers}
          />
        )

      case 'bible-view':
        if (!bible) return <Loading label="Bible" />
        return <BibleViewTab state={bible} />

      case 'translate':
        if (!translateState) return <Loading label="Batches" />
        return (
          <TranslateTab
            state={translateState}
            {...translateHandlers}
          />
        )

      case 'subtitles':
        return <SubtitlesViewTab projectId={projectId} />

      case 'review':
        return (
          <ReviewTab
            projectId={projectId}
            runningTasks={runningTasks}
            onRunGroup={reviewHandlers.onRunGroup}
            onRunAll={reviewHandlers.onRunAll}
          />
        )

      default:
        return null
    }
  }

  // ─── Config status (badge nhỏ ở header) ───────────────────────────────────

  const hasAnyApiKey = !!(
    config.api_keys.gemini || config.api_keys.openai || config.api_keys.deepseek
  )

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="h-full flex flex-col surface">
      {/* Top bar */}
      <div className="flex items-center gap-3 px-4 py-2.5 bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800">
        <button
          onClick={async () => {
            // Auto sync simple_text_vi → text legacy trước khi về Editor
            try {
              await batchesApi.syncToEditor(projectId)
            } catch (e) {
              console.warn('[sync-to-editor on back] failed', e)
            }
            onBack()
          }}
          className="btn"
          title="Tự sync bản dịch sang Editor cũ trước khi quay về"
        >
          ← Editor
        </button>
        <h1 className="text-[15px] font-semibold text-zinc-900 dark:text-zinc-100">
          {projectName}
        </h1>
        <span className="font-mono text-[11px] text-zinc-500 dark:text-zinc-500 uppercase tracking-wider">
          {totalSrtLines.toLocaleString()} dòng
          {bible && bible.master_characters_count > 0 && (
            <> · {bible.master_characters_count} nhân vật</>
          )}
        </span>
        <div className="flex-1" />

        {/* Sync to Editor button */}
        <button
          onClick={async () => {
            const r = await callApi(
              () => batchesApi.syncToEditor(projectId),
              'Lỗi sync'
            )
            if (r) pushToast('success', r.message || 'Đã sync sang Editor')
          }}
          className="btn"
          title="Copy simple_text_vi → text (Editor cũ) + map speaker → character"
        >
          ↻ Sync Editor
        </button>

        {/* Config button */}
        <button
          onClick={() => setShowConfig(true)}
          className={`btn ${!hasAnyApiKey ? 'border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300' : ''}`}
          title="Cấu hình API keys, models, batch size..."
        >
          ⚙ Cấu hình
          {!hasAnyApiKey && (
            <span className="ml-1 text-[10px] bg-amber-500 text-white px-1 rounded">!</span>
          )}
        </button>

        {/* WS status */}
        <span
          className={`inline-flex items-center gap-2 px-2.5 py-1 rounded-md text-[11px] font-medium uppercase tracking-wider border ${
            wsConnected
              ? (runningTasks.size > 0
                  ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/30 dark:text-blue-300'
                  : 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/30 dark:text-emerald-300')
              : 'bg-zinc-50 text-zinc-500 border-zinc-200 dark:bg-zinc-900 dark:text-zinc-500'
          }`}
        >
          <span className={`w-1.5 h-1.5 rounded-full bg-current ${runningTasks.size > 0 ? 'animate-pulse' : ''}`} />
          {!wsConnected
            ? 'Mất kết nối'
            : runningTasks.size > 0
              ? `Đang chạy · ${runningTasks.size} task${runningTasks.size > 1 ? 's' : ''}`
              : 'Sẵn sàng'}
        </span>
      </div>

      {/* Tabs */}
      <div className="flex items-stretch gap-1 px-4 bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800">
        {TAB_META.map(({ key, num, label }) => {
          const isActive = activeTab === key
          return (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`flex items-center gap-2 px-3.5 py-2.5 text-[13px] font-medium transition-all border-b-2 -mb-px ${
                isActive
                  ? 'border-blue-600 text-zinc-900 dark:text-zinc-100'
                  : 'border-transparent text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'
              }`}
            >
              <TabNumber n={num} active={isActive} />
              <span>{label}</span>
              {renderTabBadge(key)}
            </button>
          )
        })}
      </div>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto px-6 py-5">
        <div className="max-w-[1280px] mx-auto">
          {renderActiveTab()}
        </div>
      </div>

      {/* Config modal */}
      {showConfig && (
        <ConfigPanel
          initialConfig={config}
          onClose={() => setShowConfig(false)}
          onSave={saveConfigBoth}
        />
      )}

      {/* Toasts */}
      <div className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 pointer-events-none">
        {toasts.map(t => (
          <div
            key={t.id}
            className={`px-4 py-2.5 rounded-lg shadow-lg text-[13px] font-medium animate-in slide-in-from-right pointer-events-auto ${
              t.type === 'success' ? 'bg-emerald-600 text-white' :
              t.type === 'error'   ? 'bg-red-600 text-white' :
                                     'bg-zinc-800 text-white'
            }`}
          >
            {t.message}
          </div>
        ))}
      </div>
    </div>
  )
}


// ─── Loading placeholder ─────────────────────────────────────────────────────

function Loading({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-zinc-500">
      <div className="w-8 h-8 border-2 border-zinc-300 border-t-blue-500 rounded-full animate-spin mb-3" />
      <div className="text-[13px]">Đang tải {label}...</div>
    </div>
  )
}
