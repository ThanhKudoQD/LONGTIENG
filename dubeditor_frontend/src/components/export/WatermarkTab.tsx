/**
 * WatermarkTab — danh sách watermark (text/ảnh), thêm/xóa/chỉnh.
 */
import React, { useState } from 'react'
import { Watermark, WatermarkText, WatermarkImage, WATERMARK_POSITIONS, FONT_FAMILIES } from './types'
import { uploadAsset } from './exportApi'

interface Props {
  watermarks: Watermark[]
  projectId: number
  onChange: (wms: Watermark[]) => void
}

function genId() { return Math.random().toString(36).slice(2, 10) }

export default function WatermarkTab({ watermarks, projectId, onChange }: Props) {
  const addText = () => {
    const wm: WatermarkText = {
      id: genId(), type: 'text',
      text: '@YourChannel', font_family: 'Be Vietnam Pro', font_size: 24,
      color: '#FFFFFF', opacity: 0.8,
      position: 'top_right', x_offset: 20, y_offset: 20,
      start_time: 0, duration: null,
    }
    onChange([...watermarks, wm])
  }

  const addImage = () => {
    const wm: WatermarkImage = {
      id: genId(), type: 'image',
      image_path: '', image_url: '',
      width_px: 120, opacity: 0.8,
      position: 'bottom_right', x_offset: 20, y_offset: 20,
      start_time: 0, duration: null,
    }
    onChange([...watermarks, wm])
  }

  const updateWm = (id: string, patch: Partial<Watermark>) => {
    onChange(watermarks.map(w => w.id === id ? ({ ...w, ...patch } as Watermark) : w))
  }

  const removeWm = (id: string) => {
    onChange(watermarks.filter(w => w.id !== id))
  }

  return (
    <div className="max-w-3xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-[14px] font-semibold">Watermark</h3>
          <p className="text-[12px] text-zinc-500">Thêm text hoặc logo chèn vào video. Có thể thêm nhiều.</p>
        </div>
        <div className="flex gap-2">
          <button onClick={addText} className="btn text-[12px]">+ Text</button>
          <button onClick={addImage} className="btn text-[12px]">+ Ảnh</button>
        </div>
      </div>

      {watermarks.length === 0 ? (
        <div className="text-center py-10 border border-dashed border-zinc-300 dark:border-zinc-700 rounded-lg">
          <div className="text-3xl mb-2">©</div>
          <div className="text-[13px] text-zinc-500">Chưa có watermark. Bấm "+ Text" hoặc "+ Ảnh" để thêm.</div>
        </div>
      ) : (
        <div className="space-y-3">
          {watermarks.map((wm, i) => (
            <div key={wm.id} className="surface-card p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="text-[12px] font-semibold text-zinc-500 uppercase tracking-wider">
                  #{i + 1} · {wm.type === 'text' ? 'Text' : 'Ảnh'}
                </div>
                <button onClick={() => removeWm(wm.id)}
                  className="text-[11px] text-red-600 hover:text-red-700">🗑 Xóa</button>
              </div>

              {wm.type === 'text' ? (
                <TextEditor wm={wm} onChange={p => updateWm(wm.id, p)} />
              ) : (
                <ImageEditor wm={wm} projectId={projectId} onChange={p => updateWm(wm.id, p)} />
              )}

              <PositionTimingEditor wm={wm} onChange={p => updateWm(wm.id, p)} />
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Text editor ───────────────────────────────────────────────────────────

function TextEditor({ wm, onChange }: { wm: WatermarkText; onChange: (p: Partial<WatermarkText>) => void }) {
  return (
    <div className="grid grid-cols-2 gap-3 mb-3">
      <div className="col-span-2">
        <Label>Nội dung</Label>
        <input type="text" value={wm.text}
          onChange={e => onChange({ text: e.target.value })}
          className="input w-full text-[13px]" placeholder="@YourChannel" />
      </div>
      <div>
        <Label>Font</Label>
        <select value={wm.font_family}
          onChange={e => onChange({ font_family: e.target.value })}
          className="input w-full text-[13px]">
          {FONT_FAMILIES.map(f => <option key={f} value={f}>{f}</option>)}
        </select>
      </div>
      <div>
        <Label>Cỡ chữ: {wm.font_size}px</Label>
        <input type="range" min={10} max={80} value={wm.font_size}
          onChange={e => onChange({ font_size: parseInt(e.target.value) })} className="w-full" />
      </div>
      <div>
        <Label>Màu</Label>
        <div className="flex gap-2">
          <input type="color" value={wm.color}
            onChange={e => onChange({ color: e.target.value })}
            className="w-10 h-9 rounded border border-zinc-200 dark:border-zinc-700" />
          <input type="text" value={wm.color}
            onChange={e => onChange({ color: e.target.value })}
            className="input flex-1 text-[12px] font-mono" />
        </div>
      </div>
      <div>
        <Label>Opacity: {Math.round(wm.opacity * 100)}%</Label>
        <input type="range" min={0} max={1} step={0.05} value={wm.opacity}
          onChange={e => onChange({ opacity: parseFloat(e.target.value) })} className="w-full" />
      </div>
    </div>
  )
}

// ─── Image editor ──────────────────────────────────────────────────────────

function ImageEditor({ wm, projectId, onChange }: { wm: WatermarkImage; projectId: number; onChange: (p: Partial<WatermarkImage>) => void }) {
  const [uploading, setUploading] = useState(false)
  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    if (!f) return
    e.target.value = ''
    setUploading(true)
    try {
      const r = await uploadAsset(projectId, f, 'image')
      onChange({ image_path: r.url, image_url: r.url })
    } catch (err: any) {
      alert('Upload thất bại: ' + (err?.response?.data?.detail || err?.message || ''))
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="grid grid-cols-2 gap-3 mb-3">
      <div className="col-span-2">
        <Label>File ảnh (PNG có alpha tốt nhất)</Label>
        <div className="flex items-center gap-3">
          {wm.image_url && (
            <img src={wm.image_url} alt="logo"
              className="w-14 h-14 object-contain border border-zinc-200 dark:border-zinc-700 rounded bg-zinc-50 dark:bg-zinc-900" />
          )}
          <label className={`btn text-[12px] cursor-pointer ${uploading ? 'opacity-60 pointer-events-none' : ''}`}>
            {uploading ? '⏳ Đang upload...' : '📁 Chọn file'}
            <input type="file" accept="image/*" onChange={handleUpload} disabled={uploading} className="hidden" />
          </label>
          {wm.image_path && <span className="text-[11px] text-zinc-500 truncate">{wm.image_path.split('/').pop()}</span>}
        </div>
      </div>
      <div>
        <Label>Chiều rộng: {wm.width_px}px</Label>
        <input type="range" min={40} max={400} value={wm.width_px}
          onChange={e => onChange({ width_px: parseInt(e.target.value) })} className="w-full" />
      </div>
      <div>
        <Label>Opacity: {Math.round(wm.opacity * 100)}%</Label>
        <input type="range" min={0} max={1} step={0.05} value={wm.opacity}
          onChange={e => onChange({ opacity: parseFloat(e.target.value) })} className="w-full" />
      </div>
    </div>
  )
}

// ─── Position + Timing (chung) ─────────────────────────────────────────────

function PositionTimingEditor({ wm, onChange }: { wm: Watermark; onChange: (p: Partial<Watermark>) => void }) {
  return (
    <div className="border-t border-zinc-200 dark:border-zinc-800 pt-3 mt-2 grid grid-cols-3 gap-3">
      <div>
        <Label>Vị trí</Label>
        <select value={wm.position}
          onChange={e => onChange({ position: e.target.value as any })}
          className="input w-full text-[12px]">
          {WATERMARK_POSITIONS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
        </select>
      </div>
      <div>
        <Label>Offset X: {wm.x_offset}px</Label>
        <input type="range" min={-100} max={200} value={wm.x_offset}
          onChange={e => onChange({ x_offset: parseInt(e.target.value) })} className="w-full" />
      </div>
      <div>
        <Label>Offset Y: {wm.y_offset}px</Label>
        <input type="range" min={-100} max={200} value={wm.y_offset}
          onChange={e => onChange({ y_offset: parseInt(e.target.value) })} className="w-full" />
      </div>
      <div>
        <Label>Bắt đầu (giây)</Label>
        <input type="number" min={0} value={wm.start_time}
          onChange={e => onChange({ start_time: parseFloat(e.target.value) || 0 })}
          className="input w-full text-[12px]" />
      </div>
      <div className="col-span-2">
        <Label>Thời lượng hiển thị</Label>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1 text-[12px]">
            <input type="checkbox" checked={wm.duration === null}
              onChange={e => onChange({ duration: e.target.checked ? null : 10 })} className="w-4 h-4" />
            Suốt video
          </label>
          {wm.duration !== null && (
            <input type="number" min={0.5} step={0.5} value={wm.duration || 0}
              onChange={e => onChange({ duration: parseFloat(e.target.value) || 1 })}
              className="input w-24 text-[12px]" placeholder="giây" />
          )}
        </div>
      </div>
    </div>
  )
}

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-[10px] text-zinc-500 mb-1 uppercase tracking-wider font-medium">{children}</label>
}
