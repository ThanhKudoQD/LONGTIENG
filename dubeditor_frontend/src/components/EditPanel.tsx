import React, { useEffect, useState, useRef } from 'react'
import useStore from '../store'
import useUndoStore from '../store/undo'
import api, { translateApi } from '../api'
import { secToSrt, srtToSec } from '../types'

export default function EditPanel() {
  // PERF: selectors riêng
  const subtitles = useStore(s => s.subtitles)
  const characters = useStore(s => s.characters)
  const activeSubId = useStore(s => s.activeSubId)
  const updateSubtitle = useStore(s => s.updateSubtitle)
  const deleteSubtitle = useStore(s => s.deleteSubtitle)
  const setActiveSubId = useStore(s => s.setActiveSubId)
  const project = useStore(s => s.project)

  const activeSub = subtitles.find(s => s.id === activeSubId) ?? null
  const lastSubRef = useRef<typeof activeSub>(null)
  if (activeSub) lastSubRef.current = activeSub
  const sub = lastSubRef.current

  const [text, setText] = useState('')
  const [textV1, setTextV1] = useState('')
  const [textV2, setTextV2] = useState('')
  const [variantSelected, setVariantSelected] = useState<1 | 2>(1)
  const [start, setStart] = useState('')
  const [end, setEnd] = useState('')
  const [charId, setCharId] = useState('')
  const [saving, setSaving] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  // Reset state khi activeSub đổi
  useEffect(() => {
    if (!activeSub) return
    setText(activeSub.text || '')
    setTextV1(activeSub.text_v1 || activeSub.text || '')
    setTextV2(activeSub.text_v2 || '')
    setVariantSelected((activeSub.variant_selected as 1 | 2) || 1)
    setStart(secToSrt(activeSub.start_time))
    setEnd(secToSrt(activeSub.end_time))
    setCharId(activeSub.character_id ? String(activeSub.character_id) : '')
    setConfirmDelete(false)
  }, [activeSub?.id])

  useEffect(() => {
    if (!activeSub) return
    setCharId(activeSub.character_id ? String(activeSub.character_id) : '')
  }, [activeSub?.character_id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      if (e.key === 'Delete' && sub && !confirmDelete) { e.preventDefault(); setConfirmDelete(true) }
      if (e.key === 'Enter' && confirmDelete) { e.preventDefault(); handleDelete() }
      if (e.key === 'Escape' && confirmDelete) setConfirmDelete(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [confirmDelete, sub?.id])

  const handleDelete = async () => {
    if (!sub) return
    const idx = subtitles.findIndex(s => s.id === sub.id)
    const res = await api.delete(`/subtitles/${sub.id}`)
    const backup = res.data?.backup || []
    deleteSubtitle(sub.id)
    setConfirmDelete(false)
    lastSubRef.current = null
    const remaining = subtitles.filter(s => s.id !== sub.id)
    if (remaining.length > 0) setActiveSubId(remaining[Math.min(idx, remaining.length - 1)].id)

    if (backup.length) {
      const subIdToRestore = sub.id
      useUndoStore.getState().push({
        label: `Đã xóa phụ đề #${sub.index}`,
        restore: async () => {
          await api.post('/subtitles/restore', { backup })
          const pid = useStore.getState().project?.id
          if (pid) {
            const subs = await api.get(`/subtitles/project/${pid}`).then(r => r.data)
            useStore.getState().setSubtitles(subs)
            setActiveSubId(subIdToRestore)
          }
        },
      })
    }
  }

  const hasVariant = !!(sub && sub.text_v2 && sub.text_v2.trim())

  const save = async () => {
    if (!sub) return
    setSaving(true)
    try {
      const patch: any = {}
      // Xác định text active đang edit là v1 hay v2
      const editingV2 = variantSelected === 2 && hasVariant
      if (editingV2) {
        // Edit v2
        if (textV2 !== (sub.text_v2 || '')) patch.text_v2 = textV2
      } else {
        // Edit v1
        if (textV1 !== (sub.text_v1 || sub.text || '')) patch.text_v1 = textV1
      }
      // Nếu variant đổi
      if (variantSelected !== (sub.variant_selected || 1)) {
        patch.variant_selected = variantSelected
      }

      const newStart = srtToSec(start)
      const newEnd = srtToSec(end)
      if (Math.abs(newStart - sub.start_time) > 0.001) patch.start_time = newStart
      if (Math.abs(newEnd - sub.end_time) > 0.001) patch.end_time = newEnd
      const newCharId = charId ? parseInt(charId) : null
      if (newCharId !== sub.character_id) patch.character_id = newCharId

      if (Object.keys(patch).length === 0) return

      const updated = await api.patch(`/subtitles/${sub.id}`, patch).then(r => r.data)
      // Cập nhật store với data mới nhất từ server (vì backend đã sync text active + cps)
      const updates: any = {
        text: updated.text,
        text_v1: updated.text_v1,
        text_v2: updated.text_v2,
        variant_selected: updated.variant_selected,
        cps_value: updated.cps_value,
      }
      if ('character_id' in patch) {
        updates.character = characters.find(c => c.id === patch.character_id) || null
        updates.character_id = patch.character_id
      }
      if ('start_time' in patch) updates.start_time = patch.start_time
      if ('end_time' in patch) updates.end_time = patch.end_time
      updateSubtitle(sub.id, updates)

      // ── Auto TTS ──────────────────────────────────────────────────────
      // Nếu text active đã đổi (text_v1/text_v2/variant) HOẶC vừa gán nhân vật mới
      // → dispatch event để Editor.tsx batch enqueue TTS (chỉ khi autoTTS BẬT).
      // Hook ngay cuối save() vì lúc này store đã có data mới nhất + character_id
      // mới nhất, autoTTS batch sẽ resolve đúng giọng.
      const textChanged = 'text_v1' in patch || 'text_v2' in patch || 'variant_selected' in patch
      const charChanged = 'character_id' in patch
      const finalCharId = 'character_id' in patch ? patch.character_id : sub.character_id
      if ((textChanged || charChanged) && finalCharId) {
        window.dispatchEvent(new CustomEvent('subs_assigned', {
          detail: { subtitle_ids: [sub.id] },
        }))
      }
    } finally {
      setSaving(false)
    }
  }

  // Switch variant nhanh (gọi API + cập nhật state)
  const switchVariant = async (newVariant: 1 | 2) => {
    if (!sub || !project) return
    setVariantSelected(newVariant)
    try {
      const res = await translateApi.selectVariant(project.id, sub.id, newVariant)
      updateSubtitle(sub.id, {
        text: res.text,
        variant_selected: newVariant,
        cps_value: res.cps_value,
        tts_done: false,
        audio_path: null,
      })
      // v3.13 FIX: Switch variant đã đổi text active → cần regenerate TTS.
      // Dispatch event để Editor batch enqueue (chỉ khi autoTTS BẬT + đã có nhân vật).
      if (sub.character_id) {
        window.dispatchEvent(new CustomEvent('subs_assigned', {
          detail: { subtitle_ids: [sub.id] },
        }))
      }
    } catch (e) {
      console.warn('switch variant failed', e)
    }
  }

  return (
    <div className="border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex-shrink-0 p-3 space-y-2 relative">

      {/* Confirm delete */}
      {confirmDelete && sub && (
        <div className="absolute inset-0 z-20 bg-white/95 dark:bg-zinc-900/95 flex flex-col items-center justify-center gap-3 rounded">
          <p className="text-[13px] text-zinc-700 dark:text-zinc-300 text-center px-4">
            Xóa dòng <span className="font-semibold">#{sub.index}</span>?<br/>
            <span className="text-zinc-400 text-[12px]">"{(sub.text || '').slice(0, 40)}{(sub.text || '').length > 40 ? '...' : ''}"</span>
          </p>
          <div className="flex gap-2">
            <button onClick={handleDelete} className="px-4 py-1.5 rounded-lg bg-red-500 hover:bg-red-600 text-white text-[13px] font-medium transition-colors">Xóa (Enter)</button>
            <button onClick={() => setConfirmDelete(false)} className="px-4 py-1.5 rounded-lg border border-zinc-200 text-[13px] hover:bg-zinc-50 transition-colors">Huỷ (Esc)</button>
          </div>
        </div>
      )}

      {!sub ? (
        <div className="flex items-center justify-center h-[80px] rounded-lg border border-dashed border-zinc-200 dark:border-zinc-700 text-[12px] text-zinc-400">
          Phát video để xem phụ đề
        </div>
      ) : (
        <>
          {/* Variant picker — chỉ hiện khi có text_v2 */}
          {hasVariant && (
            <div className="flex items-center gap-2">
              <span className="text-[11px] text-zinc-500 uppercase tracking-widest">Bản dịch:</span>
              <div className="flex gap-1">
                <button
                  onClick={() => switchVariant(1)}
                  className={`px-2.5 py-1 rounded-md text-[12px] font-medium transition-all ${
                    variantSelected === 1
                      ? 'bg-blue-600 text-white shadow'
                      : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                  }`}
                  title="Sát nghĩa — chính xác, phù hợp subtitle"
                >
                  v1: Sát nghĩa
                </button>
                <button
                  onClick={() => switchVariant(2)}
                  className={`px-2.5 py-1 rounded-md text-[12px] font-medium transition-all ${
                    variantSelected === 2
                      ? 'bg-purple-600 text-white shadow'
                      : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700'
                  }`}
                  title="Thoát ý — tự nhiên, phù hợp lồng tiếng"
                >
                  v2: Thoát ý
                </button>
              </div>
              {sub.original_text && (
                <span className="ml-auto text-[10px] font-mono text-zinc-400 truncate max-w-md">
                  {sub.original_text}
                </span>
              )}
            </div>
          )}

          {/* Hiển thị 2 bản (khi có variant) */}
          {hasVariant ? (
            <div className="grid grid-cols-2 gap-2">
              <div className={`relative rounded-lg border-2 ${
                variantSelected === 1
                  ? 'border-blue-500 bg-blue-50/30 dark:bg-blue-900/10'
                  : 'border-zinc-200 dark:border-zinc-700'
              }`}>
                <div className="absolute -top-2 left-2 px-1.5 text-[10px] bg-white dark:bg-zinc-900 text-blue-600 dark:text-blue-400 font-semibold">
                  v1 · sát nghĩa
                </div>
                <textarea
                  value={textV1}
                  onChange={e => setTextV1(e.target.value)}
                  rows={3}
                  className="w-full p-2 pt-3 bg-transparent text-[13px] resize-none focus:outline-none"
                  style={{ minHeight: 72 }}
                />
              </div>
              <div className={`relative rounded-lg border-2 ${
                variantSelected === 2
                  ? 'border-purple-500 bg-purple-50/30 dark:bg-purple-900/10'
                  : 'border-zinc-200 dark:border-zinc-700'
              }`}>
                <div className="absolute -top-2 left-2 px-1.5 text-[10px] bg-white dark:bg-zinc-900 text-purple-600 dark:text-purple-400 font-semibold">
                  v2 · thoát ý
                </div>
                <textarea
                  value={textV2}
                  onChange={e => setTextV2(e.target.value)}
                  rows={3}
                  className="w-full p-2 pt-3 bg-transparent text-[13px] resize-none focus:outline-none"
                  style={{ minHeight: 72 }}
                />
              </div>
            </div>
          ) : (
            /* Chỉ 1 bản */
            <div className="flex gap-2 items-stretch">
              <textarea
                value={textV1}
                onChange={e => setTextV1(e.target.value)}
                rows={3}
                className="input text-[14px] flex-1 resize-none leading-relaxed font-medium"
                style={{ minHeight: 72 }}
              />
            </div>
          )}

          {/* Save button + info bar */}
          <div className="flex items-center gap-2">
            <div className="flex-1 flex items-center gap-2 text-[11px] text-zinc-500">
              {sub.cps_value != null && (
                <span className={sub.cps_value > 22 ? 'text-red-500 font-semibold' : ''}>
                  CPS: {sub.cps_value.toFixed(1)}
                </span>
              )}
              {sub.emotion && (
                <span>· {sub.emotion}</span>
              )}
              {sub.speaker_zh && (
                <span>· {sub.speaker_zh}</span>
              )}
            </div>
            <button
              onClick={save}
              disabled={saving}
              className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-[13px] font-medium disabled:opacity-60 transition-all"
            >
              {saving ? '⏳ Đang lưu...' : '💾 Lưu'}
            </button>
          </div>
        </>
      )}
    </div>
  )
}