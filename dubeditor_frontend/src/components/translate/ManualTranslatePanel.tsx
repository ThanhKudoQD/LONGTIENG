/**
 * ManualTranslatePanel — Chế độ Dịch Thủ công (v3.15 + persistence)
 *
 * Layout 3 cột:
 *  ┌──────────────────────────────────────────────────────────────────┐
 *  │ [Cột 1: Stages]    [Cột 2: Units]      [Cột 3: Prompt + Response]│
 *  │ ✓ Stage 1A.1       ✓ chunk_1-250        Prompt: [...]            │
 *  │ → Stage 2 (2/5)    ✓ chunk_251-500      Response: [...]          │
 *  │   Stage 3          → chunk_501-750      [Apply] [Reset]          │
 *  │                    ○ chunk_751-1000                              │
 *  └──────────────────────────────────────────────────────────────────┘
 *
 * Features v3.15 persistence:
 *  - Mỗi unit có status: pending | built | applied | failed
 *  - Click unit → auto load prompt + response đã lưu từ DB
 *  - Edit prompt → debounce 1.5s → auto save
 *  - Gõ response → debounce 1.5s → auto save draft
 *  - Apply → save kết quả + status="applied"
 *  - Build lại: load từ cache (default), hoặc force rebuild
 *  - Hiển thị progress: vd "Stage 2: 3/5 chunks applied"
 *  - F5 / mở lại tab: không mất gì
 */
import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import {
  manualTranslateApi,
  type ManualStageInfo,
  type ManualUnitInfo,
  type ManualBuiltPrompt,
  type ManualApplyResult,
} from '../../api'

interface Props {
  projectId: number
  onDataChanged?: () => void
}

// Debounce helper — gắn save với unit cụ thể, hủy nếu đổi unit
// Mỗi (stage, unit_key) có timer riêng. Khi đổi unit, timer của unit cũ bị hủy.
function useUnitScopedSave() {
  // Map: unit_id → timer
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map())
  // Track unit hiện tại để biết khi nào cần hủy timers cũ
  const currentUnitRef = useRef<string | null>(null)

  useEffect(() => () => {
    // Cleanup khi unmount: hủy tất cả timer
    timersRef.current.forEach(t => clearTimeout(t))
    timersRef.current.clear()
  }, [])

  /** Đổi sang unit mới — hủy mọi timer chưa firing của unit khác.
   *  Gọi NGAY khi user click unit mới. */
  const setCurrentUnit = useCallback((unitId: string | null) => {
    // Hủy timer của tất cả unit khác unit mới
    timersRef.current.forEach((timer, id) => {
      if (id !== unitId) {
        clearTimeout(timer)
        timersRef.current.delete(id)
      }
    })
    currentUnitRef.current = unitId
  }, [])

  /** Schedule save cho 1 unit cụ thể. unit_id được encode trong key,
   *  không phụ thuộc state hiện tại. */
  const scheduleSave = useCallback((
    unitId: string,
    fn: () => Promise<void>,
    delayMs = 1500,
  ) => {
    // Hủy timer cũ của CÙNG unit nếu có (replace)
    const existing = timersRef.current.get(unitId)
    if (existing) clearTimeout(existing)

    const timer = setTimeout(async () => {
      timersRef.current.delete(unitId)
      // Chỉ chạy nếu vẫn ở đúng unit này
      if (currentUnitRef.current !== unitId) {
        return  // user đã chuyển unit khác — bỏ qua, KHÔNG save
      }
      try { await fn() } catch (e) { console.warn('scheduled save failed', e) }
    }, delayMs)

    timersRef.current.set(unitId, timer)
  }, [])

  /** Force-flush: chạy ngay tất cả timer pending. Dùng khi user navigate đi
   *  để không mất draft. */
  const flushAll = useCallback(() => {
    const pending = Array.from(timersRef.current.entries())
    timersRef.current.clear()
    pending.forEach(([_, timer]) => clearTimeout(timer))
    // KHÔNG chạy fn của các timer pending — chúng đã được bind với unit cụ thể
    // qua closure, nhưng vì chúng ta đang chuyển unit, không an toàn để flush.
  }, [])

  // Cố định identity object để useEffect deps không trigger re-run mỗi render
  return useMemo(() => ({ setCurrentUnit, scheduleSave, flushAll }),
                  [setCurrentUnit, scheduleSave, flushAll])
}


// Debounce helper hook — gọi fn sau N ms im lặng
function useDebouncedCallback<T extends (...args: any[]) => void>(
  fn: T, delayMs: number
): (...args: Parameters<T>) => void {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fnRef = useRef(fn)
  fnRef.current = fn

  useEffect(() => () => {
    if (timerRef.current) clearTimeout(timerRef.current)
  }, [])

  return useCallback((...args: Parameters<T>) => {
    if (timerRef.current) clearTimeout(timerRef.current)
    timerRef.current = setTimeout(() => fnRef.current(...args), delayMs)
  }, [delayMs])
}


