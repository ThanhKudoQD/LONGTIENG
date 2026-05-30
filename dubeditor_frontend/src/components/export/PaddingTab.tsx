/**
 * PaddingTab — thêm thanh màu trên/dưới video (vùng để phụ đề hoặc logo).
 */
import React from 'react'
import { PaddingConfig, PaddingSide } from './types'

interface Props {
  padding: PaddingConfig
  onChange: (padding: PaddingConfig) => void
}

export default function PaddingTab({ padding, onChange }: Props) {
  const updateSide = (side: 'top' | 'bottom', patch: Partial<PaddingSide>) => {
    onChange({ ...padding, [side]: { ...padding[side], ...patch } })
  }

  return (
    <div className="max-w-3xl space-y-5">
      <div className="text-[12.5px] text-zinc-600 dark:text-zinc-400 leading-relaxed">
        Thêm thanh màu trên/dưới video. Thường dùng cho TikTok/Shorts:
        thanh dưới chứa phụ đề lớn, thanh trên có logo/tên kênh.
      </div>

      <SideEditor label="Padding TRÊN ↑" side={padding.top}
        onChange={p => updateSide('top', p)} />

      <SideEditor label="Padding DƯỚI ↓" side={padding.bottom}
        onChange={p => updateSide('bottom', p)} />

      {/* Preview ASCII layout */}
      <div className="surface-card p-4">
        <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-medium mb-3">Sơ đồ layout output</div>
        <div className="bg-zinc-100 dark:bg-zinc-900 rounded overflow-hidden border border-zinc-200 dark:border-zinc-700"
          style={{ aspectRatio: '16/9', maxWidth: 400 }}>
          {padding.top.enabled && (
            <div style={{ height: `${Math.min(30, padding.top.height_px / 8)}%`, background: padding.top.color }}
              className="flex items-center justify-center text-[10px] text-white/70">
              padding {padding.top.height_px}px
            </div>
          )}
          <div className="flex-1 bg-gradient-to-br from-zinc-300 to-zinc-400 dark:from-zinc-700 dark:to-zinc-800 flex items-center justify-center text-[11px] text-zinc-500"
            style={{ height: `${100 - (padding.top.enabled ? Math.min(30, padding.top.height_px / 8) : 0) - (padding.bottom.enabled ? Math.min(30, padding.bottom.height_px / 8) : 0)}%` }}>
            VIDEO GỐC
          </div>
          {padding.bottom.enabled && (
            <div style={{ height: `${Math.min(30, padding.bottom.height_px / 8)}%`, background: padding.bottom.color }}
              className="flex items-center justify-center text-[10px] text-white/70">
              padding {padding.bottom.height_px}px
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function SideEditor({ label, side, onChange }: { label: string; side: PaddingSide; onChange: (p: Partial<PaddingSide>) => void }) {
  return (
    <div className="surface-card p-4">
      <label className="flex items-center gap-2 mb-3 cursor-pointer">
        <input type="checkbox" checked={side.enabled}
          onChange={e => onChange({ enabled: e.target.checked })} className="w-4 h-4" />
        <span className="text-[13px] font-semibold">{label}</span>
      </label>

      {side.enabled && (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-[11px] text-zinc-500 mb-1.5 uppercase tracking-wider font-medium">
              Chiều cao: {side.height_px}px
            </label>
            <input type="range" min={20} max={500} value={side.height_px}
              onChange={e => onChange({ height_px: parseInt(e.target.value) })} className="w-full" />
            <input type="number" min={20} max={500} value={side.height_px}
              onChange={e => onChange({ height_px: parseInt(e.target.value) || 100 })}
              className="input w-24 text-[13px] mt-1" />
          </div>
          <div>
            <label className="block text-[11px] text-zinc-500 mb-1.5 uppercase tracking-wider font-medium">Màu</label>
            <div className="flex items-center gap-2">
              <input type="color" value={side.color}
                onChange={e => onChange({ color: e.target.value })}
                className="w-10 h-9 rounded border border-zinc-200 dark:border-zinc-700 cursor-pointer" />
              <input type="text" value={side.color}
                onChange={e => onChange({ color: e.target.value })}
                className="input flex-1 text-[12px] font-mono" />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
