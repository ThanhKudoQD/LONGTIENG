/**
 * ManualTranslatePanelMega — Chế độ Dịch Thủ công v4.2 Mega-Chunk
 *
 * Workflow (v4.2 — đã bỏ stage Chunks):
 *   1. bible_unified    (1 paste)  — Cast + World + Glossary + Arcs (cover toàn phim)
 *   2. translate_mega   (N paste)  — Mega chia theo Arc, ~500 dòng/paste (configurable)
 *   3. review_pass1     (1 paste)  — consistency scan + AI FIX/KEEP
 *   4. review_pass2     (N paste)  — per-arc polish
 *
 * Nét mới v4.2:
 *   - Bỏ stage Chunks + Scenes (dùng Arc làm xương sống duy nhất)
 *   - Nút "Reset Bible" để rebuild khi Bible cũ sai
 *   - Cấu hình số sub tối đa / mega (default 500, range 200-2000)
 *   - v1 + v2 đều bắt buộc cho mỗi dòng (lồng tiếng)
 *
 * UI identical với ManualTranslatePanel v3, chỉ gọi API endpoint khác
 * (/manual-translate-mega/* thay vì /manual-translate/*).
 */
import React, { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import {
  manualTranslateMegaApi,
  type ManualMegaStageInfo,
  type ManualUnitInfo,
  type ManualBuiltPrompt,
  type ManualApplyResult,
} from '../../api'

interface Props {
  projectId: number
  onDataChanged?: () => void
}

// Debounce helper — gắn save với unit cụ thể.
// v4.4: KHI ĐỔI UNIT, save NGAY (force flush) thay vì hủy timer.
//        → tránh mất draft khi user đổi unit nhanh.
function useUnitScopedSave() {
  // Map: unit_id → { timer, fn } để có thể flush
  const timersRef = useRef<Map<string, { timer: ReturnType<typeof setTimeout>; fn: () => Promise<void> }>>(new Map())
  const currentUnitRef = useRef<string | null>(null)

  useEffect(() => () => {
    // Cleanup khi unmount: hủy tất cả timer (KHÔNG save vì component đã unmount)
    timersRef.current.forEach(({ timer }) => clearTimeout(timer))
    timersRef.current.clear()
  }, [])

  /** Đổi sang unit mới — FLUSH (chạy save ngay) các timer pending của unit cũ.
   *  Gọi NGAY khi user click unit mới. */
  const setCurrentUnit = useCallback((unitId: string | null) => {
    // v4.4: flush các timer của unit khác unit mới — KHÔNG hủy
    const toFlush: Array<() => Promise<void>> = []
    timersRef.current.forEach(({ timer, fn }, id) => {
      if (id !== unitId) {
        clearTimeout(timer)
        toFlush.push(fn)
        timersRef.current.delete(id)
      }
    })
    currentUnitRef.current = unitId
    // Chạy save ngay (fire-and-forget, không await)
    toFlush.forEach(fn => {
      fn().catch(e => console.warn('flush save on unit switch failed', e))
    })
  }, [])

  /** Schedule save cho 1 unit cụ thể. */
  const scheduleSave = useCallback((
    unitId: string,
    fn: () => Promise<void>,
    delayMs = 1500,
  ) => {
    // Hủy timer cũ của CÙNG unit nếu có (replace)
    const existing = timersRef.current.get(unitId)
    if (existing) clearTimeout(existing.timer)

    const timer = setTimeout(async () => {
      timersRef.current.delete(unitId)
      // v4.4: chạy save BẤT KỂ user đã đổi unit hay chưa — đảm bảo không mất draft
      try { await fn() } catch (e) { console.warn('scheduled save failed', e) }
    }, delayMs)

    timersRef.current.set(unitId, { timer, fn })
  }, [])

  /** Force-flush: chạy ngay tất cả timer pending (await all). */
  const flushAll = useCallback(async () => {
    const pending = Array.from(timersRef.current.entries())
    timersRef.current.clear()
    pending.forEach(([, { timer }]) => clearTimeout(timer))
    await Promise.allSettled(pending.map(([, { fn }]) => fn()))
  }, [])

  /** Flush ngay 1 unit cụ thể (vd khi user blur khỏi textarea). */
  const flushUnit = useCallback(async (unitId: string) => {
    const entry = timersRef.current.get(unitId)
    if (!entry) return
    clearTimeout(entry.timer)
    timersRef.current.delete(unitId)
    try { await entry.fn() } catch (e) { console.warn('flush unit failed', e) }
  }, [])

  return useMemo(() => ({ setCurrentUnit, scheduleSave, flushAll, flushUnit }),
                  [setCurrentUnit, scheduleSave, flushAll, flushUnit])
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


export default function ManualTranslatePanelMega({ projectId, onDataChanged }: Props) {
  const [stages, setStages] = useState<ManualMegaStageInfo[]>([])
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
  // v4.4: Track thời gian apply để hiện cảnh báo nếu apply lâu
  const [applyStartTime, setApplyStartTime] = useState<number | null>(null)
  const [applyElapsed, setApplyElapsed] = useState<number>(0)

  // v4.1: Stage options (preset + advanced flags)
  // v4.3: thêm preset_field — translate_mega dùng để map preset → speaker_mode
  const [stageOptions, setStageOptions] = useState<{
    presets: Array<{ key: string; label: string; description: string }>
    default_preset?: string
    preset_field?: string   // v4.3: nếu có, value của preset sẽ được gửi với key này
    advanced: Array<{ key: string; label: string; type: string; default: any }>
  } | null>(null)
  const [selectedPreset, setSelectedPreset] = useState<string>('balanced')
  const [advancedFlags, setAdvancedFlags] = useState<Record<string, any>>({})
  const [showAdvanced, setShowAdvanced] = useState(false)

  // v4.2: Mega target config (số sub/mega) + Reset Bible
  const [megaTarget, setMegaTarget] = useState<number>(500)
  const [megaTargetInfo, setMegaTargetInfo] = useState<{
    default: number; min: number; max: number
  }>({ default: 500, min: 200, max: 2000 })
  const [targetEditing, setTargetEditing] = useState<number | null>(null)
  const [savingTarget, setSavingTarget] = useState(false)
  const [showTargetModal, setShowTargetModal] = useState(false)
  const [resettingBible, setResettingBible] = useState(false)

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
      const s = await manualTranslateMegaApi.listStages(projectId)
      setStages(s)
    } catch (e: any) {
      setError(`Không load được stages: ${e?.message || e}`)
    }
  }, [projectId])

  useEffect(() => { refreshStages() }, [refreshStages])

  // v4.2: Load mega target config on mount
  useEffect(() => {
    let cancelled = false
    manualTranslateMegaApi.getMegaTarget(projectId)
      .then(info => {
        if (cancelled) return
        setMegaTarget(info.target)
        setMegaTargetInfo({
          default: info.default,
          min: info.min,
          max: info.max,
        })
      })
      .catch(e => console.warn('Load mega target failed:', e))
    return () => { cancelled = true }
  }, [projectId])

  // v4.4: Tick elapsed mỗi giây khi apply đang chạy
  useEffect(() => {
    if (applyStartTime === null) {
      setApplyElapsed(0)
      return
    }
    const tick = () => {
      setApplyElapsed(Math.floor((Date.now() - applyStartTime) / 1000))
    }
    tick()
    const id = setInterval(tick, 1000)
    return () => clearInterval(id)
  }, [applyStartTime])

  // ─── Load units khi chọn stage ────────────────────────────────
  const refreshUnits = useCallback(async (stage: string) => {
    setLoadingUnits(true)
    try {
      const u = await manualTranslateMegaApi.listUnits(projectId, stage)
      setUnits(u)
      return u
    } catch (e: any) {
      setError(`Không load được units: ${e?.message || e}`)
      return []
    } finally {
      setLoadingUnits(false)
    }
  }, [projectId])

  // v4.2: Save mega target (đặt SAU refreshUnits vì có dùng nó)
  const handleSaveMegaTarget = useCallback(async () => {
    if (targetEditing === null) return
    const v = Math.max(megaTargetInfo.min,
                         Math.min(megaTargetInfo.max, targetEditing))
    setSavingTarget(true)
    try {
      const r = await manualTranslateMegaApi.setMegaTarget(projectId, v)
      setMegaTarget(r.target)
      setTargetEditing(null)
      setShowTargetModal(false)
      // Refresh units để rebuild theo target mới
      if (selectedStage === 'translate_mega') {
        await refreshUnits('translate_mega')
      }
      await refreshStages()
    } catch (e: any) {
      setError(`Lưu mega target lỗi: ${e?.response?.data?.detail || e?.message || e}`)
    } finally {
      setSavingTarget(false)
    }
  }, [projectId, targetEditing, megaTargetInfo, selectedStage,
      refreshUnits, refreshStages])

  // v4.2: Reset Bible
  const handleResetBible = useCallback(async () => {
    if (!confirm(
      "Reset Bible sẽ xóa:\n" +
      "  - Bible (cast + world + glossary + arcs)\n" +
      "  - Toàn bộ Nhân vật (Character)\n" +
      "  - Toàn bộ Story Arcs\n" +
      "  - Toàn bộ Glossary Terms\n" +
      "  - Liên kết character_id của các Subtitle (về null)\n\n" +
      "KHÔNG xóa text đã dịch (v1, v2) hay speaker_zh.\n\n" +
      "Bạn chắc chắn muốn reset?"
    )) return

    setResettingBible(true)
    try {
      const r = await manualTranslateMegaApi.resetBible(projectId)
      if (r.ok) {
        alert("✓ " + r.summary)
        await refreshStages()
        if (selectedStage) await refreshUnits(selectedStage)
        onDataChanged?.()
      }
    } catch (e: any) {
      setError(`Reset Bible lỗi: ${e?.response?.data?.detail || e?.message || e}`)
    } finally {
      setResettingBible(false)
    }
  }, [projectId, selectedStage, refreshStages, refreshUnits, onDataChanged])

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

    // v4.1: Load stage-options nếu stage có options (vd bible_unified)
    manualTranslateMegaApi.getStageOptions(projectId, selectedStage)
      .then(opts => {
        if (opts && opts.presets && opts.presets.length > 0) {
          setStageOptions(opts)
          setSelectedPreset(opts.default_preset || opts.presets[0].key)
          // Khởi tạo advanced flags từ default
          const defaults: Record<string, any> = {}
          for (const a of opts.advanced || []) {
            defaults[a.key] = a.default
          }
          setAdvancedFlags(defaults)
          setShowAdvanced(false)
        } else {
          setStageOptions(null)
        }
      })
      .catch(() => setStageOptions(null))
  }, [selectedStage, stages, refreshUnits, projectId])

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

    manualTranslateMegaApi.getUnitState(projectId, selectedStage, selectedUnit)
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
        await manualTranslateMegaApi.savePromptEdit(projectId, stage, unitKey, value)
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
        await manualTranslateMegaApi.saveResponseDraft(projectId, stage, unitKey, value)
        setAutoSaveStatus('saved')
        setTimeout(() => setAutoSaveStatus(prev => prev === 'saved' ? 'idle' : prev), 1500)
      } catch (e) {
        console.warn('save response draft failed', e)
        setAutoSaveStatus('idle')
      }
    }, 700)   // v4.4: 700ms (giảm từ 1500ms cho phản hồi nhanh hơn)
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
      // v4.1: Truyền options (preset + advanced) nếu stage có
      // v4.3: cho translate_mega, key gửi backend là `speaker_mode`
      let buildOptions: any = undefined
      if (stageOptions) {
        buildOptions = {
          preset: selectedPreset,
          advanced: advancedFlags,
        }
        // v4.3: map preset → speaker_mode cho stage translate_mega
        const presetField = (stageOptions as any).preset_field
        if (presetField) {
          buildOptions[presetField] = selectedPreset
        }
      }
      const bp = await manualTranslateMegaApi.buildPrompt(
        projectId, stage, unitKey, forceRebuild, buildOptions
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
    setApplyStartTime(Date.now())
    setError(null)
    try {
      const result = await manualTranslateMegaApi.applyResponse(
        projectId, stage, unitKey, meta, response,
      )
      // Verify user vẫn ở unit này — chỉ apply kết quả lên state nếu còn ở đúng unit
      if (currentUnitRef.current === unitId) {
        setLastApplyResult(result)
        if (result.ok) {
          await refreshStages()
          await refreshUnits(stage)
          onDataChanged?.()
        }
      }
    } catch (e: any) {
      // Chỉ hiển thị error nếu còn ở đúng unit
      if (currentUnitRef.current === unitId) {
        setError(`Apply lỗi: ${e?.response?.data?.detail || e?.message || e}`)
      }
    } finally {
      // v4.4 fix: LUÔN setApplying(false) bất kể user ở unit nào
      //          — tránh nút Apply kẹt ở "Đang apply..." mãi mãi
      setApplying(false)
      setApplyStartTime(null)
    }
  }

  // ─── Reset unit ──────────────────────────────────────────────
  const handleResetUnit = async () => {
    if (!selectedStage || !selectedUnit) return
    if (!confirm(`Reset unit "${selectedUnit}"? Sẽ xóa prompt + response đã lưu.`))
      return
    try {
      await manualTranslateMegaApi.resetUnit(projectId, selectedStage, selectedUnit)
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
    (selectedStage && ['translate_mega', 'review_pass2'].includes(selectedStage))

  return (
    <div className="flex flex-col h-full bg-zinc-50 dark:bg-zinc-900">
      {/* Header */}
      <div className="px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold flex items-center gap-2">
              🚀 Dịch Thủ công — Mega-Chunk
              <span className="text-xs font-normal text-white bg-gradient-to-r from-purple-500 to-pink-500 px-2 py-0.5 rounded">
                v4.2
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
              Workflow tối ưu: 4 stage. Bible với Arcs cover toàn phim,
              mega-chunk chia theo Arc (~{megaTarget} dòng/paste), 2-pass review.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={() => {
                setTargetEditing(megaTarget)
                setShowTargetModal(true)
              }}
              className="text-xs px-2 py-1 rounded border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              title={`Số sub/mega hiện tại: ${megaTarget}. Click để đổi.`}
            >
              ⚙ {megaTarget} sub/mega
            </button>
            <button
              onClick={handleResetBible}
              disabled={resettingBible}
              className="text-xs px-2 py-1 rounded border border-red-300 dark:border-red-700 text-red-700 dark:text-red-300 hover:bg-red-50 dark:hover:bg-red-950/30 disabled:opacity-50"
              title="Xóa Bible + Arcs + Characters để rebuild từ đầu"
            >
              {resettingBible ? '⏳ Đang reset...' : '🗑 Reset Bible'}
            </button>
            <button
              onClick={refreshStages}
              className="text-xs px-2 py-1 rounded border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              title="Reload trạng thái"
            >
              🔄 Reload
            </button>
          </div>
        </div>
      </div>

      {/* v4.2: Modal config mega target */}
      {showTargetModal && (
        <div
          className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center"
          onClick={() => { setShowTargetModal(false); setTargetEditing(null) }}
        >
          <div
            className="bg-white dark:bg-zinc-900 rounded-lg p-6 shadow-xl max-w-md w-full mx-4"
            onClick={e => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold mb-2">
              ⚙ Cấu hình số sub / mega-chunk
            </h3>
            <p className="text-sm text-zinc-500 mb-4">
              Số dòng tối đa cho mỗi đơn vị paste khi dịch.
              Arc dài hơn sẽ tự động chia step.
            </p>
            <div className="flex items-center gap-2 mb-4">
              <input
                type="number"
                min={megaTargetInfo.min}
                max={megaTargetInfo.max}
                step={50}
                value={targetEditing ?? megaTarget}
                onChange={e => setTargetEditing(parseInt(e.target.value) || megaTarget)}
                className="w-32 px-3 py-1.5 border rounded bg-white dark:bg-zinc-800
                           border-zinc-300 dark:border-zinc-700"
                autoFocus
              />
              <span className="text-sm text-zinc-500">
                (min {megaTargetInfo.min}, max {megaTargetInfo.max}, default {megaTargetInfo.default})
              </span>
            </div>
            <div className="text-xs text-amber-700 dark:text-amber-400 mb-4 p-2 bg-amber-50 dark:bg-amber-950/30 rounded">
              ⚠ Đổi target sẽ rebuild danh sách mega. Các mega đã apply vẫn giữ.
            </div>
            <div className="flex justify-end gap-2">
              <button
                onClick={() => { setShowTargetModal(false); setTargetEditing(null) }}
                className="px-3 py-1.5 text-sm rounded border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800"
              >
                Hủy
              </button>
              <button
                onClick={handleSaveMegaTarget}
                disabled={savingTarget || targetEditing === null}
                className="px-3 py-1.5 text-sm rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
              >
                {savingTarget ? 'Đang lưu...' : 'Lưu'}
              </button>
            </div>
          </div>
        </div>
      )}

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

              {/* v4.1: Stage options (preset + advanced) — chỉ hiện khi stage có options và CHƯA build prompt */}
              {stageOptions && !builtPrompt && (
                <div className="px-4 py-3 bg-gradient-to-r from-purple-50 to-pink-50 dark:from-purple-950/20 dark:to-pink-950/20 border-b border-zinc-200 dark:border-zinc-800">
                  <div className="text-xs font-semibold mb-2 text-zinc-700 dark:text-zinc-300">
                    ⚙️ Tùy chọn build prompt
                  </div>

                  {/* Preset selection */}
                  <div className="space-y-1.5 mb-2">
                    {stageOptions.presets.map(preset => (
                      <label
                        key={preset.key}
                        className={`flex items-start gap-2 px-2 py-1.5 rounded cursor-pointer border ${
                          selectedPreset === preset.key
                            ? 'bg-white dark:bg-zinc-900 border-purple-400 dark:border-purple-600'
                            : 'border-transparent hover:bg-white/50 dark:hover:bg-zinc-900/50'
                        }`}
                      >
                        <input
                          type="radio"
                          name="bible_preset"
                          value={preset.key}
                          checked={selectedPreset === preset.key}
                          onChange={() => setSelectedPreset(preset.key)}
                          className="mt-0.5"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="text-sm font-medium text-zinc-800 dark:text-zinc-200">
                            {preset.label}
                          </div>
                          <div className="text-[11px] text-zinc-600 dark:text-zinc-400 whitespace-pre-line leading-relaxed">
                            {preset.description}
                          </div>
                        </div>
                      </label>
                    ))}
                  </div>

                  {/* Advanced toggle */}
                  <button
                    onClick={() => setShowAdvanced(!showAdvanced)}
                    className="text-xs text-purple-700 dark:text-purple-400 hover:underline flex items-center gap-1"
                  >
                    <span>{showAdvanced ? '▼' : '▶'}</span>
                    Tùy chỉnh nâng cao
                    {showAdvanced && (
                      <span className="ml-2 text-[10px] text-zinc-500">
                        (override preset)
                      </span>
                    )}
                  </button>

                  {/* Advanced flags */}
                  {showAdvanced && (
                    <div className="mt-2 pl-3 border-l-2 border-purple-300 dark:border-purple-700 space-y-1">
                      {stageOptions.advanced.map(adv => (
                        adv.type === 'bool' && (
                          <label key={adv.key} className="flex items-center gap-2 text-xs cursor-pointer">
                            <input
                              type="checkbox"
                              checked={!!advancedFlags[adv.key]}
                              onChange={e => setAdvancedFlags(f => ({
                                ...f, [adv.key]: e.target.checked
                              }))}
                            />
                            <span className="text-zinc-700 dark:text-zinc-300">{adv.label}</span>
                          </label>
                        )
                      ))}
                      <button
                        onClick={() => {
                          const defaults: Record<string, any> = {}
                          for (const a of stageOptions.advanced) defaults[a.key] = a.default
                          setAdvancedFlags(defaults)
                        }}
                        className="text-[10px] text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 underline mt-1"
                      >
                        Reset về default
                      </button>
                    </div>
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
                      onBlur={() => {
                        // v4.4: flush ngay khi user blur khỏi textarea
                        // Tránh trường hợp paste rồi click sang chỗ khác mà save chưa kịp chạy
                        if (selectedStage && selectedUnit) {
                          const unitId = `${selectedStage}::${selectedUnit}`
                          scopedSave.flushUnit(unitId).catch(() => {})
                        }
                      }}
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
                        {applying ? (
                          applyElapsed > 30
                            ? `⚠ Đang apply... ${applyElapsed}s (lâu bất thường — check log backend)`
                            : `⏳ Đang apply... ${applyElapsed > 0 ? `${applyElapsed}s` : ''}`
                        ) : (lastApplyResult?.ok ? '🔁 Apply lại' : '✓ Apply response')}
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
  stage: ManualMegaStageInfo
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
