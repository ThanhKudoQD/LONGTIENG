/**
 * CutTab — chi tiết các khoảng cắt + hướng dẫn.
 *
 * Lưu ý: thao tác cắt CHÍNH thực hiện trên MultiTrackTimeline DƯỚI preview.
 * Tab này chỉ list chi tiết + edit chính xác bằng số.
 */
import React from 'react'
import { VideoClip } from './types'

interface Props {
  clips: VideoClip[]
  videoDuration: number
  onChange: (clips: VideoClip[]) => void
}

function fmtTime(s: number): string {
  if (!isFinite(s) || s < 0) return '0:00'
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = Math.floor(s % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  return `${m}:${String(sec).padStart(2, '0')}`
}

function parseTime(str: string): number {
  const parts = str.split(':').map(p => parseInt(p.trim()) || 0)
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
  if (parts.length === 2) return parts[0] * 60 + parts[1]
  return parts[0] || 0
}

export default function CutTab({ clips, videoDuration, onChange }: Props) {
  const totalKeep = clips.reduce((s, c) => s + Math.max(0, c.source_end - c.source_start), 0)

  const updateClip = (id: string, p: Partial<VideoClip>) => {
    onChange(clips.map(c => c.id === id ? { ...c, ...p } : c))
  }

  return (
    <div className="max-w-3xl space-y-5">
      <div>
        <h3 className="text-[14px] font-semibold text-zinc-900 dark:text-zinc-100">Cắt video</h3>
        <p className="text-[12px] text-zinc-500 mt-0.5 leading-relaxed">
          Cắt và chỉnh trực quan trên <b>Timeline DƯỚI</b>: Shift+drag để tạo · drag cạnh xanh để chỉnh start/end · double-click block để nhập time chính xác.<br />
          Tab này dùng để edit chính xác bằng số nếu cần.
        </p>
      </div>

      {clips.length === 0 ? (
        <div className="text-center py-10 border border-dashed border-zinc-300 dark:border-zinc-700 rounded-lg">
          <div className="text-4xl mb-2">✂</div>
          <div className="text-[13px] text-zinc-500">
            Chưa có khoảng nào — sẽ export TOÀN BỘ video.
          </div>
          <div className="text-[11px] text-zinc-400 mt-2">
            💡 Vào Timeline DƯỚI, Shift+drag trên track Video để tạo khoảng giữ.
          </div>
        </div>
      ) : (
        <div className="space-y-2">
          {clips.map((c, i) => (
            <div key={c.id} className="surface-card p-3">
              <div className="flex items-center gap-2">
                <span className="font-mono text-[11px] text-zinc-400 w-6">{i + 1}</span>
                <input
                  type="text"
                  value={c.label || ''}
                  onChange={e => updateClip(c.id, { label: e.target.value })}
                  placeholder={`Đoạn ${i + 1}`}
                  className="flex-1 px-2 py-1 text-[12.5px] border border-zinc-200 dark:border-zinc-700 rounded bg-white dark:bg-zinc-950"
                />
                <span className="text-[11px] text-zinc-500">Từ</span>
                <input
                  type="text"
                  defaultValue={fmtTime(c.source_start)}
                  key={`start-${c.source_start}`}
                  onBlur={e => updateClip(c.id, { source_start: parseTime(e.target.value) })}
                  className="w-20 px-2 py-1 text-[12.5px] font-mono border border-zinc-200 dark:border-zinc-700 rounded bg-white dark:bg-zinc-950 text-center"
                />
                <span className="text-[11px] text-zinc-500">→</span>
                <input
                  type="text"
                  defaultValue={fmtTime(c.source_end)}
                  key={`end-${c.source_end}`}
                  onBlur={e => updateClip(c.id, { source_end: parseTime(e.target.value) })}
                  className="w-20 px-2 py-1 text-[12.5px] font-mono border border-zinc-200 dark:border-zinc-700 rounded bg-white dark:bg-zinc-950 text-center"
                />
                <span className="text-[10px] font-mono text-zinc-400 w-14 text-right">
                  ({fmtTime(c.source_end - c.source_start)})
                </span>
                <button onClick={() => onChange(clips.filter(x => x.id !== c.id))}
                  className="text-[11px] px-1.5 py-1 hover:bg-red-50 hover:text-red-700 rounded">🗑</button>
              </div>
            </div>
          ))}
        </div>
      )}

      {videoDuration > 0 && (
        <div className="surface-card p-3 flex items-center gap-4 text-[12px]">
          <span className="text-zinc-500">📊 Tổng:</span>
          <span><b>{clips.length}</b> đoạn</span>
          <span className="text-zinc-300">·</span>
          <span>Output: <b className="font-mono text-emerald-700 dark:text-emerald-500">{fmtTime(totalKeep || videoDuration)}</b></span>
          <span className="text-zinc-300">·</span>
          <span className="text-zinc-500">Video gốc: <span className="font-mono">{fmtTime(videoDuration)}</span></span>
        </div>
      )}
    </div>
  )
}
