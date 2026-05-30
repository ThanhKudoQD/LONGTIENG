/**
 * PresetDialog — modal save/load/manage export presets.
 *
 * v4.0: wire BE thật (CRUD qua /api/export_video/presets).
 * localStorage fallback đã loại bỏ.
 */
import React, { useState, useEffect } from 'react'
import { ExportConfig, ExportPreset } from './types'
import { listPresets, createPreset, deletePresetApi } from './exportApi'

interface Props {
  mode: 'save' | 'manage'
  currentConfig: ExportConfig
  onClose: () => void
  onApply?: (preset: ExportPreset) => void
  onSaved?: (preset: ExportPreset) => void
}

export default function PresetDialog({ mode, currentConfig, onClose, onApply, onSaved }: Props) {
  const [presets, setPresets] = useState<ExportPreset[]>([])
  const [newName, setNewName] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [selectedSections, setSelectedSections] = useState({
    subtitle_style: true,
    padding: true,
    watermarks: true,
    audio: true,
    output: true,
    clips: false,
  })

  useEffect(() => {
    listPresets().then(setPresets).catch(e => {
      setErr('Không tải được danh sách preset')
      console.error(e)
    })
  }, [])

  const handleSave = async () => {
    const name = newName.trim()
    if (!name) {
      setErr('Vui lòng nhập tên preset')
      return
    }
    if (presets.some(p => p.name === name)) {
      if (!confirm(`Preset "${name}" đã tồn tại. Ghi đè?`)) return
    }

    // Build config theo section đã tick
    const partial: any = {}
    if (selectedSections.subtitle_style) partial.subtitle_style = currentConfig.subtitle_style
    if (selectedSections.padding)        partial.padding = currentConfig.padding
    if (selectedSections.watermarks)     partial.watermarks = currentConfig.watermarks
    if (selectedSections.audio)          partial.audio = currentConfig.audio
    if (selectedSections.output)         partial.output = currentConfig.output
    if (selectedSections.clips)          partial.clips = currentConfig.clips

    setLoading(true)
    setErr(null)
    try {
      const saved = await createPreset(name, partial)
      onSaved?.(saved)
      onClose()
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Lưu thất bại')
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id: number) => {
    const p = presets.find(x => x.id === id)
    if (!p) return
    if (!confirm(`Xóa preset "${p.name}"?`)) return
    try {
      await deletePresetApi(id)
      setPresets(prev => prev.filter(x => x.id !== id))
    } catch (e: any) {
      alert('Xóa thất bại: ' + (e?.message || ''))
    }
  }

  const handleApply = (preset: ExportPreset) => {
    onApply?.(preset)
    onClose()
  }

  const sectionCount = (preset: ExportPreset): string => {
    const keys = Object.keys(preset.config || {})
    return `${keys.length} mục`
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[100]" onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-lg max-w-lg w-full mx-4 shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">
            {mode === 'save' ? '💾 Lưu preset mới' : '📦 Quản lý preset'}
          </h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 text-[18px] leading-none w-7 h-7 flex items-center justify-center rounded hover:bg-zinc-100 dark:hover:bg-zinc-800">✕</button>
        </div>

        <div className="px-5 py-4 max-h-[70vh] overflow-y-auto">
          {err && (
            <div className="mb-3 text-[12px] text-red-700 bg-red-50 dark:bg-red-950/30 rounded p-2">{err}</div>
          )}

          {mode === 'save' ? (
            <div className="space-y-4">
              <div>
                <label className="block text-[12px] font-medium mb-1.5">Tên preset</label>
                <input
                  type="text" value={newName} autoFocus disabled={loading}
                  onChange={e => setNewName(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && handleSave()}
                  placeholder="vd: TikTok Style, YouTube Long..."
                  className="input w-full text-[13px]"
                />
              </div>
              <div>
                <label className="block text-[12px] font-medium mb-1.5">Lưu những phần nào</label>
                <div className="space-y-1.5">
                  {[
                    { key: 'subtitle_style' as const, label: 'Phụ đề (font, màu, vị trí)' },
                    { key: 'padding' as const, label: 'Padding (thanh trên/dưới)' },
                    { key: 'watermarks' as const, label: `Watermark (${currentConfig.watermarks.length} mục)` },
                    { key: 'audio' as const, label: `Audio + BGM (${currentConfig.audio.tracks.length} track)` },
                    { key: 'output' as const, label: 'Output (tỉ lệ, resolution, codec)' },
                    { key: 'clips' as const, label: `Clips cắt (${currentConfig.clips.length} đoạn) — thường KHÔNG nên lưu` },
                  ].map(s => (
                    <label key={s.key} className="flex items-center gap-2 text-[12.5px] cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800 px-2 py-1 rounded">
                      <input type="checkbox" checked={selectedSections[s.key]}
                        onChange={e => setSelectedSections(prev => ({ ...prev, [s.key]: e.target.checked }))}
                        className="w-4 h-4" />
                      <span>{s.label}</span>
                    </label>
                  ))}
                </div>
              </div>
              <div className="text-[11px] text-zinc-500 leading-relaxed bg-zinc-50 dark:bg-zinc-800/40 rounded p-2.5">
                💡 Preset lưu trên server, dùng được giữa tất cả project. Clips không nên
                lưu vì khác phim có cấu trúc khác nhau.
              </div>
            </div>
          ) : (
            <div className="space-y-2">
              {presets.length === 0 ? (
                <div className="text-center py-10 text-[13px] text-zinc-500">
                  Chưa có preset nào.
                  <div className="text-[11px] mt-1">Đóng dialog → bấm "💾 Lưu preset" để tạo.</div>
                </div>
              ) : (
                presets.map(p => (
                  <div key={p.id} className="flex items-center gap-3 p-2.5 border border-zinc-200 dark:border-zinc-800 rounded hover:bg-zinc-50 dark:hover:bg-zinc-800/50">
                    <div className="flex-1 min-w-0">
                      <div className="text-[13px] font-medium truncate">{p.name}</div>
                      <div className="text-[10.5px] text-zinc-500">
                        {sectionCount(p)} {p.created_at && ` · ${new Date(p.created_at).toLocaleString()}`}
                      </div>
                    </div>
                    <button onClick={() => handleApply(p)} className="btn btn-primary text-[11.5px]">↓ Apply</button>
                    <button onClick={() => handleDelete(p.id)}
                      className="text-[11px] text-red-600 hover:text-red-700 px-2 py-1 rounded hover:bg-red-50 dark:hover:bg-red-950">🗑</button>
                  </div>
                ))
              )}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-zinc-200 dark:border-zinc-800 flex justify-end gap-2">
          <button onClick={onClose} className="btn text-[12px]">Hủy</button>
          {mode === 'save' && (
            <button onClick={handleSave} disabled={loading} className="btn btn-primary text-[12px]">
              {loading ? '⏳ Đang lưu...' : '💾 Lưu'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
