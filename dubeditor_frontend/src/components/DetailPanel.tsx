import React, { useState, useRef, useEffect, useMemo } from 'react'
import useStore, { filterVisible } from '../store'
import useUndoStore from '../store/undo'
import api from '../api'
import ConfirmModal from './ConfirmModal'
import InfoDialog from './InfoDialog'
import { getEffectiveSpeed } from '../types'

export default function DetailPanel() {
  // PERF: selectors riêng — KHÔNG destructure
  const subtitles = useStore(s => s.subtitles)
  const characters = useStore(s => s.characters)
  const project = useStore(s => s.project)
  const activeSubId = useStore(s => s.activeSubId)
  const updateSubtitle = useStore(s => s.updateSubtitle)
  const selectedIds = useStore(s => s.selectedIds)

  // v3.4: filter state — dùng để giới hạn mọi bulk action trong đoạn đang lọc
  const filterText = useStore(s => s.filterText)
  const filterNoChar = useStore(s => s.filterNoChar)
  const filterNoTTS = useStore(s => s.filterNoTTS)
  const filterOverlap = useStore(s => s.filterOverlap)
  const filterCharIds = useStore(s => s.filterCharIds)
  const filterChapterIds = useStore(s => s.filterChapterIds)
  const overlapSubIdsFromStore = useStore(s => s.overlapSubIds)
  const chaptersFromStore = useStore(s => s.chapters)

  const hasFilter = useMemo(() => (
    !!filterText.trim() || filterNoChar || filterNoTTS || filterOverlap ||
    filterCharIds.length > 0 || filterChapterIds.length > 0
  ), [filterText, filterNoChar, filterNoTTS, filterOverlap, filterCharIds, filterChapterIds])

  // visibleSubtitles = đang hiển thị theo filter. Khi không filter → full subtitles.
  // TẤT CẢ bulk actions (TTS, trim, set speed, delete audio, done counter) đều dựa
  // trên cái này — không được đọc thẳng `subtitles` nữa.
  const visibleSubtitles = useMemo(() => filterVisible(subtitles, {
    filterText, filterNoChar, filterNoTTS, filterOverlap,
    filterCharIds, filterChapterIds,
    overlapSubIds: overlapSubIdsFromStore,
    chapters: chaptersFromStore,
  }), [subtitles, filterText, filterNoChar, filterNoTTS, filterOverlap,
       filterCharIds, filterChapterIds, overlapSubIdsFromStore, chaptersFromStore])
  const visibleIdSet = useMemo(() => new Set(visibleSubtitles.map(s => s.id)), [visibleSubtitles])

  const activeSub = subtitles.find(s => s.id === activeSubId)
  const lastSubRef = useRef<typeof activeSub | undefined>(undefined)
  if (activeSub) (lastSubRef as React.MutableRefObject<typeof activeSub>).current = activeSub
  const sub = lastSubRef.current

  const [ttsLoading, setTtsLoading] = useState(false)
  const [bulkTtsLoading, setBulkTtsLoading] = useState(false)
  const [bulkDelLoading, setBulkDelLoading] = useState(false)
  const [bulkAudioDelLoading, setBulkAudioDelLoading] = useState(false)
  const [trimLoading, setTrimLoading] = useState(false)
  const [trimDb, setTrimDb] = useState(-35)
  const [trimMsg, setTrimMsg] = useState('')
  const [exportPct, setExportPct] = useState(-1)
  const [exportMsg, setExportMsg] = useState('')

  // SRT dropdown
  const [srtMenuOpen, setSrtMenuOpen] = useState(false)
  const srtMenuRef = useRef<HTMLDivElement>(null)

  // Collapsible sections
  const [trimOpen, setTrimOpen] = useState(false)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)

  // Modal xác nhận / info
  const [confirmCfg, setConfirmCfg] = useState<{
    title: string
    message: string
    warnings?: string[]
    variant?: 'default' | 'danger' | 'warning'
    confirmText?: string
    onConfirm: () => void
  } | null>(null)
  const [info, setInfo] = useState<{ message: string; title?: string; variant: 'success' | 'error' | 'info' | 'warning' } | null>(null)

  useEffect(() => {
    const onProgress = (e: any) => { setExportPct(e.detail.pct); setExportMsg(e.detail.msg) }
    const onDone = (e: any) => { setExportPct(100); setExportMsg(`✓ Xong! ${e.detail.size_mb || ''}MB · ${e.detail.duration || ''}s`) }
    const onError = (e: any) => { setExportPct(-1); setExportMsg('❌ ' + e.detail.error) }
    window.addEventListener('export_progress', onProgress)
    window.addEventListener('export_done', onDone)
    window.addEventListener('export_error', onError)
    return () => {
      window.removeEventListener('export_progress', onProgress)
      window.removeEventListener('export_done', onDone)
      window.removeEventListener('export_error', onError)
    }
  }, [])

  // Close SRT menu khi click ngoài
  useEffect(() => {
    if (!srtMenuOpen) return
    const onClickOut = (e: MouseEvent) => {
      if (srtMenuRef.current && !srtMenuRef.current.contains(e.target as Node)) {
        setSrtMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', onClickOut)
    return () => document.removeEventListener('mousedown', onClickOut)
  }, [srtMenuOpen])

  // v3.4: done/total/noChar — khi có filter → đếm trong đoạn đang lọc; không filter → toàn phim
  const baseList = hasFilter ? visibleSubtitles : subtitles
  const done = baseList.filter(s => s.tts_done).length
  const total = baseList.length
  const noChar = baseList.filter(s => !s.character_id).length
  const pct = total ? Math.round(done / total * 100) : 0

  // ────────────────────── ACTIONS ──────────────────────

  const bulkTTS = async () => {
    if (!project) return

    // v3.4 FIX: Guard race condition — nếu user CÓ filter chapter mà chapters chưa
    // load vào store → KHÔNG cho enqueue (tránh ra danh sách sai). User có thể đợi 1s
    // rồi bấm lại — lúc đó chapters đã load.
    if (filterChapterIds.length > 0 && chaptersFromStore.length === 0) {
      setInfo({
        message: 'Đang tải danh sách đoạn, vui lòng đợi 1-2 giây rồi thử lại.',
        variant: 'warning',
      })
      return
    }
    // Nếu filterChapterIds có nhưng KHÔNG match chapter nào trong store
    // (chapter id đã bị xóa) → cảnh báo
    if (filterChapterIds.length > 0) {
      const existingIds = new Set(chaptersFromStore.map(c => c.id))
      const validFilterIds = filterChapterIds.filter(id => existingIds.has(id))
      if (validFilterIds.length === 0) {
        setInfo({
          message: 'Filter đoạn hiện tại không khớp đoạn nào (có thể đã bị xóa). Vui lòng chọn lại.',
          variant: 'warning',
        })
        return
      }
    }

    // v3.4: chỉ áp trong đoạn đang lọc (nếu có filter), không thì toàn phim như cũ
    const src = hasFilter ? visibleSubtitles : subtitles
    // v3.13 FIX: Map character_id → có voice (voxcpm_role_id) chưa
    const charHasVoice: Record<number, boolean> = {}
    for (const c of characters) {
      charHasVoice[c.id] = !!c.voxcpm_role_id
    }
    // v3.13 FIX: Detect "chưa dịch" = text rỗng hoặc còn ký tự TQ.
    // Tránh trường hợp import SRT Trung mà chưa dịch → TTS phát text Trung.
    const CHINESE_RE = /[\u4e00-\u9fff]/
    const isUntranslated = (s: any): boolean => {
      const t = (s.text || '').trim()
      if (!t) return true
      if (CHINESE_RE.test(t)) return true
      if (t.startsWith('[CHƯA DỊCH') || t.startsWith('[UNTRANSLATED')) return true
      return false
    }

    const willGenerate = src.filter(s =>
      !s.tts_done &&
      s.character_id &&
      charHasVoice[s.character_id] &&
      !isUntranslated(s)              // ← thêm: skip dòng chưa dịch
    ).map(s => s.id)
    // Count skipped: chia thành 3 loại để báo user
    const skippedNoChar = src.filter(s => !s.tts_done && !s.character_id).length
    const skippedNoVoice = src.filter(s =>
      !s.tts_done &&
      s.character_id &&
      !charHasVoice[s.character_id]
    ).length
    const skippedUntranslated = src.filter(s =>
      !s.tts_done &&
      s.character_id &&
      charHasVoice[s.character_id] &&
      isUntranslated(s)
    ).length
    const skipped = skippedNoChar + skippedNoVoice + skippedUntranslated

    if (!willGenerate.length) {
      const parts: string[] = []
      if (skippedNoChar > 0) parts.push(`${skippedNoChar} dòng chưa gán NV`)
      if (skippedNoVoice > 0) parts.push(`${skippedNoVoice} dòng có NV nhưng NV chưa có voice`)
      if (skippedUntranslated > 0) parts.push(`${skippedUntranslated} dòng chưa dịch (còn TQ/rỗng)`)
      const msg = skipped > 0
        ? `Không có dòng hợp lệ để tạo TTS. ${parts.join('. ')}.`
        : (hasFilter ? 'Tất cả phụ đề trong đoạn lọc đã có TTS rồi!' : 'Tất cả phụ đề đã có TTS rồi!')
      setInfo({ message: msg, variant: 'info' })
      return
    }

    const warnings: string[] = []
    if (skippedNoChar > 0) warnings.push(`Bỏ qua ${skippedNoChar} dòng chưa gán nhân vật`)
    if (skippedNoVoice > 0) warnings.push(`Bỏ qua ${skippedNoVoice} dòng có nhân vật nhưng chưa gán voice`)
    if (skippedUntranslated > 0) warnings.push(`Bỏ qua ${skippedUntranslated} dòng chưa dịch (còn TQ/rỗng)`)

    setConfirmCfg({
      title: hasFilter ? 'Tạo TTS (đoạn đang lọc)' : 'Tạo TTS tất cả',
      message: hasFilter
        ? `Sẽ tạo TTS cho ${willGenerate.length} dòng trong đoạn đang lọc. Quá trình này có thể mất nhiều thời gian.`
        : `Sẽ tạo TTS cho ${willGenerate.length} dòng đã gán nhân vật. Quá trình này có thể mất nhiều thời gian.`,
      warnings,
      variant: 'default',
      confirmText: 'Bắt đầu',
      onConfirm: async () => {
        setConfirmCfg(null)
        try {
          await api.post('/tts/bulk', { subtitle_ids: willGenerate })
        } catch (e: any) {
          setInfo({
            message: e?.response?.data?.detail || e?.message || 'Không thể tạo TTS',
            variant: 'error',
          })
        }
      },
    })
  }

  const bulkTTSSelected = async () => {
    const allSel = Array.from(useStore.getState().selectedIds)
    if (!allSel.length) {
      setInfo({ message: 'Hãy chọn các dòng phụ đề muốn tạo TTS trước.', variant: 'info' })
      return
    }
    const subs = useStore.getState().subtitles
    const chars = useStore.getState().characters
    // v3.13 FIX: Map character_id → có voice chưa
    const charHasVoice: Record<number, boolean> = {}
    for (const c of chars) {
      charHasVoice[c.id] = !!c.voxcpm_role_id
    }
    // v3.13 FIX: Detect "chưa dịch" = text rỗng hoặc còn ký tự TQ
    const CHINESE_RE = /[\u4e00-\u9fff]/
    const isUntranslated = (s: any): boolean => {
      const t = (s.text || '').trim()
      if (!t) return true
      if (CHINESE_RE.test(t)) return true
      if (t.startsWith('[CHƯA DỊCH') || t.startsWith('[UNTRANSLATED')) return true
      return false
    }
    const willGenerate = allSel.filter(id => {
      const s = subs.find(x => x.id === id)
      return s && s.character_id && charHasVoice[s.character_id] && !isUntranslated(s)
    })
    const noChar = allSel.filter(id => {
      const s = subs.find(x => x.id === id)
      return s && !s.character_id
    }).length
    const noVoice = allSel.filter(id => {
      const s = subs.find(x => x.id === id)
      return s && s.character_id && !charHasVoice[s.character_id]
    }).length
    const untranslated = allSel.filter(id => {
      const s = subs.find(x => x.id === id)
      return s && s.character_id && charHasVoice[s.character_id] && isUntranslated(s)
    }).length

    if (!willGenerate.length) {
      const parts: string[] = []
      if (noChar > 0) parts.push(`${noChar} dòng chưa gán NV`)
      if (noVoice > 0) parts.push(`${noVoice} dòng có NV nhưng NV chưa có voice`)
      if (untranslated > 0) parts.push(`${untranslated} dòng chưa dịch (còn TQ/rỗng)`)
      const msg = parts.length
        ? `Không có dòng hợp lệ. ${parts.join('. ')}.`
        : `Trong ${allSel.length} dòng đã chọn, không có dòng nào hợp lệ.`
      setInfo({ message: msg, variant: 'warning' })
      return
    }

    const existing = willGenerate.filter(id => {
      const s = subs.find(x => x.id === id)
      return s && s.tts_done
    }).length

    const warnings: string[] = []
    if (existing > 0) warnings.push(`${existing} dòng đã có TTS — audio cũ sẽ bị GHI ĐÈ`)
    if (noChar > 0) warnings.push(`Bỏ qua ${noChar} dòng chưa gán nhân vật`)
    if (noVoice > 0) warnings.push(`Bỏ qua ${noVoice} dòng có NV nhưng NV chưa có voice`)
    if (untranslated > 0) warnings.push(`Bỏ qua ${untranslated} dòng chưa dịch (còn TQ/rỗng)`)

    setConfirmCfg({
      title: 'Tạo TTS cho mục đã chọn',
      message: `Sẽ tạo TTS cho ${willGenerate.length} dòng.`,
      warnings,
      variant: existing > 0 ? 'warning' : 'default',
      confirmText: existing > 0 ? 'Ghi đè và tạo' : 'Bắt đầu',
      onConfirm: async () => {
        setConfirmCfg(null)
        setBulkTtsLoading(true)
        try {
          await api.post('/tts/bulk', { subtitle_ids: willGenerate })
        } catch (e: any) {
          setInfo({
            message: e?.response?.data?.detail || e?.message || 'Không thể tạo TTS',
            variant: 'error',
          })
        } finally {
          setBulkTtsLoading(false)
        }
      },
    })
  }

  const bulkDeleteAudio = async () => {
    const ids = Array.from(useStore.getState().selectedIds).filter(id => {
      const s = useStore.getState().subtitles.find(s => s.id === id)
      return s?.tts_done
    })
    if (!ids.length) {
      setInfo({ message: 'Không có audio nào để xóa trong số dòng đã chọn.', variant: 'info' })
      return
    }
    setConfirmCfg({
      title: 'Xóa audio đã chọn',
      message: `Xóa audio của ${ids.length} dòng đã chọn? Phụ đề được giữ nguyên, chỉ xóa file audio.`,
      variant: 'warning',
      confirmText: 'Xóa audio',
      onConfirm: async () => {
        setConfirmCfg(null)
        setBulkAudioDelLoading(true)
        try {
          const res = await api.post('/tts/delete-audio', { subtitle_ids: ids })
          const undoToken = res.data?.undo_token
          const backup    = res.data?.backup || []
          // Cập nhật FE: clear audio_path/tts_done của các sub đã xóa
          useStore.getState().deleteAudio(ids)

          // Push Toast Undo
          if (backup.length) {
            useUndoStore.getState().push({
              label: `Đã xóa ${backup.length} audio`,
              restore: async () => {
                await api.post('/tts/restore-audio', {
                  undo_token: undoToken,
                  backup,
                })
                // Cập nhật FE: set lại audio_path + tts_done
                const setSubs = useStore.getState()
                backup.forEach((b: any) => {
                  setSubs.updateSubtitle(b.sub_id, {
                    audio_path:   b.audio_path,
                    tts_done:     true,
                    wav_duration: b.wav_duration,
                  } as any)
                })
              },
            })
          }
        } finally { setBulkAudioDelLoading(false) }
      },
    })
  }

  const bulkDeleteSelected = async () => {
    const ids = Array.from(useStore.getState().selectedIds)
    if (!ids.length) {
      setInfo({ message: 'Chưa chọn dòng nào!', variant: 'info' })
      return
    }
    setConfirmCfg({
      title: 'Xóa phụ đề đã chọn',
      message: `Xóa ${ids.length} dòng phụ đề? Bạn có thể hoàn tác trong 8 giây.`,
      variant: 'danger',
      confirmText: 'Xóa',
      onConfirm: async () => {
        setConfirmCfg(null)
        setBulkDelLoading(true)
        try {
          const res = await api.post('/subtitles/bulk-delete', { subtitle_ids: ids })
          const backup = res.data?.backup || []
          ids.forEach(id => useStore.getState().deleteSubtitle(id))
          useStore.setState({ selectedIds: new Set(), activeSubId: null })

          if (backup.length) {
            useUndoStore.getState().push({
              label: `Đã xóa ${backup.length} phụ đề`,
              restore: async () => {
                await api.post('/subtitles/restore', { backup })
                // Re-load để có đủ thông tin character + scene relationship
                const pid = useStore.getState().project?.id
                if (pid) {
                  const subs = await api.get(`/subtitles/project/${pid}`).then(r => r.data)
                  useStore.getState().setSubtitles(subs)
                }
              },
            })
          }
        } finally { setBulkDelLoading(false) }
      },
    })
  }

  const genTTS = async () => {
    if (!sub) return
    setTtsLoading(true)
    try {
      const res = await api.post('/tts/generate', { subtitle_id: sub.id })
      updateSubtitle(sub.id, { tts_done: true, audio_path: res.data.audio_path })
    } catch (e: any) {
      setInfo({
        message: e?.response?.data?.detail || e?.message || 'Không thể tạo TTS',
        variant: 'error',
      })
    } finally { setTtsLoading(false) }
  }

  const trimOne = async () => {
    if (!sub?.audio_path) return
    setTrimLoading(true); setTrimMsg('')
    try {
      const res = await api.post('/tts/trim', { subtitle_id: sub.id, threshold_db: trimDb })
      updateSubtitle(sub.id, { audio_path: res.data.audio_path, tts_done: true })
      setTrimMsg(`✓ ${res.data.before_s.toFixed(2)}s → ${res.data.after_s.toFixed(2)}s`)
    } catch {
      setTrimMsg('Lỗi trim')
    } finally { setTrimLoading(false) }
  }

  const trimAll = async () => {
    if (!project) return
    setTrimLoading(true); setTrimMsg('')
    try {
      // v3.4: chỉ trim trong đoạn đang lọc (nếu có filter)
      const src = hasFilter ? visibleSubtitles : subtitles
      const ids = src.filter(s => s.tts_done && s.audio_path).map(s => s.id)
      if (!ids.length) {
        setTrimMsg(hasFilter ? 'Không có audio trong đoạn lọc' : 'Không có audio để trim')
        setTrimLoading(false)
        return
      }
      const res = await api.post('/tts/trim-bulk', { subtitle_ids: ids, threshold_db: trimDb })
      ids.forEach(id => updateSubtitle(id, { tts_done: true }))
      setTrimMsg(`✓ Đã trim ${res.data.trimmed}/${ids.length} file${hasFilter ? ' (đoạn lọc)' : ''}`)
    } catch {
      setTrimMsg('Lỗi trim')
    } finally { setTrimLoading(false) }
  }

  const playAudio = () => sub?.audio_path && new Audio(sub.audio_path!).play()

  const exportAudio = async () => {
    if (!project) return
    setExportPct(0); setExportMsg('Đang khởi động...')
    await api.post('/export/audio', { project_id: project.id })
  }
  const exportVideo = async () => {
    if (!project) return
    setExportPct(0); setExportMsg('Đang khởi động xuất video...')
    await api.post('/export/video', { project_id: project.id })
  }
  const exportSrt = async (onlyWithAudio: boolean) => {
    if (!project) return
    setSrtMenuOpen(false)
    setExportPct(0)
    setExportMsg(onlyWithAudio ? 'Đang xuất SRT (đồng bộ audio)...' : 'Đang xuất SRT (tất cả)...')
    await api.post('/export/srt', { project_id: project.id, only_with_audio: onlyWithAudio })
  }

  // ────────────────────── RENDER ──────────────────────

  return (
    <div className="w-52 flex-shrink-0 flex flex-col bg-white dark:bg-zinc-900 border-l border-zinc-200 dark:border-zinc-800 overflow-y-auto text-[13px]">

      {/* ━━━━ DÒNG HIỆN TẠI ━━━━ */}
      {sub && (
        <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Dòng #{sub.index}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full font-semibold"
              style={{
                background: sub.tts_done ? '#10b98120' : '#9ca3af20',
                color: sub.tts_done ? '#10b981' : '#9ca3af',
              }}>
              {sub.tts_done ? '✓ TTS' : 'Chưa TTS'}
            </span>
          </div>

          <div className="grid grid-cols-2 gap-x-2 gap-y-1 text-[12px]">
            <span className="text-zinc-500">Thời lượng</span>
            <span className="text-right font-medium tabular-nums">{(sub.end_time - sub.start_time).toFixed(1)}s</span>
            <span className="text-zinc-500">Ký tự</span>
            <span className="text-right font-medium tabular-nums">{sub.text.length}</span>
            <span className="text-zinc-500">Nhân vật</span>
            <span className="text-right font-medium truncate" style={{ color: sub.character?.color }}>
              {sub.character?.name || '—'}
            </span>
          </div>

          <div className="flex gap-1.5 pt-0.5">
            <button onClick={playAudio} disabled={!sub.audio_path}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-[11px] font-medium text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-40 transition-colors">
              ▶ Nghe
            </button>
            <button onClick={genTTS} disabled={ttsLoading}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-[11px] font-medium text-white disabled:opacity-60 transition-colors">
              {ttsLoading ? '...' : '🎙 TTS'}
            </button>
          </div>
        </section>
      )}

      {/* ━━━━ TỐC ĐỘ TTS ━━━━ */}
      {sub && <SpeedSection sub={sub} setConfirmCfg={setConfirmCfg} setInfo={setInfo} />}

      {/* ━━━━ TIẾN ĐỘ TTS ━━━━ */}
      <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-1.5">
        <div className="flex items-center justify-between">
          <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Tiến độ TTS</span>
          <span className="text-[12px] font-semibold tabular-nums">
            <span className="text-zinc-700 dark:text-zinc-300">{done}</span>
            <span className="text-zinc-400">/{total}</span>
            <span className="text-blue-600 ml-1.5">{pct}%</span>
          </span>
        </div>
        <div className="h-2 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden">
          <div className="h-full bg-gradient-to-r from-blue-500 to-blue-600 rounded-full transition-all duration-500"
            style={{ width: `${pct}%` }} />
        </div>
        {noChar > 0 && (
          <div className="text-[11px] text-amber-600 dark:text-amber-400 flex items-center gap-1">
            ⚠ <span>{noChar} dòng chưa gán NV</span>
          </div>
        )}
      </section>

      {/* ━━━━ TTS HÀNG LOẠT ━━━━ */}
      <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-2">
        <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">TTS hàng loạt</span>

        <button onClick={bulkTTS}
          className="w-full py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-[12px] font-semibold transition-colors">
          🎙 TTS tất cả
        </button>

        <div className="pt-1.5 border-t border-zinc-100 dark:border-zinc-800 space-y-1.5">
          <p className="text-[11px] text-zinc-500">
            Đã chọn: <span className="font-bold text-zinc-700 dark:text-zinc-300">{selectedIds.size}</span> dòng
          </p>
          <div className="flex gap-1.5">
            <button onClick={bulkTTSSelected} disabled={bulkTtsLoading}
              className="flex-1 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-[11px] font-medium text-white disabled:opacity-60 transition-colors">
              {bulkTtsLoading ? '...' : '🎙 TTS'}
            </button>
            <button onClick={bulkDeleteSelected} disabled={bulkDelLoading}
              className="flex-1 py-1.5 rounded-lg bg-red-50 hover:bg-red-100 dark:bg-red-950/30 border border-red-200 dark:border-red-900 text-[11px] font-medium text-red-600 dark:text-red-400 disabled:opacity-60 transition-colors">
              {bulkDelLoading ? '...' : '🗑 Xóa'}
            </button>
          </div>
          <button onClick={bulkDeleteAudio} disabled={bulkAudioDelLoading}
            className="w-full py-1.5 rounded-lg bg-orange-50 hover:bg-orange-100 dark:bg-orange-950/30 border border-orange-200 dark:border-orange-900 text-[11px] font-medium text-orange-600 dark:text-orange-400 disabled:opacity-60 transition-colors">
            {bulkAudioDelLoading ? '...' : '🔇 Xóa audio đã chọn'}
          </button>
        </div>
      </section>

      {/* ━━━━ XUẤT ━━━━ */}
      <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-1.5">
        <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">Xuất file</span>

        {/* SRT dropdown */}
        <div className="relative" ref={srtMenuRef}>
          <button onClick={() => setSrtMenuOpen(o => !o)}
            disabled={exportPct >= 0 && exportPct < 100}
            className="w-full py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-[12px] font-medium flex items-center justify-between px-2.5 disabled:opacity-60">
            <span>📄 Xuất SRT</span>
            <span className="text-[10px]">▼</span>
          </button>
          {srtMenuOpen && (
            <div className="absolute top-full left-0 right-0 mt-1 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-900 shadow-lg z-40 overflow-hidden">
              <button onClick={() => exportSrt(true)}
                className="w-full px-3 py-2 text-left text-[12px] hover:bg-zinc-50 dark:hover:bg-zinc-800 border-b border-zinc-100 dark:border-zinc-800">
                <div className="font-medium">Đồng bộ audio</div>
                <div className="text-[10px] text-zinc-500">Theo end_time đã chỉnh, chỉ sub có TTS</div>
              </button>
              <button onClick={() => exportSrt(false)}
                className="w-full px-3 py-2 text-left text-[12px] hover:bg-zinc-50 dark:hover:bg-zinc-800">
                <div className="font-medium">Tất cả phụ đề</div>
                <div className="text-[10px] text-zinc-500">Theo end_time gốc, đầy đủ</div>
              </button>
            </div>
          )}
        </div>

        <button onClick={exportAudio} disabled={exportPct >= 0 && exportPct < 100}
          className="w-full py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-[12px] font-medium disabled:opacity-60">
          🔊 Xuất audio
        </button>
        <button onClick={exportVideo} disabled={exportPct >= 0 && exportPct < 100}
          className="w-full py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-[12px] font-medium disabled:opacity-60">
          🎬 Xuất video
        </button>

        {exportPct >= 0 && (
          <div className="space-y-1 pt-1">
            <div className="h-1.5 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden">
              <div className="h-full bg-emerald-500 rounded-full transition-all duration-300"
                style={{ width: `${exportPct}%` }} />
            </div>
            {exportMsg && (
              <p className="text-[10px] text-zinc-500 truncate">{exportMsg}</p>
            )}
          </div>
        )}
      </section>

      {/* ━━━━ TRIM SILENCE (collapsible) ━━━━ */}
      <section className="border-b border-zinc-100 dark:border-zinc-800">
        <button onClick={() => setTrimOpen(o => !o)}
          className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors">
          <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">✂ Trim silence</span>
          <span className="text-[10px] text-zinc-400">{trimOpen ? '▲' : '▼'}</span>
        </button>
        {trimOpen && (
          <div className="px-3 pb-3 space-y-2">
            <div className="space-y-1">
              <div className="flex justify-between text-[11px] text-zinc-500">
                <span>Ngưỡng cắt</span>
                <span className="font-mono font-semibold text-zinc-700 dark:text-zinc-300">{trimDb} dB</span>
              </div>
              <input type="range" min={-60} max={-10} step={1} value={trimDb}
                onChange={e => setTrimDb(parseInt(e.target.value))}
                className="w-full accent-violet-500 cursor-pointer" style={{ height: 4 }} />
              <div className="flex justify-between text-[9px] text-zinc-400">
                <span>-60 (ít)</span>
                <span>-10 (mạnh)</span>
              </div>
              <div className="flex gap-1 flex-wrap">
                {[[-50, 'Nhẹ'], [-35, 'Tối ưu'], [-20, 'Mạnh']].map(([v, label]) => (
                  <button key={v} onClick={() => setTrimDb(v as number)}
                    className={`px-1.5 py-0.5 rounded text-[9px] font-medium transition-colors ${trimDb === v ? 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300' : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 hover:bg-zinc-200'}`}>
                    {label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex gap-1.5">
              <button onClick={trimOne} disabled={trimLoading || !sub?.audio_path}
                className="flex-1 py-1.5 rounded-lg border border-violet-300 dark:border-violet-800 text-[11px] font-medium text-violet-600 dark:text-violet-400 hover:bg-violet-50 dark:hover:bg-violet-950 disabled:opacity-40 transition-colors">
                {trimLoading ? '...' : 'Dòng này'}
              </button>
              <button onClick={trimAll} disabled={trimLoading || done === 0}
                className="flex-1 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-[11px] font-medium text-white disabled:opacity-40 transition-colors">
                {trimLoading ? '...' : 'Tất cả'}
              </button>
            </div>

            {trimMsg && (
              <p className="text-[10px] text-center font-medium"
                style={{ color: trimMsg.startsWith('✓') ? '#10B981' : '#EF4444' }}>
                {trimMsg}
              </p>
            )}
          </div>
        )}
      </section>

      {/* ━━━━ PHÍM TẮT (collapsible) ━━━━ */}
      <section>
        <button onClick={() => setShortcutsOpen(o => !o)}
          className="w-full flex items-center justify-between px-3 py-2.5 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors">
          <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">⌨ Phím tắt</span>
          <span className="text-[10px] text-zinc-400">{shortcutsOpen ? '▲' : '▼'}</span>
        </button>
        {shortcutsOpen && (
          <div className="px-3 pb-3 space-y-1.5">
            {[
              ['Space', 'Play/Pause'],
              ['↑↓', 'Di chuyển'],
              ['1–9', 'Gán nhân vật'],
              ['Ctrl+T', 'TTS dòng'],
              ['[ ]', '±100ms'],
              ['Del', 'Xóa dòng'],
              ['N', 'Tạo sub'],
            ].map(([k, v]) => (
              <div key={k} className="flex items-center justify-between gap-2">
                <span className="kbd">{k}</span>
                <span className="text-[11px] text-zinc-500 text-right">{v}</span>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Modals */}
      <ConfirmModal
        open={confirmCfg !== null}
        title={confirmCfg?.title || ''}
        message={confirmCfg?.message || ''}
        warnings={confirmCfg?.warnings}
        variant={confirmCfg?.variant}
        confirmText={confirmCfg?.confirmText}
        onConfirm={() => confirmCfg?.onConfirm()}
        onCancel={() => setConfirmCfg(null)}
      />

      <InfoDialog
        open={!!info}
        title={info?.title}
        message={info?.message || ''}
        variant={info?.variant || 'info'}
        onClose={() => setInfo(null)}
      />
    </div>
  )
}


// ─────────────────────────────────────────────────────────────
// SpeedSection — chỉnh tốc độ TTS (gọn lại: chip ngang, dùng dialog)
// ─────────────────────────────────────────────────────────────
interface SpeedSectionProps {
  sub: any
  setConfirmCfg: (cfg: any) => void
  setInfo: (info: any) => void
}

function SpeedSection({ sub, setConfirmCfg, setInfo }: SpeedSectionProps) {
  const characters = useStore(s => s.characters)
  const subtitles = useStore(s => s.subtitles)
  const updateSubtitle = useStore(s => s.updateSubtitle)
  const setCharacters = useStore(s => s.setCharacters)
  const selectedIds = useStore(s => s.selectedIds)

  // v3.4: filter state — áp speed character chỉ trong đoạn lọc nếu có filter
  const filterText = useStore(s => s.filterText)
  const filterNoChar = useStore(s => s.filterNoChar)
  const filterNoTTS = useStore(s => s.filterNoTTS)
  const filterOverlap = useStore(s => s.filterOverlap)
  const filterCharIds = useStore(s => s.filterCharIds)
  const filterChapterIds = useStore(s => s.filterChapterIds)
  const overlapSubIdsFromStore = useStore(s => s.overlapSubIds)
  const chaptersFromStore = useStore(s => s.chapters)
  const hasFilter = (
    !!filterText.trim() || filterNoChar || filterNoTTS || filterOverlap ||
    filterCharIds.length > 0 || filterChapterIds.length > 0
  )
  const visibleSubtitles = React.useMemo(() => filterVisible(subtitles, {
    filterText, filterNoChar, filterNoTTS, filterOverlap,
    filterCharIds, filterChapterIds,
    overlapSubIds: overlapSubIdsFromStore,
    chapters: chaptersFromStore,
  }), [subtitles, filterText, filterNoChar, filterNoTTS, filterOverlap,
       filterCharIds, filterChapterIds, overlapSubIdsFromStore, chaptersFromStore])

  const char = sub.character || characters.find((c: any) => c.id === sub.character_id)
  const effective = getEffectiveSpeed(sub, char)
  const isInherited = sub.tts_speed == null

  const [val, setVal] = React.useState(effective)
  const [mode, setMode] = React.useState<'this' | 'selection' | 'character'>('this')

  React.useEffect(() => { setVal(effective) }, [sub.id, effective])

  const apply = async () => {
    const speed = Math.max(0.5, Math.min(2.0, val))
    if (mode === 'this') {
      try {
        await api.post('/tts/bulk-set-speed', { subtitle_ids: [sub.id], tts_speed: speed })
        updateSubtitle(sub.id, { tts_speed: speed })
      } catch (e) {
        setInfo({ message: 'Lỗi: ' + (e as any)?.message, variant: 'error' })
      }
    } else if (mode === 'selection') {
      const ids = Array.from(selectedIds)
      if (!ids.length) {
        setInfo({ message: 'Chưa chọn dòng nào', variant: 'info' })
        return
      }
      try {
        await api.post('/tts/bulk-set-speed', { subtitle_ids: ids, tts_speed: speed })
        ids.forEach(id => updateSubtitle(id, { tts_speed: speed }))
      } catch (e) {
        setInfo({ message: 'Lỗi: ' + (e as any)?.message, variant: 'error' })
      }
    } else if (mode === 'character') {
      if (!char) {
        setInfo({ message: 'Sub chưa gán nhân vật', variant: 'info' })
        return
      }
      // v3.4: nếu có filter → chỉ áp cho subs của NV này NẰM TRONG đoạn lọc
      const baseList = hasFilter ? visibleSubtitles : subtitles
      const charSubs = baseList.filter(s => s.character_id === char.id)
      const overrideCount = charSubs.filter(s => s.tts_speed != null).length

      if (!charSubs.length) {
        setInfo({
          message: hasFilter
            ? `Không có dòng nào của "${char.name}" trong đoạn đang lọc.`
            : `Không có dòng nào của "${char.name}".`,
          variant: 'info',
        })
        return
      }

      const doApply = async () => {
        try {
          // Khi có filter → gửi kèm subtitle_ids để backend chỉ reset override
          // trong scope visible (không động tới subs ngoài đoạn lọc).
          // Khi không filter → giữ behavior cũ (apply_to_subs cho toàn NV).
          const charSubIds = charSubs.map(s => s.id)
          if (hasFilter) {
            await api.post(`/tts/character/${char.id}/set-speed`, {
              tts_speed: speed,
              apply_to_subs: true,
              subtitle_ids: charSubIds,
            })
          } else {
            await api.post(`/tts/character/${char.id}/set-speed`, {
              tts_speed: speed,
              apply_to_subs: true,
            })
            setCharacters(characters.map((c: any) => c.id === char.id ? { ...c, tts_speed: speed } : c))
          }
          charSubs.forEach(s => {
            if (s.tts_speed != null) updateSubtitle(s.id, { tts_speed: null })
          })
        } catch (e) {
          setInfo({ message: 'Lỗi: ' + (e as any)?.message, variant: 'error' })
        }
      }

      setConfirmCfg({
        title: hasFilter
          ? `Đặt tốc độ ${speed.toFixed(2)}x cho "${char.name}" (đoạn đang lọc)`
          : `Đặt tốc độ ${speed.toFixed(2)}x cho "${char.name}"`,
        message: hasFilter
          ? `Sẽ áp dụng cho ${charSubs.length} dòng của nhân vật này TRONG ĐOẠN ĐANG LỌC.`
          : `Sẽ áp dụng cho ${charSubs.length} dòng của nhân vật này.`,
        warnings: overrideCount > 0
          ? [`${overrideCount} dòng đã có tốc độ riêng — sẽ bị reset về tốc độ chung`]
          : [],
        variant: 'warning',
        confirmText: 'Áp dụng',
        onConfirm: async () => {
          setConfirmCfg(null)
          await doApply()
        },
      })
    }
  }

  const reset = async () => {
    try {
      await api.post('/tts/bulk-set-speed', { subtitle_ids: [sub.id], tts_speed: null })
      updateSubtitle(sub.id, { tts_speed: null })
    } catch (e) {
      setInfo({ message: 'Lỗi: ' + (e as any)?.message, variant: 'error' })
    }
  }

  return (
    <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-500">⚡ Tốc độ TTS</span>
        <span className="text-[12px] tabular-nums font-bold text-blue-600">{val.toFixed(2)}x</span>
      </div>

      <input
        type="range" min="0.5" max="2.0" step="0.05"
        value={val}
        onChange={e => setVal(parseFloat(e.target.value))}
        className="w-full accent-blue-600"
      />
      <div className="flex justify-between text-[10px] text-zinc-400 -mt-1">
        <span>0.5x</span><span>1.0x</span><span>2.0x</span>
      </div>

      {isInherited && char && (
        <div className="text-[10px] text-zinc-500 italic">
          Đang kế thừa từ "{char.name}" ({(char.tts_speed || 1.0).toFixed(2)}x)
        </div>
      )}

      {/* Mode chips — 3 chip ngang thay vì radio dọc */}
      <div className="flex gap-1">
        <button onClick={() => setMode('this')}
          className={`flex-1 py-1 rounded text-[10px] font-medium border transition-colors
            ${mode === 'this'
              ? 'bg-blue-600 text-white border-blue-600'
              : 'border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800'
            }`}>
          Sub này
        </button>
        <button onClick={() => setMode('selection')}
          className={`flex-1 py-1 rounded text-[10px] font-medium border transition-colors
            ${mode === 'selection'
              ? 'bg-blue-600 text-white border-blue-600'
              : 'border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800'
            }`}>
          Đã chọn ({selectedIds.size})
        </button>
        {char && (
          <button onClick={() => setMode('character')}
            title={`NV "${char.name}"`}
            className={`flex-1 py-1 rounded text-[10px] font-medium border transition-colors truncate
              ${mode === 'character'
                ? 'bg-blue-600 text-white border-blue-600'
                : 'border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800'
              }`}>
            NV
          </button>
        )}
      </div>

      <div className="flex gap-1.5">
        {!isInherited && (
          <button onClick={reset}
            className="flex-1 py-1.5 text-[11px] rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-zinc-500 font-medium">
            ↺ Reset
          </button>
        )}
        <button onClick={apply}
          className="flex-1 py-1.5 text-[11px] rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold">
          Áp dụng
        </button>
      </div>
    </section>
  )
}