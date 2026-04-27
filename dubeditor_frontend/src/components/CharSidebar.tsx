import React, { useState, useRef, useEffect } from 'react'
import useStore from '../store'
import api from '../api'
import { VoxActor, VoxRole } from '../types'
import VoicePicker from './VoicePicker'

interface Props { visible: boolean }

let _sidebarAudio: HTMLAudioElement | null = null

interface Preset {
  id: number
  name: string
  char_count: number
  created_at: string
}

export default function CharSidebar({ visible }: Props) {
  const { characters, project, selectedIds, updateSubtitle, setCharacters, subtitles } = useStore()
  const [showPicker, setShowPicker]     = useState(false)
  const [editingId, setEditingId]       = useState<number | null>(null)
  const [editingName, setEditingName]   = useState('')
  const [playingAudio, setPlayingAudio] = useState<string | null>(null)
  const [showPresets, setShowPresets]   = useState(false)
  const [presets, setPresets]           = useState<Preset[]>([])
  const [presetName, setPresetName]     = useState('')
  const [saving, setSaving]             = useState(false)
  const [loading, setLoading]           = useState(false)

  // Drag-to-sort state
  const dragIdx = useRef<number | null>(null)
  const [dragOverIdx, setDragOverIdx]   = useState<number | null>(null)

  // Speaker mapping modal
  const [mappingCharId, setMappingCharId] = useState<number | null>(null)

  // Active character từ subtitle đang active
  const { activeSubId } = useStore()
  const activeSub = useStore(s => s.subtitles.find(s2 => s2.id === s.activeSubId))
  const activeCharId = activeSub?.character_id ?? null
  const activeCardRefs = useRef<Record<number, HTMLDivElement | null>>({})

  // Scroll tới nhân vật active
  useEffect(() => {
    if (activeCharId && activeCardRefs.current[activeCharId]) {
      activeCardRefs.current[activeCharId]?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [activeCharId])
  const [replacingCharId, setReplacingCharId] = useState<number | null>(null)

  // ── Drag sort ──────────────────────────────────────────────
  const onDragStart = (e: React.DragEvent, idx: number, charId: number) => {
    dragIdx.current = idx
    e.dataTransfer.setData('charId', String(charId))
    e.dataTransfer.effectAllowed = 'move'
  }

  const onDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    setDragOverIdx(idx)
  }

  const onDrop = (e: React.DragEvent, dropIdx: number) => {
    e.preventDefault()
    e.stopPropagation()
    const fromIdx = dragIdx.current
    if (fromIdx === null || fromIdx === dropIdx) { setDragOverIdx(null); return }

    const newChars = [...characters]
    const [moved] = newChars.splice(fromIdx, 1)
    newChars.splice(dropIdx, 0, moved)
    setCharacters(newChars)
    dragIdx.current = null
    setDragOverIdx(null)
  }

  const onDragEnd = () => { dragIdx.current = null; setDragOverIdx(null) }

  // ── Presets ────────────────────────────────────────────────
  const loadPresets = async () => {
    try { const res = await api.get('/presets'); setPresets(res.data.presets) } catch {}
  }

  const savePreset = async () => {
    if (!project || !presetName.trim()) return
    setSaving(true)
    try {
      await api.post('/presets/save', { name: presetName.trim(), project_id: project.id })
      setPresetName(''); await loadPresets()
    } finally { setSaving(false) }
  }

  const loadPreset = async (presetId: number) => {
    if (!project) return
    if (!confirm('Load preset sẽ xóa nhân vật hiện tại. Tiếp tục?')) return
    setLoading(true)
    try {
      const res = await api.post('/presets/load', { preset_id: presetId, project_id: project.id })
      setCharacters(res.data.chars); setShowPresets(false)
    } finally { setLoading(false) }
  }

  const deletePreset = async (presetId: number, e: React.MouseEvent) => {
    e.stopPropagation()
    await api.delete(`/presets/${presetId}`)
    setPresets(p => p.filter(x => x.id !== presetId))
  }

  // ── VoicePicker ────────────────────────────────────────────
  const handleSelect = async (actor: VoxActor, role: VoxRole, alias: string, color: string) => {
    if (!project) return
    const charName = alias || role.character_name || actor.name
    const res = await api.post(`/characters/project/${project.id}`, {
      name: charName, description: '', color,
      avatar: actor.avatar || '',
      voxcpm_role_id: role.id,
      voxcpm_actor_name: actor.name,
      voxcpm_role_name: role.character_name,
      audio: role.audio || '',
    })
    setCharacters([...useStore.getState().characters, res.data])
  }

  // ── Edit name ──────────────────────────────────────────────
  const saveCharName = async (charId: number) => {
    if (!editingName.trim()) { setEditingId(null); return }
    const newName = editingName.trim()
    await api.patch(`/characters/${charId}`, { name: newName })
    const updated = characters.map(c => c.id === charId ? { ...c, name: newName } : c)
    setCharacters(updated)
    const { subtitles: subs } = useStore.getState()
    subs.filter(s => s.character_id === charId).forEach(s => {
      const newChar = s.character ? { ...s.character, name: newName } : { id: charId, name: newName, project_id: 0, description: '', color: '', avatar: '', voxcpm_role_id: '', voxcpm_actor_name: '', voxcpm_role_name: '' }
      useStore.getState().updateSubtitle(s.id, { character: newChar })
    })
    setEditingId(null)
  }

  // ── Assign selected ────────────────────────────────────────
  const assign = async (charId: number) => {
    const ids = Array.from(selectedIds); if (!ids.length) return
    await api.post('/subtitles/bulk-assign', { subtitle_ids: ids, character_id: charId })
    const char = characters.find(c => c.id === charId)
    ids.forEach(id => updateSubtitle(id, { character_id: charId, character: char }))
  }

  // ── Remove char ────────────────────────────────────────────
  const removeChar = async (charId: number, e: React.MouseEvent) => {
    e.stopPropagation()
    await api.delete(`/characters/${charId}`)
    setCharacters(characters.filter(c => c.id !== charId))
  }

  // ── Speaker mapping ────────────────────────────────────────
  // Lấy danh sách SPEAKER_XX chưa được map (character không có voxcpm_role_id và tên dạng SPEAKER_)
  const speakerChars = characters.filter(c => c.name.startsWith('SPEAKER_'))
  const realChars    = characters.filter(c => !c.name.startsWith('SPEAKER_'))

  const mapSpeakerToChar = async (speakerCharId: number, targetCharId: number) => {
    // Lấy tất cả subtitle của speaker
    const { subtitles: subs } = useStore.getState()
    const ids = subs.filter(s => s.character_id === speakerCharId).map(s => s.id)
    if (!ids.length) return
    const targetChar = characters.find(c => c.id === targetCharId)
    // Reassign
    await api.post('/subtitles/bulk-assign', { subtitle_ids: ids, character_id: targetCharId })
    ids.forEach(id => updateSubtitle(id, { character_id: targetCharId, character: targetChar }))
    // Xóa speaker char
    await api.delete(`/characters/${speakerCharId}`)
    setCharacters(characters.filter(c => c.id !== speakerCharId))
    setMappingCharId(null)
  }

  // ── Replace character voice ───────────────────────────────
  const replaceChar = async (actor: VoxActor, role: VoxRole, alias: string, color: string) => {
    if (!replacingCharId || !project) return
    const charName = alias || role.character_name || actor.name
    await api.patch(`/characters/${replacingCharId}`, {
      name: charName, color,
      avatar: actor.avatar || '',
      voxcpm_role_id: role.id,
      voxcpm_actor_name: actor.name,
      voxcpm_role_name: role.character_name,
      audio: role.audio || '',
    })
    const updated = characters.map(c => c.id === replacingCharId ? {
      ...c, name: charName, color,
      avatar: actor.avatar || '',
      voxcpm_role_id: role.id,
      voxcpm_actor_name: actor.name,
      voxcpm_role_name: role.character_name,
      audio: role.audio || '',
    } : c)
    setCharacters(updated)
    setReplacingCharId(null)
  }

  // Đếm số dòng mỗi nhân vật
  const charLineCounts = React.useMemo(() => {
    const counts: Record<number, number> = {}
    subtitles.forEach(s => { if (s.character_id) counts[s.character_id] = (counts[s.character_id] || 0) + 1 })
    return counts
  }, [subtitles])

  return (
    <>
      <div className="w-[240px] flex flex-col h-full bg-white dark:bg-zinc-900 border-r border-zinc-200 dark:border-zinc-800 overflow-hidden">

        {/* Header */}
        <div className="flex items-center justify-between px-3 py-2 border-b border-zinc-100 dark:border-zinc-800 flex-shrink-0">
          <span className="panel-label mb-0">Nhân vật</span>
          <div className="flex items-center gap-1">
            <button onClick={() => { setShowPresets(v => !v); loadPresets() }}
              title="Bộ nhân vật đã lưu"
              className={`w-6 h-6 rounded-md flex items-center justify-center text-[11px] transition-colors ${showPresets ? 'bg-violet-100 text-violet-600 dark:bg-violet-950 dark:text-violet-400' : 'text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800'}`}>
              📁
            </button>
            <button onClick={() => setShowPicker(true)}
              className="w-6 h-6 rounded-md flex items-center justify-center text-base leading-none text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800 hover:text-blue-600 transition-colors">
              +
            </button>
          </div>
        </div>

        {/* Preset panel */}
        {showPresets && (
          <div className="border-b border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 flex-shrink-0">
            {characters.length > 0 && (
              <div className="px-2 pt-2 pb-1 flex gap-1">
                <input value={presetName} onChange={e => setPresetName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && savePreset()}
                  placeholder="Tên bộ nhân vật..."
                  className="input text-[11px] flex-1 px-2 py-1"/>
                <button onClick={savePreset} disabled={saving || !presetName.trim()}
                  className="px-2 py-1 rounded-lg bg-violet-600 hover:bg-violet-500 text-white text-[10px] font-semibold disabled:opacity-50 transition-colors flex-shrink-0">
                  {saving ? '...' : 'Lưu'}
                </button>
              </div>
            )}
            <div className="max-h-32 overflow-y-auto px-2 pb-2 space-y-1">
              {presets.length === 0
                ? <p className="text-[11px] text-zinc-400 text-center py-2">Chưa có bộ nào</p>
                : presets.map(p => (
                  <div key={p.id} onClick={() => loadPreset(p.id)}
                    className="flex items-center justify-between px-2 py-1.5 rounded-lg bg-white dark:bg-zinc-700 border border-zinc-200 dark:border-zinc-600 cursor-pointer hover:border-violet-300 hover:bg-violet-50 transition-colors group">
                    <div className="min-w-0">
                      <p className="text-[11px] font-semibold text-zinc-700 dark:text-zinc-200 truncate">{p.name}</p>
                      <p className="text-[9px] text-zinc-400">{p.char_count} nhân vật</p>
                    </div>
                    <button onClick={e => deletePreset(p.id, e)}
                      className="w-4 h-4 rounded-full flex items-center justify-center text-zinc-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all text-[10px] flex-shrink-0">×</button>
                  </div>
                ))}
            </div>
          </div>
        )}

        {/* Character list — scroll sau item thứ 6 */}
        <div className="flex-1 overflow-y-auto p-1.5 space-y-1" style={{minHeight:0}}>
          {characters.length === 0 && (
            <div className="text-center py-8 px-3">
              <div className="text-3xl mb-2">🎙</div>
              <p className="text-[12px] text-zinc-400 leading-relaxed">Bấm <span className="font-bold text-zinc-500">+</span> để chọn nhân vật từ VoiceCast</p>
            </div>
          )}

          {characters.map((c, i) => {
            const lineCount = charLineCounts[c.id] || 0
            const isSpeaker = c.name.startsWith('SPEAKER_')
            const isDragOver = dragOverIdx === i

            return (
              <div key={c.id}
                ref={(el: HTMLDivElement | null) => { activeCardRefs.current[c.id] = el }}
                draggable
                onDragStart={e => onDragStart(e, i, c.id)}
                onDragOver={e => onDragOver(e, i)}
                onDrop={e => onDrop(e, i)}
                onDragEnd={onDragEnd}
                onClick={() => assign(c.id)}
                className={`rounded-lg border cursor-pointer active:scale-[0.98] transition-all group relative select-none overflow-hidden
                  ${isDragOver ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/30'
                    : activeCharId !== c.id ? 'border-zinc-100 dark:border-zinc-800 bg-white dark:bg-zinc-800/50 hover:border-zinc-300 dark:hover:border-zinc-600'
                    : ''}
                  
                `}
                style={{
                  height: 150,
                  flexShrink: 0,
                  ...(activeCharId === c.id ? {
                    borderWidth: 2,
                    borderColor: '#f97316',
                    boxShadow: '0 0 0 3px rgba(249,115,22,0.25)',
                    background: 'rgba(249,115,22,0.05)',
                  } : {})
                }}>


                {/* Main row: avatar LEFT | info RIGHT */}
                <div className="flex gap-2 p-2">
                  <div className="flex-shrink-0 cursor-grab active:cursor-grabbing" title="Kéo để sắp xếp">
                    {c.avatar
                      ? <img src={c.avatar} className="w-16 h-[118px] rounded-lg object-cover object-top"/>
                      : <div className="w-16 h-[118px] rounded-lg flex items-center justify-center text-[18px] font-bold"
                          style={{ background: c.color + '25', color: c.color }}>
                          {c.name.slice(0,2).toUpperCase()}
                        </div>
                    }
                  </div>

                  <div className="flex-1 min-w-0 flex flex-col">
                    <div className="w-full">
                      {editingId === c.id ? (
                        <input value={editingName}
                          onChange={e => setEditingName(e.target.value)}
                          onBlur={() => saveCharName(c.id)}
                          onKeyDown={e => { if (e.key==='Enter') saveCharName(c.id); if (e.key==='Escape') setEditingId(null) }}
                          onClick={e => e.stopPropagation()}
                          autoFocus
                          className="text-[13px] font-semibold w-full bg-transparent border-b outline-none"
                          style={{ color: c.color, borderColor: c.color }}/>
                      ) : (
                        <p className="text-[13px] font-semibold leading-snug flex items-center gap-1" style={{ color: c.color }}>
                          <span onClick={e => { e.stopPropagation(); setEditingId(c.id); setEditingName(c.name) }}
                            className="cursor-text hover:underline">{c.name}</span>
                          {isSpeaker && <span className="text-[9px] text-amber-500 font-normal">AI</span>}
                          {!isSpeaker && (
                            <span onClick={e => { e.stopPropagation(); setEditingId(c.id); setEditingName(c.name) }}
                              className="text-zinc-300 hover:text-zinc-500 cursor-pointer text-[11px]" title="Sửa tên">✏️</span>
                          )}
                        </p>
                      )}
                    </div>

                    <div className="flex items-center gap-1 mt-1">
                      <span className="text-[10px] text-zinc-400">Phím</span>
                      <span className="font-black text-[14px]" style={{color: c.color}}>{i+1}</span>
                      <span className="text-[10px] text-zinc-400">· {lineCount}d</span>
                      <div className="ml-auto">
                        {c.voxcpm_role_id && (
                          <span className="text-[9px] px-1 py-0.5 rounded bg-blue-50 dark:bg-blue-950 text-blue-500 font-medium">VoxCPM</span>
                        )}
                      </div>
                    </div>
                    {/* Inline action buttons ở vùng trống */}
                    <div className="flex items-center gap-1 mt-1.5">
                      {isSpeaker ? (
                        <button onClick={e => { e.stopPropagation(); setMappingCharId(c.id) }}
                          className="flex-1 py-0.5 rounded text-[10px] font-semibold bg-amber-50 dark:bg-amber-950 border border-amber-300 dark:border-amber-700 text-amber-600 hover:bg-amber-100 transition-colors">
                          Gán NV
                        </button>
                      ) : (
                        <button onClick={e => { e.stopPropagation(); setReplacingCharId(c.id) }}
                          className="flex-1 py-0.5 rounded text-[10px] font-semibold bg-blue-50 dark:bg-blue-950 border border-blue-200 dark:border-blue-800 text-blue-600 hover:bg-blue-100 transition-colors">
                          Đổi NV
                        </button>
                      )}
                      <button onClick={e => removeChar(c.id, e)}
                        className="flex-1 py-0.5 rounded text-[10px] font-semibold bg-zinc-50 dark:bg-zinc-700 border border-zinc-200 dark:border-zinc-600 text-zinc-400 hover:text-red-500 hover:border-red-300 transition-colors">
                        Xóa
                      </button>
                    </div>

                    {c.audio && (
                      <button onClick={e => {
                        e.stopPropagation()
                        if (playingAudio === c.audio) {
                          _sidebarAudio?.pause(); _sidebarAudio = null; setPlayingAudio(null)
                        } else {
                          if (_sidebarAudio) { _sidebarAudio.pause(); _sidebarAudio = null }
                          const a = new Audio(`http://localhost:8809${c.audio}`)
                          _sidebarAudio = a; a.play().catch(()=>{})
                          a.onended = () => { _sidebarAudio = null; setPlayingAudio(null) }
                          setPlayingAudio(c.audio!)
                        }
                      }}
                        className="mt-auto w-full flex items-center justify-center gap-1 py-1 rounded text-[10px] font-medium transition-colors border"
                        style={{
                          color: playingAudio===c.audio ? '#10B981' : '#9CA3AF',
                          background: playingAudio===c.audio ? '#ECFDF5' : 'transparent',
                          borderColor: playingAudio===c.audio ? '#6EE7B7' : '#E5E7EB',
                        }}>
                        {playingAudio===c.audio
                          ? <><svg width="9" height="9" viewBox="0 0 10 10" fill="currentColor"><rect x="1" y="1" width="3" height="8" rx="0.5"/><rect x="6" y="1" width="3" height="8" rx="0.5"/></svg> Đang phát</>
                          : <><svg width="9" height="9" viewBox="0 0 12 12" fill="none"><path d="M2 1.5L10 6L2 10.5V1.5Z" fill="currentColor"/></svg> Nghe mẫu</>
                        }
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* Footer tips */}
        <div className="px-3 py-2 border-t border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/30 text-[10px] text-zinc-400 leading-relaxed flex-shrink-0">
          <p>Kéo thả để sắp xếp · Kéo vào dòng phụ đề</p>
          <p>Shift+click chọn nhiều · Phím <span className="font-semibold text-zinc-500">1–9</span> gán nhanh</p>
        </div>
      </div>

      {/* Speaker → Char mapping modal */}
      {mappingCharId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
          onClick={() => setMappingCharId(null)}>
          <div className="bg-white dark:bg-zinc-900 rounded-xl border border-zinc-200 dark:border-zinc-700 p-4 w-72 shadow-xl"
            onClick={e => e.stopPropagation()}>
            <p className="text-[13px] font-semibold text-zinc-800 dark:text-zinc-200 mb-1">
              Gán {characters.find(c => c.id === mappingCharId)?.name} vào nhân vật
            </p>
            <p className="text-[11px] text-zinc-400 mb-3">
              Tất cả dòng phụ đề sẽ được chuyển sang nhân vật được chọn
            </p>
            <div className="space-y-1.5">
              {realChars.map(rc => (
                <button key={rc.id}
                  onClick={() => mappingCharId && mapSpeakerToChar(mappingCharId, rc.id)}
                  className="w-full flex items-center gap-2.5 px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 hover:border-zinc-300 dark:hover:border-zinc-500 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors text-left">
                  {rc.avatar
                    ? <img src={rc.avatar} className="w-7 h-7 rounded-full object-cover flex-shrink-0"/>
                    : <div className="w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0"
                        style={{ background: rc.color+'20', color: rc.color }}>
                        {rc.name.slice(0,2).toUpperCase()}
                      </div>
                  }
                  <div className="min-w-0">
                    <p className="text-[12px] font-semibold truncate" style={{ color: rc.color }}>{rc.name}</p>
                    {rc.voxcpm_role_name && <p className="text-[10px] text-zinc-400 truncate">{rc.voxcpm_role_name}</p>}
                  </div>
                  <span className="ml-auto text-[10px] text-zinc-400">{charLineCounts[rc.id]||0}d</span>
                </button>
              ))}
              {realChars.length === 0 && (
                <p className="text-[12px] text-zinc-400 text-center py-3">
                  Chưa có nhân vật thật. Thêm nhân vật bằng nút <b>+</b> trước.
                </p>
              )}
            </div>
            <button onClick={() => setMappingCharId(null)}
              className="mt-3 w-full py-1.5 text-[12px] text-zinc-500 hover:text-zinc-700 transition-colors">
              Huỷ
            </button>
          </div>
        </div>
      )}

      {showPicker && (
        <VoicePicker onSelect={handleSelect} onClose={() => setShowPicker(false)}/>
      )}
      {replacingCharId !== null && (
        <VoicePicker onSelect={replaceChar} onClose={() => setReplacingCharId(null)}/>
      )}
    </>
  )
}