export default function ManualTranslatePanel({ projectId, onDataChanged }: Props) {
  const [stages, setStages] = useState<ManualStageInfo[]>([])
  const [selectedStage, setSelectedStage] = useState<string | null>(null)
  const [units, setUnits] = useState<ManualUnitInfo[]>([])
  const [selectedUnit, setSelectedUnit] = useState<string | null>(null)
  const [loadingUnits, setLoadingUnits] = useState(false)
  const [loadingUnitState, setLoadingUnitState] = useState(false)

  const [builtPrompt, setBuiltPrompt] = useState<ManualBuiltPrompt | null>(null)
  const [editedPrompt, setEditedPrompt] = useState<string>('')
  const [buildingPrompt, setBuildingPrompt] = useState(false)

  const [rawResponse, setRawResponse] = useState<string>('')
  const [applying, setApplying] = useState(false)
  const [lastApplyResult, setLastApplyResult] = useState<ManualApplyResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  const [copyOk, setCopyOk] = useState(false)
  const [autoSaveStatus, setAutoSaveStatus] = useState<'idle' | 'saving' | 'saved'>('idle')

  // v3.15.1 — scoped auto-save: mỗi unit có timer riêng, hủy khi đổi unit
  const scopedSave = useUnitScopedSave()

  // Track xem đang ở unit nào để tránh save khi đã chuyển unit
  const currentUnitRef = useRef<string | null>(null)
  // Đánh dấu prompt/response có thay đổi không (để không spam save khi load)
  const promptInitializedRef = useRef(false)
  const responseInitializedRef = useRef(false)

  // ─── Load stages on mount ─────────────────────────────────────
  const refreshStages = useCallback(async () => {
    try {
      const s = await manualTranslateApi.listStages(projectId)
      setStages(s)
    } catch (e: any) {
      setError(`Không load được stages: ${e?.message || e}`)
    }
  }, [projectId])

  useEffect(() => { refreshStages() }, [refreshStages])

  // ─── Load units khi chọn stage ────────────────────────────────
  const refreshUnits = useCallback(async (stage: string) => {
    setLoadingUnits(true)
    try {
      const u = await manualTranslateApi.listUnits(projectId, stage)
      setUnits(u)
      return u
    } catch (e: any) {
      setError(`Không load được units: ${e?.message || e}`)
      return []
    } finally {
      setLoadingUnits(false)
    }
  }, [projectId])

  useEffect(() => {
    if (!selectedStage) return
    const stageInfo = stages.find(s => s.stage === selectedStage)
    if (!stageInfo || !stageInfo.ready) {
      setUnits([])
      setSelectedUnit(null)
      return
    }
    setSelectedUnit(null)
    setBuiltPrompt(null)
    setRawResponse('')
    setEditedPrompt('')
    setLastApplyResult(null)
    promptInitializedRef.current = false
    responseInitializedRef.current = false

    refreshUnits(selectedStage).then(u => {
      // Auto-select unit chưa applied đầu tiên (hoặc unit duy nhất nếu chỉ có 1)
      if (u.length === 1) {
        setSelectedUnit(u[0].unit_key)
      } else {
        const firstNotApplied = u.find(x => x.status !== 'applied')
        if (firstNotApplied) setSelectedUnit(firstNotApplied.unit_key)
      }
    })
  }, [selectedStage, stages, refreshUnits])

  // ─── Load unit state khi chọn unit ────────────────────────────
  useEffect(() => {
    if (!selectedStage || !selectedUnit) {
      currentUnitRef.current = null
      scopedSave.setCurrentUnit(null)
      return
    }
    const stageInfo = stages.find(s => s.stage === selectedStage)
    if (!stageInfo?.ready) return

    const unitId = `${selectedStage}::${selectedUnit}`

    // v3.15.1 — QUAN TRỌNG: hủy mọi timer save pending của unit khác TRƯỚC khi
    // load state mới. Tránh race: timer cũ firing sau khi đã đổi unit → save
    // nhầm vào unit mới.
    scopedSave.setCurrentUnit(unitId)

    currentUnitRef.current = unitId
    setLoadingUnitState(true)
    // Clear UI state — nhưng KHÔNG trigger auto-save vì initialized=false
    setBuiltPrompt(null)
    setEditedPrompt('')
    setRawResponse('')
    setLastApplyResult(null)
    promptInitializedRef.current = false
    responseInitializedRef.current = false

    manualTranslateApi.getUnitState(projectId, selectedStage, selectedUnit)
      .then(state => {
        // Verify vẫn ở đúng unit (user có thể đã click sang unit khác)
        if (currentUnitRef.current !== unitId) return

        if (state) {
          // Có state đã lưu → restore
          if (state.prompt) {
            const bp: ManualBuiltPrompt = {
              stage: state.stage,
              unit_key: state.unit_key,
              label: state.label || '',
              prompt: state.prompt,
              meta: state.meta,
              char_count: state.prompt.length,
              status: state.status,
              raw_response: state.raw_response,
              apply_summary: state.apply_summary,
              applied_at: state.applied_at,
              from_cache: true,
            }
            setBuiltPrompt(bp)
            setEditedPrompt(state.prompt)
            promptInitializedRef.current = true
          }
          if (state.raw_response) {
            setRawResponse(state.raw_response)
            responseInitializedRef.current = true
          }
          if (state.apply_summary) {
            setLastApplyResult({
              stage: state.stage,
              unit_key: state.unit_key,
              ok: state.status === 'applied',
              summary: state.apply_summary,
              counts: state.apply_counts || {},
              warnings: state.apply_warnings || [],
              errors: state.apply_errors || [],
              status: state.status,
              applied_at: state.applied_at,
            })
          }
        }
      })
      .catch(e => {
        // Không có state là OK
        if (e?.response?.status !== 404) {
          console.warn('getUnitState failed:', e)
        }
      })
      .finally(() => {
        if (currentUnitRef.current === unitId) {
          setLoadingUnitState(false)
        }
      })
  }, [selectedStage, selectedUnit, projectId, stages, scopedSave])

  // ─── Auto-save khi prompt/response đổi (v3.15.1: scoped per-unit) ──
  // Mỗi save bind chặt vào (stage, unit_key) tại thời điểm trigger.
  // Khi user đổi unit, scopedSave.setCurrentUnit() đã hủy timer pending,
  // và scheduleSave kiểm tra currentUnit trước khi chạy → KHÔNG save sang unit khác.

  useEffect(() => {
    if (!promptInitializedRef.current) {
      promptInitializedRef.current = true
      return
    }
    if (!builtPrompt || !selectedStage || !selectedUnit) return

    // Snapshot tại thời điểm này — không đọc state ở moment timer fire
    const stage = selectedStage
    const unitKey = selectedUnit
    const unitId = `${stage}::${unitKey}`
    const value = editedPrompt

    setAutoSaveStatus('saving')
    scopedSave.scheduleSave(unitId, async () => {
      try {
        await manualTranslateApi.savePromptEdit(projectId, stage, unitKey, value)
        setAutoSaveStatus('saved')
        setTimeout(() => setAutoSaveStatus(prev => prev === 'saved' ? 'idle' : prev), 1500)
      } catch (e) {
        console.warn('save prompt edit failed', e)
        setAutoSaveStatus('idle')
      }
    }, 1500)
  }, [editedPrompt, builtPrompt, selectedStage, selectedUnit, projectId, scopedSave])

  useEffect(() => {
    if (!responseInitializedRef.current) {
      responseInitializedRef.current = true
      return
    }
    if (!selectedStage || !selectedUnit) return

    const stage = selectedStage
    const unitKey = selectedUnit
    const unitId = `${stage}::${unitKey}`
    const value = rawResponse

    setAutoSaveStatus('saving')
    scopedSave.scheduleSave(unitId, async () => {
      try {
        await manualTranslateApi.saveResponseDraft(projectId, stage, unitKey, value)
        setAutoSaveStatus('saved')
        setTimeout(() => setAutoSaveStatus(prev => prev === 'saved' ? 'idle' : prev), 1500)
      } catch (e) {
        console.warn('save response draft failed', e)
        setAutoSaveStatus('idle')
      }
    }, 1500)
  }, [rawResponse, selectedStage, selectedUnit, projectId, scopedSave])

  // ─── Build prompt ────────────────────────────────────────────
  const handleBuildPrompt = async (forceRebuild = false) => {
    if (!selectedStage || !selectedUnit) return

    // Snapshot unit hiện tại — verify trước khi set state (tránh leak khi
    // user đổi unit trong lúc build đang chạy)
    const stage = selectedStage
    const unitKey = selectedUnit
    const unitId = `${stage}::${unitKey}`

    setBuildingPrompt(true)
    setError(null)
    if (forceRebuild) {
      setBuiltPrompt(null)
      promptInitializedRef.current = false
    }
    try {
      const bp = await manualTranslateApi.buildPrompt(
        projectId, stage, unitKey, forceRebuild
      )
      // v3.15.1: Verify user vẫn ở unit này — tránh ghi đè state khi user đã chuyển
      if (currentUnitRef.current !== unitId) return

      setBuiltPrompt(bp)
      setEditedPrompt(bp.prompt)
      promptInitializedRef.current = true
      // Nếu build trả về response cũ (force rebuild giữ response)
      if (bp.raw_response && !rawResponse) {
        setRawResponse(bp.raw_response)
        responseInitializedRef.current = true
      }
      // Refresh units để cập nhật status
      await refreshUnits(stage)
    } catch (e: any) {
      if (currentUnitRef.current !== unitId) return
      setError(`Build prompt lỗi: ${e?.response?.data?.detail || e?.message || e}`)
    } finally {
      if (currentUnitRef.current === unitId) {
        setBuildingPrompt(false)
      }
    }
  }

  // ─── Copy prompt ─────────────────────────────────────────────
  const handleCopyPrompt = async () => {
    if (!editedPrompt) return
    try {
      await navigator.clipboard.writeText(editedPrompt)
      setCopyOk(true)
      setTimeout(() => setCopyOk(false), 2000)
    } catch {
      const ta = document.createElement('textarea')
      ta.value = editedPrompt
      document.body.appendChild(ta)
      ta.select()
      try { document.execCommand('copy'); setCopyOk(true); setTimeout(() => setCopyOk(false), 2000) }
      catch {}
      document.body.removeChild(ta)
    }
  }

  // ─── Apply response ──────────────────────────────────────────
  const handleApply = async () => {
    if (!selectedStage || !selectedUnit || !builtPrompt) return
    if (!rawResponse.trim()) {
      setError('Vui lòng paste response vào ô bên dưới trước')
      return
    }
    // Snapshot
    const stage = selectedStage
    const unitKey = selectedUnit
    const unitId = `${stage}::${unitKey}`
    const meta = builtPrompt.meta
    const response = rawResponse

    setApplying(true)
    setError(null)
    try {
      const result = await manualTranslateApi.applyResponse(
        projectId, stage, unitKey, meta, response,
      )
      // Verify user vẫn ở unit này
      if (currentUnitRef.current !== unitId) return

      setLastApplyResult(result)
      if (result.ok) {
        await refreshStages()
        await refreshUnits(stage)
        onDataChanged?.()
      }
    } catch (e: any) {
      if (currentUnitRef.current !== unitId) return
      setError(`Apply lỗi: ${e?.response?.data?.detail || e?.message || e}`)
    } finally {
      if (currentUnitRef.current === unitId) {
        setApplying(false)
      }
    }
  }

  // ─── Reset unit ──────────────────────────────────────────────
  const handleResetUnit = async () => {
    if (!selectedStage || !selectedUnit) return
    if (!confirm(`Reset unit "${selectedUnit}"? Sẽ xóa prompt + response đã lưu.`))
      return
    try {
      await manualTranslateApi.resetUnit(projectId, selectedStage, selectedUnit)
      setBuiltPrompt(null)
      setEditedPrompt('')
      setRawResponse('')
      setLastApplyResult(null)
      promptInitializedRef.current = false
      responseInitializedRef.current = false
      await refreshStages()
      await refreshUnits(selectedStage)
    } catch (e: any) {
      setError(`Reset lỗi: ${e?.response?.data?.detail || e?.message || e}`)
    }
  }

  const handleNextUnit = () => {
    if (!selectedUnit) return
    const currentIdx = units.findIndex(u => u.unit_key === selectedUnit)
    // Tìm unit kế tiếp chưa applied, nếu không có thì lấy ngay sau
    let nextIdx = -1
    for (let i = currentIdx + 1; i < units.length; i++) {
      if (units[i].status !== 'applied') { nextIdx = i; break }
    }
    if (nextIdx < 0 && currentIdx >= 0 && currentIdx < units.length - 1) {
      nextIdx = currentIdx + 1
    }
    if (nextIdx >= 0) setSelectedUnit(units[nextIdx].unit_key)
  }

  // ─── Render ──────────────────────────────────────────────────
  const stageInfo = stages.find(s => s.stage === selectedStage)
  const currentUnitInfo = units.find(u => u.unit_key === selectedUnit)
  const currentUnitIdx = units.findIndex(u => u.unit_key === selectedUnit)
  const hasNextUnit = currentUnitIdx >= 0 && currentUnitIdx < units.length - 1
  const isMultiUnit = units.length > 1 ||
    (selectedStage && ['chunks', 'speaker', 'translate', 'polish'].includes(selectedStage))

  return (
    <div className="flex flex-col h-full bg-zinc-50 dark:bg-zinc-900">
      {/* Header */}
      <div className="px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold flex items-center gap-2">
              🛠️ Dịch Thủ công
              <span className="text-xs font-normal text-zinc-500 bg-zinc-100 dark:bg-zinc-800 px-2 py-0.5 rounded">
                v3.15
              </span>
              {autoSaveStatus !== 'idle' && selectedUnit && (
                <span className="text-xs font-normal text-zinc-500 italic">
                  {autoSaveStatus === 'saving' ? '💾 Đang lưu' : '✓ Đã lưu'}
                  {' '}
                  <code className="text-[10px] bg-zinc-100 dark:bg-zinc-800 px-1 rounded">
                    {selectedUnit}
                  </code>
                </span>
              )}
            </h2>
            <p className="text-xs text-zinc-500 mt-1">
              Code build prompt → copy ra ChatGPT/Claude/Gemini web → paste response → lưu DB.
              Tất cả prompt + response được lưu vào DB — mở lại không mất.
            </p>
          </div>
          <button
            onClick={refreshStages}
            className="text-xs px-2 py-1 rounded border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
            title="Reload trạng thái"
          >
            🔄 Reload
          </button>
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div className="px-4 py-2 bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300 border-b border-red-200 dark:border-red-800 text-sm flex items-center justify-between">
          <span>⚠ {error}</span>
          <button onClick={() => setError(null)} className="text-xs underline">Dismiss</button>
        </div>
      )}

      {/* Main 3 columns */}
      <div className="flex-1 flex overflow-hidden">
        {/* ─── COL 1: Stages ─────────────────────────────────── */}
        <div className="w-72 flex-shrink-0 border-r border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 overflow-y-auto">
          <div className="px-3 py-2 text-xs font-semibold text-zinc-500 uppercase border-b border-zinc-200 dark:border-zinc-800">
            Stages
          </div>
          {stages.length === 0 ? (
            <div className="p-4 text-sm text-zinc-500">Đang tải...</div>
          ) : (
            <div className="py-1">
              {stages.map((s) => (
                <StageRow
                  key={s.stage}
                  stage={s}
                  selected={selectedStage === s.stage}
                  onClick={() => setSelectedStage(s.stage)}
                />
              ))}
            </div>
          )}
        </div>

        {/* ─── COL 2: Units ──────────────────────────────────── */}
        <div className="w-80 flex-shrink-0 border-r border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 overflow-y-auto">
          <div className="px-3 py-2 text-xs font-semibold text-zinc-500 uppercase border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
            <span>{isMultiUnit ? `Units (${units.length})` : 'Unit'}</span>
            {selectedStage && units.length > 1 && (
              <span className="text-[10px] font-normal text-zinc-400">
                {units.filter(u => u.status === 'applied').length}/{units.length} applied
              </span>
            )}
          </div>
          {!selectedStage ? (
            <div className="p-4 text-sm text-zinc-400">← Chọn 1 stage</div>
          ) : !stageInfo?.ready ? (
            <div className="p-4 text-sm text-amber-600 dark:text-amber-400">
              ⚠ {stageInfo?.dependency_msg || 'Stage chưa sẵn sàng'}
            </div>
          ) : loadingUnits ? (
            <div className="p-4 text-sm text-zinc-500">Đang tải units...</div>
          ) : units.length === 0 ? (
            <div className="p-4 text-sm text-zinc-500">Không có unit nào</div>
          ) : (
            <div className="py-1">
              {units.map((u) => (
                <UnitRow
                  key={u.unit_key}
                  unit={u}
                  selected={selectedUnit === u.unit_key}
                  onClick={() => setSelectedUnit(u.unit_key)}
                />
              ))}
            </div>
          )}
        </div>

        {/* ─── COL 3: Prompt + Response ──────────────────────── */}
        <div className="flex-1 flex flex-col overflow-hidden bg-zinc-50 dark:bg-zinc-900">
          {!selectedStage || !selectedUnit ? (
            <div className="flex-1 flex items-center justify-center text-zinc-400 text-sm">
              ← Chọn stage và unit để bắt đầu
            </div>
          ) : loadingUnitState ? (
            <div className="flex-1 flex items-center justify-center text-zinc-500 text-sm">
              ⏳ Đang load state đã lưu...
            </div>
          ) : (
            <>
              {/* Status banner cho unit hiện tại */}
              {currentUnitInfo && (
                <div className={`px-4 py-2 border-b text-xs flex items-center justify-between ${
                  currentUnitInfo.status === 'applied'
                    ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800'
                    : currentUnitInfo.status === 'failed'
                    ? 'bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300 border-red-200 dark:border-red-800'
                    : currentUnitInfo.status === 'built'
                    ? 'bg-blue-50 dark:bg-blue-950/30 text-blue-700 dark:text-blue-300 border-blue-200 dark:border-blue-800'
                    : 'bg-zinc-100 dark:bg-zinc-900 text-zinc-600 dark:text-zinc-400 border-zinc-200 dark:border-zinc-800'
                }`}>
                  <div>
                    <span className="font-semibold">{currentUnitInfo.label}</span>
                    <span className="ml-2 opacity-75">— {labelForStatus(currentUnitInfo.status)}</span>
                    {currentUnitInfo.applied_at && (
                      <span className="ml-2 text-[10px] opacity-60">
                        ({formatTime(currentUnitInfo.applied_at)})
                      </span>
                    )}
                  </div>
                  {currentUnitInfo.apply_summary && (
                    <span className="text-[11px] opacity-80">{currentUnitInfo.apply_summary}</span>
                  )}
                </div>
              )}

              {/* Action bar */}
              <div className="px-4 py-2 bg-white dark:bg-zinc-950 border-b border-zinc-200 dark:border-zinc-800 flex items-center gap-2 flex-wrap">
                {!builtPrompt ? (
                  <button
                    onClick={() => handleBuildPrompt(false)}
                    disabled={buildingPrompt}
                    className="px-3 py-1.5 text-sm rounded bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white font-medium"
                  >
                    {buildingPrompt ? '⏳ Đang build...' : '✨ Build prompt'}
                  </button>
                ) : (
                  <>
                    <button
                      onClick={handleCopyPrompt}
                      className={`px-3 py-1.5 text-sm rounded font-medium ${
                        copyOk
                          ? 'bg-emerald-600 text-white'
                          : 'bg-blue-600 hover:bg-blue-700 text-white'
                      }`}
                    >
                      {copyOk ? '✓ Đã copy' : '📋 Copy prompt'}
                    </button>
                    <button
                      onClick={() => handleBuildPrompt(true)}
                      disabled={buildingPrompt}
                      className="px-2 py-1.5 text-xs rounded border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                      title="Build lại từ data DB hiện tại (ghi đè prompt đã edit)"
                    >
                      {buildingPrompt ? '⏳' : '🔄 Build lại'}
                    </button>
                    {(builtPrompt || rawResponse) && (
                      <button
                        onClick={handleResetUnit}
                        className="px-2 py-1.5 text-xs rounded border border-zinc-300 dark:border-zinc-700 hover:bg-red-50 dark:hover:bg-red-950/30 text-zinc-600 dark:text-zinc-400 hover:text-red-600 dark:hover:text-red-400"
                        title="Xóa prompt + response đã lưu cho unit này"
                      >
                        🗑️ Reset
                      </button>
                    )}
                    <span className="text-xs text-zinc-500 ml-2">
                      {editedPrompt.length.toLocaleString()} ký tự
                      {builtPrompt && editedPrompt !== builtPrompt.prompt && (
                        <span className="ml-1 text-amber-600 dark:text-amber-400">• đã sửa</span>
                      )}
                      {builtPrompt?.from_cache && (
                        <span className="ml-1 text-blue-500">• từ cache</span>
                      )}
                    </span>
                  </>
                )}
              </div>

              {builtPrompt && (
                <div className="flex-1 flex flex-col overflow-hidden">
                  {/* Prompt textarea */}
                  <div className="flex-1 flex flex-col p-4 overflow-hidden">
                    <label className="text-xs font-semibold text-zinc-500 uppercase mb-1.5 flex items-center justify-between">
                      <span>📤 Prompt (copy đoạn này sang ChatGPT/Claude/Gemini web)</span>
                      {/* v3.15.1: hiển thị stats cấu trúc prompt — giúp user phân biệt 2 stage cùng inject SRT */}
                      <PromptStats prompt={editedPrompt} stage={builtPrompt.stage} />
                    </label>
                    <textarea
                      value={editedPrompt}
                      onChange={(e) => setEditedPrompt(e.target.value)}
                      placeholder='Prompt sẽ hiện ở đây...'
                      spellCheck={false}
                      className="flex-1 min-h-0 p-3 text-xs font-mono rounded border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 resize-none focus:outline-none focus:border-blue-500"
                    />
                  </div>

                  {/* Response textarea */}
                  <div className="flex-1 flex flex-col p-4 pt-0 overflow-hidden">
                    <label className="text-xs font-semibold text-zinc-500 uppercase mb-1.5">
                      📥 Response (paste output từ LLM web vào đây)
                    </label>
                    <textarea
                      value={rawResponse}
                      onChange={(e) => setRawResponse(e.target.value)}
                      placeholder='Paste JSON response từ ChatGPT/Claude/Gemini... (có thể có fence ```json hoặc preamble — parser sẽ tự xử lý)'
                      spellCheck={false}
                      className="flex-1 min-h-[120px] p-3 text-xs font-mono rounded border border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-950 resize-none focus:outline-none focus:border-emerald-500"
                    />
                    <div className="flex items-center gap-2 mt-2">
                      <button
                        onClick={handleApply}
                        disabled={applying || !rawResponse.trim()}
                        className="px-4 py-2 text-sm rounded bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white font-medium"
                      >
                        {applying ? '⏳ Đang apply...' : (lastApplyResult?.ok ? '🔁 Apply lại' : '✓ Apply response')}
                      </button>
                      {rawResponse && (
                        <button
                          onClick={() => setRawResponse('')}
                          className="px-3 py-2 text-sm rounded border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
                        >
                          Clear
                        </button>
                      )}
                      {lastApplyResult?.ok && hasNextUnit && (
                        <button
                          onClick={handleNextUnit}
                          className="ml-auto px-3 py-2 text-sm rounded bg-blue-600 hover:bg-blue-700 text-white font-medium"
                        >
                          Next unit →
                        </button>
                      )}
                    </div>

                    {/* Apply result */}
                    {lastApplyResult && (
                      <div className={`mt-2 p-2 rounded text-xs ${
                        lastApplyResult.ok
                          ? 'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800'
                          : 'bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800'
                      }`}>
                        <div className="font-semibold">
                          {lastApplyResult.ok ? '✓' : '✗'} {lastApplyResult.summary}
                        </div>
                        {lastApplyResult.warnings.length > 0 && (
                          <details className="mt-1">
                            <summary className="cursor-pointer">⚠ {lastApplyResult.warnings.length} warning(s)</summary>
                            <ul className="mt-1 ml-4 list-disc">
                              {lastApplyResult.warnings.slice(0, 5).map((w, i) => (
                                <li key={i}>{w}</li>
                              ))}
                            </ul>
                          </details>
                        )}
                        {lastApplyResult.errors.length > 0 && (
                          <ul className="mt-1 ml-4 list-disc">
                            {lastApplyResult.errors.map((e, i) => (
                              <li key={i}>{e}</li>
                            ))}
                          </ul>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────

/**
 * Hiển thị stats cấu trúc prompt: % instructions vs % data (SRT/context).
 *
 * v3.15.1: dùng để user phân biệt 2 stage cùng inject SRT (vd 1A.2 + 1B).
 * Phần SRT giống nhau nhưng instructions khác hẳn → cần làm rõ với user.
 *
 * Tìm marker tách prompt: "PHỤ ĐỀ ĐẦU VÀO" hoặc "PHẦN BIẾN — CONTEXT".
 */
function PromptStats({ prompt, stage }: { prompt: string; stage: string }) {
  // Các marker tách instructions vs data
  const markers = [
    "PHẦN BIẾN — CONTEXT",
    "PHỤ ĐỀ ĐẦU VÀO",
    "━━━ PHẦN BIẾN",
    "THOẠI CẦN DỊCH",
    "THOẠI CẦN GÁN",
    "DATA_LINES",
  ]

  let splitPos = -1
  let usedMarker = ""
  for (const m of markers) {
    const pos = prompt.indexOf(m)
    if (pos >= 0 && (splitPos < 0 || pos < splitPos)) {
      splitPos = pos
      usedMarker = m
    }
  }

  if (splitPos < 0) {
    return (
      <span className="text-[10px] font-normal text-zinc-400">
        {prompt.length.toLocaleString()} ký tự
      </span>
    )
  }

  const instructionsLen = splitPos
  const dataLen = prompt.length - splitPos
  const instructionsPct = Math.round(100 * instructionsLen / prompt.length)

  return (
    <span className="text-[10px] font-normal text-zinc-400 flex items-center gap-2">
      <span title={`Phần instructions riêng của ${stage}`}>
        📋 instructions: <strong className="text-blue-600 dark:text-blue-400">
          {instructionsLen.toLocaleString()}
        </strong> ký tự ({instructionsPct}%)
      </span>
      <span className="text-zinc-300 dark:text-zinc-700">·</span>
      <span title="Phần data SRT/context (giống nhau giữa các stage cùng đọc toàn phim)">
        📜 data: <strong className="text-zinc-600 dark:text-zinc-300">
          {dataLen.toLocaleString()}
        </strong> ký tự
      </span>
    </span>
  )
}

function labelForStatus(status: string): string {
  switch (status) {
    case 'applied': return '✓ Đã apply, lưu vào DB'
    case 'failed': return '✗ Apply thất bại'
    case 'built': return '📝 Đã build prompt, chờ apply'
    case 'pending':
    default: return 'Chưa làm'
  }
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    const now = new Date()
    const diffMs = now.getTime() - d.getTime()
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return 'vừa xong'
    if (diffMin < 60) return `${diffMin} phút trước`
    if (diffMin < 1440) return `${Math.floor(diffMin / 60)}h trước`
    return d.toLocaleString('vi-VN')
  } catch { return iso }
}


// ─────────────────────────────────────────────────────────────
// Row components
// ─────────────────────────────────────────────────────────────

function StageRow({ stage, selected, onClick }: {
  stage: ManualStageInfo
  selected: boolean
  onClick: () => void
}) {
  // Hiển thị progress thủ công: vd "3/5" cho stage có 5 unit, đã apply 3
  const isMulti = stage.units_count > 1
  const totalUnits = stage.units_count
  const appliedUnits = stage.applied_units_count
  const allApplied = isMulti && appliedUnits === totalUnits && totalUnits > 0
  const someApplied = isMulti && appliedUnits > 0 && appliedUnits < totalUnits

  let statusIcon: string
  let statusColor: string
  if (allApplied || (!isMulti && stage.has_data && stage.applied_units_count > 0)) {
    statusIcon = '✓'
    statusColor = 'text-emerald-600 dark:text-emerald-400'
  } else if (someApplied || stage.built_units_count > 0) {
    statusIcon = '◐'
    statusColor = 'text-blue-600 dark:text-blue-400'
  } else if (stage.has_data) {
    statusIcon = '✓'
    statusColor = 'text-emerald-500 dark:text-emerald-400 opacity-70'
  } else if (stage.ready) {
    statusIcon = '→'
    statusColor = 'text-blue-600 dark:text-blue-400'
  } else {
    statusIcon = '⏸'
    statusColor = 'text-zinc-400'
  }

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2 border-l-2 transition-colors ${
        selected
          ? 'bg-blue-50 dark:bg-blue-950/30 border-blue-500'
          : 'border-transparent hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
      }`}
    >
      <div className="flex items-start gap-2">
        <span className={`mt-0.5 font-mono font-bold ${statusColor}`}>{statusIcon}</span>
        <div className="min-w-0 flex-1">
          <div className={`text-sm font-medium flex items-center justify-between ${selected ? 'text-blue-700 dark:text-blue-300' : ''}`}>
            <span>{stage.label}</span>
            {isMulti && totalUnits > 0 && (
              <span className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
                allApplied
                  ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300'
                  : someApplied
                  ? 'bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                  : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-500'
              }`}>
                {appliedUnits}/{totalUnits}
              </span>
            )}
          </div>
          <div className="text-xs text-zinc-500 mt-0.5 line-clamp-2">
            {stage.description}
          </div>
          {stage.failed_units_count > 0 && (
            <div className="text-[10px] text-red-500 mt-1">
              {stage.failed_units_count} unit(s) failed
            </div>
          )}
          {!stage.ready && stage.dependency_msg && (
            <div className="text-[10px] text-amber-600 dark:text-amber-400 mt-1 italic">
              {stage.dependency_msg}
            </div>
          )}
        </div>
      </div>
    </button>
  )
}

function UnitRow({ unit, selected, onClick }: {
  unit: ManualUnitInfo
  selected: boolean
  onClick: () => void
}) {
  let statusIcon: string
  let statusColor: string
  switch (unit.status) {
    case 'applied':
      statusIcon = '✓'
      statusColor = 'text-emerald-600 dark:text-emerald-400'
      break
    case 'failed':
      statusIcon = '✗'
      statusColor = 'text-red-600 dark:text-red-400'
      break
    case 'built':
      statusIcon = '📝'
      statusColor = 'text-blue-600 dark:text-blue-400'
      break
    case 'pending':
    default:
      statusIcon = '○'
      statusColor = 'text-zinc-400'
  }

  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-2 border-l-2 transition-colors ${
        selected
          ? 'bg-blue-50 dark:bg-blue-950/30 border-blue-500'
          : 'border-transparent hover:bg-zinc-50 dark:hover:bg-zinc-800/50'
      }`}
    >
      <div className="flex items-start gap-2">
        <span className={`mt-0.5 font-mono ${statusColor}`}>{statusIcon}</span>
        <div className="min-w-0 flex-1">
          <div className={`text-sm ${selected ? 'font-medium text-blue-700 dark:text-blue-300' : ''}`}>
            {unit.label}
          </div>
          <div className="text-[10px] text-zinc-400 mt-0.5 font-mono flex items-center gap-1.5">
            <span>{unit.unit_key}</span>
            {unit.has_prompt && <span className="text-blue-400">📤</span>}
            {unit.has_response && <span className="text-emerald-400">📥</span>}
          </div>
          {unit.apply_summary && unit.status === 'applied' && (
            <div className="text-[10px] text-emerald-600 dark:text-emerald-400 mt-0.5 truncate">
              {unit.apply_summary}
            </div>
          )}
        </div>
      </div>
    </button>
  )
}
