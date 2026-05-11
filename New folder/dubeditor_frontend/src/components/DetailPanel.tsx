import React, { useState } from 'react'
import useStore from '../store'
import api from '../api'
import ConfirmModal from './ConfirmModal'
import { getEffectiveSpeed } from '../types'
export default function DetailPanel() {
  // PERF: selectors riêng — KHÔNG destructure
  const subtitles = useStore(s => s.subtitles)
  const characters = useStore(s => s.characters)
  const project = useStore(s => s.project)
  const activeSubId = useStore(s => s.activeSubId)
  const updateSubtitle = useStore(s => s.updateSubtitle)
  const selectedIds = useStore(s => s.selectedIds)

  const activeSub = subtitles.find(s => s.id === activeSubId)
  const lastSubRef = React.useRef<typeof activeSub | undefined>(undefined)
  if (activeSub) (lastSubRef as React.MutableRefObject<typeof activeSub>).current = activeSub
  const sub = lastSubRef.current

  const [ttsLoading, setTtsLoading] = useState(false)
  const [bulkTtsLoading, setBulkTtsLoading] = useState(false)
  // Modal xác nhận
  const [confirmCfg, setConfirmCfg] = useState<{
    title: string
    message: string
    warnings?: string[]
    variant?: 'default' | 'danger' | 'warning'
    confirmText?: string
    onConfirm: () => void
  } | null>(null)
  const [bulkDelLoading, setBulkDelLoading] = useState(false)
  const [bulkAudioDelLoading, setBulkAudioDelLoading] = useState(false)
  const [trimLoading, setTrimLoading] = useState(false)
  const [trimDb, setTrimDb] = useState(-35)
  const [trimMsg, setTrimMsg] = useState('')
  const [exportPct, setExportPct] = useState(-1)  // -1 = idle
  const [exportMsg, setExportMsg] = useState('')

  React.useEffect(() => {
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

  const done = subtitles.filter(s => s.tts_done).length
  const total = subtitles.length
  const noChar = subtitles.filter(s => !s.character_id).length
  const pct = total ? Math.round(done / total * 100) : 0

  const bulkTTS = async () => {
    if (!project) return
    const total = subtitles.filter(s => !s.tts_done).length
    const willGenerate = subtitles.filter(s => !s.tts_done && s.character_id).map(s => s.id)
    const skipped = total - willGenerate.length

    if (!willGenerate.length) {
      setConfirmCfg({
        title: 'Không có gì để tạo',
        message: skipped > 0
          ? `${skipped} dòng chưa gán nhân vật bị bỏ qua, không có dòng nào hợp lệ để tạo TTS.`
          : 'Tất cả phụ đề đã có TTS rồi!',
        variant: 'default',
        confirmText: 'Đóng',
        onConfirm: () => setConfirmCfg(null),
      })
      return
    }

    const warnings: string[] = []
    if (skipped > 0) warnings.push(`Bỏ qua ${skipped} dòng chưa gán nhân vật`)

    setConfirmCfg({
      title: 'Tạo TTS tất cả',
      message: `Sẽ tạo TTS cho ${willGenerate.length} dòng đã gán nhân vật. Quá trình này có thể mất nhiều thời gian.`,
      warnings,
      variant: 'default',
      confirmText: 'Bắt đầu tạo',
      onConfirm: async () => {
        setConfirmCfg(null)
        try {
          await api.post('/tts/bulk', { subtitle_ids: willGenerate })
        } catch (e: any) {
          setConfirmCfg({
            title: 'Lỗi',
            message: e?.response?.data?.detail || e?.message || 'Không thể tạo TTS',
            variant: 'danger',
            confirmText: 'Đóng',
            onConfirm: () => setConfirmCfg(null),
          })
        }
      },
    })
  }

  const bulkTTSSelected = async () => {
    const allSel = Array.from(useStore.getState().selectedIds)
    if (!allSel.length) {
      setConfirmCfg({
        title: 'Chưa chọn dòng nào',
        message: 'Hãy chọn các dòng phụ đề muốn tạo TTS trước.',
        variant: 'default',
        confirmText: 'Đóng',
        onConfirm: () => setConfirmCfg(null),
      })
      return
    }
    const subs = useStore.getState().subtitles
    const willGenerate = allSel.filter(id => {
      const s = subs.find(x => x.id === id)
      return s && s.character_id
    })
    const noChar = allSel.length - willGenerate.length

    if (!willGenerate.length) {
      setConfirmCfg({
        title: 'Không có dòng nào hợp lệ',
        message: `Trong ${allSel.length} dòng đã chọn, không có dòng nào đã gán nhân vật.`,
        variant: 'default',
        confirmText: 'Đóng',
        onConfirm: () => setConfirmCfg(null),
      })
      return
    }

    const existing = willGenerate.filter(id => {
      const s = subs.find(x => x.id === id)
      return s && s.tts_done
    }).length

    const warnings: string[] = []
    if (existing > 0) warnings.push(`${existing} dòng đã có TTS — audio cũ sẽ bị GHI ĐÈ`)
    if (noChar > 0) warnings.push(`Bỏ qua ${noChar} dòng chưa gán nhân vật`)

    setConfirmCfg({
      title: 'Tạo TTS cho mục đã chọn',
      message: `Sẽ tạo TTS cho ${willGenerate.length} dòng.`,
      warnings,
      variant: existing > 0 ? 'warning' : 'default',
      confirmText: existing > 0 ? 'Ghi đè và tạo lại' : 'Bắt đầu tạo',
      onConfirm: async () => {
        setConfirmCfg(null)
        setBulkTtsLoading(true)
        try {
          await api.post('/tts/bulk', { subtitle_ids: willGenerate })
        } catch (e: any) {
          setConfirmCfg({
            title: 'Lỗi',
            message: e?.response?.data?.detail || e?.message || 'Không thể tạo TTS',
            variant: 'danger',
            confirmText: 'Đóng',
            onConfirm: () => setConfirmCfg(null),
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
    if (!ids.length) return alert('Không có audio nào để xóa!')
    if (!confirm(`Xóa audio của ${ids.length} dòng đã chọn?`)) return
    setBulkAudioDelLoading(true)
    try {
      await api.post('/tts/delete-audio', { subtitle_ids: ids })
      useStore.getState().deleteAudio(ids)
    } finally { setBulkAudioDelLoading(false) }
  }

  const bulkDeleteSelected = async () => {
    const ids = Array.from(useStore.getState().selectedIds)
    if (!ids.length) return alert('Chưa chọn dòng nào!')
    if (!confirm(`Xóa ${ids.length} dòng đã chọn?`)) return
    setBulkDelLoading(true)
    try {
      await api.post('/subtitles/bulk-delete', { subtitle_ids: ids })
      ids.forEach(id => useStore.getState().deleteSubtitle(id))
      useStore.setState({ selectedIds: new Set(), activeSubId: null })
    } finally { setBulkDelLoading(false) }
  }

  const genTTS = async () => {
    if (!sub) return
    setTtsLoading(true)
    try {
      const res = await api.post('/tts/generate', { subtitle_id: sub.id })
      updateSubtitle(sub.id, { tts_done: true, audio_path: res.data.audio_path })
    } finally { setTtsLoading(false) }
  }

  // Trim 1 dòng
  const trimOne = async () => {
    if (!sub?.audio_path) return
    setTrimLoading(true); setTrimMsg('')
    try {
      const res = await api.post('/tts/trim', {
        subtitle_id: sub.id,
        threshold_db: trimDb,
      })
      // update tts_done=true để trigger lastTtsAt
      updateSubtitle(sub.id, { audio_path: res.data.audio_path, tts_done: true })
      setTrimMsg(`✓ ${res.data.before_s.toFixed(2)}s → ${res.data.after_s.toFixed(2)}s`)
    } catch {
      setTrimMsg('Lỗi trim')
    } finally { setTrimLoading(false) }
  }

  // Trim tất cả
  const trimAll = async () => {
    if (!project) return
    setTrimLoading(true); setTrimMsg('')
    try {
      const ids = subtitles.filter(s => s.tts_done && s.audio_path).map(s => s.id)
      const res = await api.post('/tts/trim-bulk', {
        subtitle_ids: ids,
        threshold_db: trimDb,
      })
      // Update tất cả subtitle đã trim để trigger lastTtsAt
      ids.forEach(id => updateSubtitle(id, { tts_done: true }))
      setTrimMsg(`✓ Đã trim ${res.data.trimmed}/${ids.length} file`)
    } catch {
      setTrimMsg('Lỗi trim')
    } finally { setTrimLoading(false) }
  }

  const playAudio = () => sub?.audio_path && new Audio(sub.audio_path!).play()
  const exportAudio = async () => { if (!project) return; setExportPct(0); setExportMsg('Đang khởi động...'); await api.post('/export/audio', { project_id: project.id }) }
  const exportVideo = async () => { if (!project) return; await api.post('/export/video', { project_id: project.id }); alert('Đang xuất video...') }
  const exportSrt = async () => {
    if (!project) return
    setExportPct(0); setExportMsg('Đang xuất SRT...')
    await api.post('/export/srt', { project_id: project.id, only_with_audio: false })
  }
  const exportSrtWithAudio = async () => {
    if (!project) return
    setExportPct(0); setExportMsg('Đang xuất SRT (đồng bộ audio)...')
    await api.post('/export/srt', { project_id: project.id, only_with_audio: true })
  }

  return (
    <div className="w-44 flex-shrink-0 flex flex-col bg-white dark:bg-zinc-900 border-l border-zinc-200 dark:border-zinc-800 overflow-y-auto text-[13px]">

      {/* Dòng hiện tại */}
      {sub && (
        <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-1.5">
          <p className="panel-label">Dòng #{sub.index}</p>
          <Row k="Thời lượng" v={`${(sub.end_time - sub.start_time).toFixed(1)}s`} />
          <Row k="Ký tự" v={String(sub.text.length)} />
          <Row k="Nhân vật" v={sub.character?.name || '—'} color={sub.character?.color} />
          <div className="flex items-center justify-between gap-1">
            <span className="text-[12px] text-zinc-500">TTS</span>
            <span className="text-[12px] font-medium" style={{ color: sub.tts_done ? '#10b981' : '#9ca3af' }}>
              {sub.tts_done ? '✓ Đã tạo' : 'Chưa'}
            </span>
          </div>
          <div className="flex gap-1.5 pt-0.5">
            <button onClick={playAudio} disabled={!sub.audio_path}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-700 text-[11px] font-medium text-zinc-600 dark:text-zinc-400 hover:bg-zinc-50 dark:hover:bg-zinc-800 disabled:opacity-40 transition-colors">
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.2" />
                <path d="M4.5 3.5L9 6L4.5 8.5V3.5Z" fill="currentColor" />
              </svg>
              Nghe
            </button>
            <button onClick={genTTS} disabled={ttsLoading}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-[11px] font-medium text-white disabled:opacity-60 transition-colors">
              <svg width="11" height="11" viewBox="0 0 12 12" fill="none">
                <path d="M1.5 4.5H3.5L6 2V10L3.5 7.5H1.5V4.5Z" fill="currentColor" />
                <path d="M8 4C8.8 4.8 8.8 7.2 8 8" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
                <path d="M9.5 2.5C11 4 11 8 9.5 9.5" stroke="currentColor" strokeWidth="1.1" strokeLinecap="round" />
              </svg>
              {ttsLoading ? '...' : 'TTS'}
            </button>
          </div>
        </section>
      )}

      {/* Speed control */}
      {sub && <SpeedSection sub={sub} setConfirmCfg={setConfirmCfg} />}

      {/* Tiến độ */}
      <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-2">
        <p className="panel-label">Tiến độ</p>
        <div className="flex justify-between text-[12px] text-zinc-500">
          <span>TTS</span>
          <span className="font-semibold text-zinc-700 dark:text-zinc-300">{done}/{total}</span>
        </div>
        <div className="h-1.5 bg-zinc-100 dark:bg-zinc-800 rounded-full overflow-hidden">
          <div className="h-full bg-blue-500 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
        </div>
        <div className="flex justify-between text-[12px]">
          <span className="text-zinc-500">Hoàn thành</span>
          <span className="font-semibold">{pct}%</span>
        </div>
        {noChar > 0 && <Row k="Chưa gán" v={String(noChar)} color="#F59E0B" />}
      </section>

      {/* Tác vụ */}
      <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-2">
        <p className="panel-label">Tác vụ</p>
        <button onClick={bulkTTS} className="btn-primary w-full text-[12px] py-1.5">TTS tất cả</button>

        {/* Thao tác với phụ đề đã chọn */}
        <div className="pt-1 border-t border-zinc-100 dark:border-zinc-800 space-y-1.5">
          <p className="text-[10px] text-zinc-400 font-medium uppercase tracking-wide">
            Đã chọn: {selectedIds.size} dòng
          </p>
          <div className="flex gap-1.5">
            <button onClick={bulkTTSSelected}
              disabled={bulkTtsLoading}
              className="flex-1 py-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-[11px] font-medium text-white disabled:opacity-60 transition-colors">
              {bulkTtsLoading ? '...' : '🎙 TTS'}
            </button>
            <button onClick={bulkDeleteSelected}
              disabled={bulkDelLoading}
              className="flex-1 py-1.5 rounded-lg bg-red-50 hover:bg-red-100 dark:bg-red-950/30 border border-red-200 dark:border-red-900 text-[11px] font-medium text-red-600 dark:text-red-400 disabled:opacity-60 transition-colors">
              {bulkDelLoading ? '...' : '🗑 Xóa'}
            </button>
          </div>
          <button onClick={bulkDeleteAudio}
            disabled={bulkAudioDelLoading}
            className="w-full py-1.5 rounded-lg bg-orange-50 hover:bg-orange-100 dark:bg-orange-950/30 border border-orange-200 dark:border-orange-900 text-[11px] font-medium text-orange-600 dark:text-orange-400 disabled:opacity-60 transition-colors">
            {bulkAudioDelLoading ? '...' : '🔇 Xóa audio đã chọn'}
          </button>
        </div>
        <button onClick={exportAudio} disabled={exportPct >= 0 && exportPct < 100}
          className="btn w-full text-[12px] py-1.5 disabled:opacity-60">
          {exportPct >= 0 && exportPct < 100 ? `Đang xuất ${exportPct}%` : 'Xuất audio'}
        </button>
        <button onClick={exportVideo} disabled={exportPct >= 0 && exportPct < 100}
          className="btn w-full text-[12px] py-1.5 disabled:opacity-60">Xuất video</button>
        <button onClick={exportSrtWithAudio} disabled={exportPct >= 0 && exportPct < 100}
          title="Xuất SRT đồng bộ với audio đã chỉnh (chỉ sub đã có TTS)"
          className="btn w-full text-[12px] py-1.5 disabled:opacity-60">
          📄 Xuất SRT (đồng bộ audio)
        </button>
        <button onClick={exportSrt} disabled={exportPct >= 0 && exportPct < 100}
          title="Xuất SRT đầy đủ (gồm cả sub chưa có TTS — dùng end_time gốc)"
          className="btn w-full text-[12px] py-1.5 disabled:opacity-60 text-zinc-500">
          📄 Xuất SRT (tất cả)
        </button>
        {/* Progress bar */}
        {exportPct >= 0 && (
          <div className="space-y-1">
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

      {/* Trim silence */}
      <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-2">
        <p className="panel-label">✂ Trim silence</p>

        {/* Threshold slider */}
        <div className="space-y-1">
          <div className="flex justify-between text-[11px] text-zinc-500">
            <span>Ngưỡng cắt</span>
            <span className="font-mono font-semibold text-zinc-700 dark:text-zinc-300">{trimDb} dB</span>
          </div>
          <input type="range" min={-60} max={-10} step={1} value={trimDb}
            onChange={e => setTrimDb(parseInt(e.target.value))}
            className="w-full accent-violet-500 cursor-pointer" style={{ height: 4 }} />
          <div className="flex justify-between text-[9px] text-zinc-400">
            <span>-60 (ít cắt)</span>
            <span>-10 (nhiều)</span>
          </div>
          {/* Gợi ý */}
          <div className="flex gap-1 flex-wrap">
            {[[-50, 'Nhẹ'], [-35, 'Tối ưu'], [-20, 'Mạnh']].map(([v, label]) => (
              <button key={v} onClick={() => setTrimDb(v as number)}
                className={`px-1.5 py-0.5 rounded text-[9px] font-medium transition-colors ${trimDb === v ? 'bg-violet-100 text-violet-700 dark:bg-violet-950 dark:text-violet-300' : 'bg-zinc-100 text-zinc-500 dark:bg-zinc-800 hover:bg-zinc-200'}`}>
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Nút trim */}
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

        {/* Kết quả */}
        {trimMsg && (
          <p className="text-[10px] text-center font-medium"
            style={{ color: trimMsg.startsWith('✓') ? '#10B981' : '#EF4444' }}>
            {trimMsg}
          </p>
        )}
      </section>

      {/* Phím tắt */}
      <section className="p-3 space-y-2">
        <p className="panel-label">Phím tắt</p>
        <div className="space-y-1.5">
          {[['Space', 'Play/Pause'], ['↑↓', 'Di chuyển'], ['1–9', 'Gán char'], ['Ctrl+T', 'TTS dòng'], ['[ ]', '±100ms'], ['Del', 'Xóa dòng']].map(([k, v]) => (
            <div key={k} className="flex items-center justify-between gap-2">
              <span className="kbd">{k}</span>
              <span className="text-[11px] text-zinc-500 text-right">{v}</span>
            </div>
          ))}
        </div>
      </section>
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
    </div>

  )

}

function Row({ k, v, color }: { k: string; v: string; color?: string }) {
  return (
    <div className="flex justify-between items-center gap-2">
      <span className="text-[12px] text-zinc-500">{k}</span>
      <span className="text-[12px] font-medium truncate" style={{ color: color || undefined }}>{v}</span>
    </div>
  )
}


// ─── SpeedSection: chỉnh tốc độ TTS ─────────────────────────────────────────
interface SpeedSectionProps {
  sub: any
  setConfirmCfg: (cfg: any) => void
}

function SpeedSection({ sub, setConfirmCfg }: SpeedSectionProps) {
  const characters = useStore(s => s.characters)
  const subtitles = useStore(s => s.subtitles)
  const updateSubtitle = useStore(s => s.updateSubtitle)
  const setCharacters = useStore(s => s.setCharacters)
  const selectedIds = useStore(s => s.selectedIds)

  const char = sub.character || characters.find((c: any) => c.id === sub.character_id)
  const effective = getEffectiveSpeed(sub, char)
  const isInherited = sub.tts_speed == null

  const [val, setVal] = React.useState(effective)
  const [mode, setMode] = React.useState<'this' | 'selection' | 'character'>('this')

  React.useEffect(() => {
    setVal(effective)
  }, [sub.id, effective])

  const apply = async () => {
    const speed = Math.max(0.5, Math.min(2.0, val))
    if (mode === 'this') {
      // Set cho 1 sub
      try {
        await api.post('/tts/bulk-set-speed', { subtitle_ids: [sub.id], tts_speed: speed })
        updateSubtitle(sub.id, { tts_speed: speed })
      } catch (e) {
        alert('Lỗi: ' + (e as any)?.message)
      }
    } else if (mode === 'selection') {
      const ids = Array.from(selectedIds)
      if (!ids.length) {
        alert('Chưa chọn dòng nào')
        return
      }
      try {
        await api.post('/tts/bulk-set-speed', { subtitle_ids: ids, tts_speed: speed })
        ids.forEach(id => updateSubtitle(id, { tts_speed: speed }))
      } catch (e) {
        alert('Lỗi: ' + (e as any)?.message)
      }
    } else if (mode === 'character') {
      if (!char) {
        alert('Sub chưa gán nhân vật')
        return
      }
      const charSubs = subtitles.filter(s => s.character_id === char.id)
      const overrideCount = charSubs.filter(s => s.tts_speed != null).length

      const doApply = async () => {
        try {
          await api.post(`/tts/character/${char.id}/set-speed`, {
            tts_speed: speed,
            apply_to_subs: true,
          })
          // Update local: character speed mới + clear sub overrides
          setCharacters(characters.map((c: any) =>
            c.id === char.id ? { ...c, tts_speed: speed } : c
          ))
          charSubs.forEach(s => {
            if (s.tts_speed != null) updateSubtitle(s.id, { tts_speed: null })
          })
        } catch (e) {
          alert('Lỗi: ' + (e as any)?.message)
        }
      }

      // Confirm trước nếu ảnh hưởng nhiều
      setConfirmCfg({
        title: `Đặt tốc độ ${speed.toFixed(2)}x cho "${char.name}"`,
        message: `Sẽ áp dụng cho ${charSubs.length} dòng của nhân vật này.`,
        warnings: overrideCount > 0
          ? [`${overrideCount} dòng đã có tốc độ riêng — sẽ bị reset về tốc độ chung của nhân vật`]
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
    // Clear override của sub này → kế thừa từ character
    try {
      await api.post('/tts/bulk-set-speed', { subtitle_ids: [sub.id], tts_speed: null })
      updateSubtitle(sub.id, { tts_speed: null })
    } catch (e) {
      alert('Lỗi: ' + (e as any)?.message)
    }
  }

  return (
    <section className="p-3 border-b border-zinc-100 dark:border-zinc-800 space-y-2">
      <div className="flex items-center justify-between">
        <p className="panel-label !mb-0">⚡ Tốc độ TTS</p>
        <span className="text-[11px] tabular-nums font-bold text-blue-600">{val.toFixed(2)}x</span>
      </div>

      <input
        type="range" min="0.5" max="2.0" step="0.05"
        value={val}
        onChange={e => setVal(parseFloat(e.target.value))}
        className="w-full"
      />

      <div className="flex justify-between text-[10px] text-zinc-400">
        <span>0.5x</span><span>1.0x</span><span>2.0x</span>
      </div>

      {isInherited && char && (
        <div className="text-[10px] text-zinc-500 italic">
          Đang kế thừa từ "{char.name}" ({(char.tts_speed || 1.0).toFixed(2)}x)
        </div>
      )}

      <div className="space-y-1">
        <p className="text-[10px] text-zinc-500 uppercase tracking-wider">Áp dụng cho</p>
        <label className="flex items-center gap-1.5 cursor-pointer text-[12px]">
          <input type="radio" checked={mode === 'this'} onChange={() => setMode('this')} className="accent-blue-600"/>
          <span>Sub này</span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer text-[12px]">
          <input type="radio" checked={mode === 'selection'} onChange={() => setMode('selection')} className="accent-blue-600"/>
          <span>Đã chọn ({selectedIds.size})</span>
        </label>
        {char && (
          <label className="flex items-center gap-1.5 cursor-pointer text-[12px]">
            <input type="radio" checked={mode === 'character'} onChange={() => setMode('character')} className="accent-blue-600"/>
            <span className="truncate">NV "{char.name}"</span>
          </label>
        )}
      </div>

      <div className="flex gap-1.5">
        {!isInherited && (
          <button onClick={reset}
            className="flex-1 py-1.5 text-[11px] rounded-lg border border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-zinc-500">
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