/**
 * TimelineEditor — thanh thời gian video gốc với block "khoảng giữ".
 *
 * Tương tác:
 *   - Click vào empty area → tạo block mới ở vị trí click (start = click pos, len = 5s)
 *   - Drag handle TRÁI của block → chỉnh start
 *   - Drag handle PHẢI của block → chỉnh end
 *   - Drag GIỮA block → di chuyển nguyên block
 *   - Double-click block → mở popup nhập time chính xác
 *   - Click block → highlight + hiện nút X xóa
 *
 * Bonus: hiển thị thumbnail strip (10 frame đều) dùng <video> currentTime capture.
 */
import React, { useRef, useState, useEffect, useCallback } from 'react'
import { VideoClip } from './types'

interface Props {
  videoUrl: string | null
  videoDuration: number       // giây
  clips: VideoClip[]
  onChange: (clips: VideoClip[]) => void
  // Khi user scrub timeline (chưa drag clip) — báo cho preview pause ở time đó
  onScrub?: (time: number) => void
  currentTime?: number        // vị trí scrubber (để hiển thị marker)
}

type DragState =
  | { type: 'create'; startX: number; startTime: number; id: string }
  | { type: 'move'; id: string; startX: number; origStart: number; origEnd: number }
  | { type: 'resize-left'; id: string; startX: number; origStart: number }
  | { type: 'resize-right'; id: string; startX: number; origEnd: number }
  | { type: 'scrub' }
  | null

function genId() { return Math.random().toString(36).slice(2, 10) }

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
  if (parts.length === 1) return parts[0]
  return 0
}

const TIMELINE_HEIGHT = 64
const CLIP_HEIGHT = 36

export default function TimelineEditor({
  videoUrl, videoDuration, clips, onChange, onScrub, currentTime = 0,
}: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<DragState>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editing, setEditing] = useState<string | null>(null)
  const [hoverTime, setHoverTime] = useState<number | null>(null)
  const [thumbs, setThumbs] = useState<string[]>([])

  // ─── Helpers chuyển px ↔ time ────────────────────────────────────────────
  const pxToTime = useCallback((px: number): number => {
    const rect = trackRef.current?.getBoundingClientRect()
    if (!rect || rect.width === 0 || videoDuration === 0) return 0
    const ratio = Math.max(0, Math.min(1, px / rect.width))
    return ratio * videoDuration
  }, [videoDuration])

  const timeToPercent = useCallback((t: number): number => {
    if (videoDuration === 0) return 0
    return Math.max(0, Math.min(100, (t / videoDuration) * 100))
  }, [videoDuration])

  // ─── Generate thumbnails strip ──────────────────────────────────────────
  useEffect(() => {
    if (!videoUrl || videoDuration === 0) {
      setThumbs([])
      return
    }
    let cancelled = false
    const COUNT = 10
    const video = document.createElement('video')
    video.crossOrigin = 'anonymous'
    video.src = videoUrl
    video.muted = true
    video.preload = 'metadata'

    const canvas = document.createElement('canvas')
    canvas.width = 160
    canvas.height = 90
    const ctx = canvas.getContext('2d')!

    const result: string[] = []
    let idx = 0

    const grabNext = () => {
      if (cancelled || idx >= COUNT) {
        if (!cancelled) setThumbs(result)
        return
      }
      const t = (idx / COUNT) * videoDuration
      video.currentTime = t
    }

    video.addEventListener('loadedmetadata', () => {
      grabNext()
    })
    video.addEventListener('seeked', () => {
      if (cancelled) return
      try {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
        result.push(canvas.toDataURL('image/jpeg', 0.6))
        idx++
        grabNext()
      } catch (e) {
        // CORS hoặc lỗi decode — skip
        idx++
        grabNext()
      }
    })
    video.addEventListener('error', () => {
      // Không gen được thumb — silent fail
      setThumbs([])
    })

    return () => {
      cancelled = true
      video.removeEventListener('loadedmetadata', grabNext)
    }
  }, [videoUrl, videoDuration])

  // ─── Drag handlers ──────────────────────────────────────────────────────
  useEffect(() => {
    if (!drag) return

    const onMove = (e: MouseEvent) => {
      const rect = trackRef.current?.getBoundingClientRect()
      if (!rect) return

      if (drag.type === 'create') {
        const curTime = pxToTime(e.clientX - rect.left)
        const start = Math.min(drag.startTime, curTime)
        const end = Math.max(drag.startTime, curTime)
        onChange(clips.map(c => c.id === drag.id ? { ...c, source_start: start, source_end: end } : c))
      } else if (drag.type === 'move') {
        const dx = e.clientX - drag.startX
        const dtSec = (dx / rect.width) * videoDuration
        const len = drag.origEnd - drag.origStart
        let newStart = drag.origStart + dtSec
        newStart = Math.max(0, Math.min(videoDuration - len, newStart))
        onChange(clips.map(c => c.id === drag.id ? { ...c, source_start: newStart, source_end: newStart + len } : c))
      } else if (drag.type === 'resize-left') {
        const t = pxToTime(e.clientX - rect.left)
        onChange(clips.map(c => {
          if (c.id !== drag.id) return c
          const newStart = Math.max(0, Math.min(c.source_end - 0.5, t))
          return { ...c, source_start: newStart }
        }))
      } else if (drag.type === 'resize-right') {
        const t = pxToTime(e.clientX - rect.left)
        onChange(clips.map(c => {
          if (c.id !== drag.id) return c
          const newEnd = Math.min(videoDuration, Math.max(c.source_start + 0.5, t))
          return { ...c, source_end: newEnd }
        }))
      } else if (drag.type === 'scrub') {
        const t = pxToTime(e.clientX - rect.left)
        onScrub?.(t)
      }
    }

    const onUp = () => setDrag(null)

    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [drag, clips, onChange, pxToTime, videoDuration, onScrub])

  // ─── Track click → create new clip ──────────────────────────────────────
  const onTrackMouseDown = (e: React.MouseEvent) => {
    // Skip nếu click vào clip (đã có handler riêng)
    if ((e.target as HTMLElement).dataset.clip) return
    const rect = trackRef.current!.getBoundingClientRect()
    const t = pxToTime(e.clientX - rect.left)

    // Shift = create clip; otherwise = scrub
    if (e.shiftKey) {
      const id = genId()
      const newClip: VideoClip = {
        id,
        source_start: t,
        source_end: Math.min(videoDuration, t + 5),
        label: `Đoạn ${clips.length + 1}`,
      }
      onChange([...clips, newClip])
      setSelectedId(id)
      setDrag({ type: 'create', startX: e.clientX, startTime: t, id })
    } else {
      // Scrub
      onScrub?.(t)
      setDrag({ type: 'scrub' })
      setSelectedId(null)
    }
  }

  const onClipMouseDown = (e: React.MouseEvent, clip: VideoClip, handle: 'left' | 'right' | 'body') => {
    e.stopPropagation()
    setSelectedId(clip.id)
    if (handle === 'left') {
      setDrag({ type: 'resize-left', id: clip.id, startX: e.clientX, origStart: clip.source_start })
    } else if (handle === 'right') {
      setDrag({ type: 'resize-right', id: clip.id, startX: e.clientX, origEnd: clip.source_end })
    } else {
      setDrag({ type: 'move', id: clip.id, startX: e.clientX, origStart: clip.source_start, origEnd: clip.source_end })
    }
  }

  const removeClip = (id: string) => {
    onChange(clips.filter(c => c.id !== id))
    if (selectedId === id) setSelectedId(null)
  }

  const addClipQuick = () => {
    const last = clips[clips.length - 1]
    const start = last ? last.source_end : 0
    const end = Math.min(start + 30, videoDuration || start + 30)
    onChange([...clips, { id: genId(), source_start: start, source_end: end, label: `Đoạn ${clips.length + 1}` }])
  }

  const totalKeep = clips.reduce((s, c) => s + Math.max(0, c.source_end - c.source_start), 0)

  // ─── Render time ruler (mỗi 10% hoặc nhiều hơn nếu video ngắn) ──────────
  const rulerSteps = videoDuration > 0 ? Array.from({ length: 11 }, (_, i) => i / 10) : []

  return (
    <div className="space-y-2">
      {/* Header info */}
      <div className="flex items-center justify-between text-[12px]">
        <div className="flex items-center gap-3">
          <span className="text-zinc-500">Video gốc:</span>
          <span className="font-mono">{fmtTime(videoDuration)}</span>
          <span className="text-zinc-300">·</span>
          <span className="text-zinc-500">{clips.length} khoảng giữ</span>
          <span className="text-zinc-300">·</span>
          <span className="text-zinc-500">Tổng output:</span>
          <span className="font-mono font-semibold text-emerald-700 dark:text-emerald-500">
            {fmtTime(totalKeep || videoDuration)}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={addClipQuick} className="btn text-[11px]">+ Thêm nhanh</button>
          {clips.length > 0 && (
            <button onClick={() => onChange([])} className="text-[11px] text-red-600 hover:text-red-700 px-2">
              Xóa hết
            </button>
          )}
        </div>
      </div>

      {/* Timeline */}
      <div className="relative select-none">
        {/* Ruler trên */}
        <div className="relative h-5 text-[10px] text-zinc-400 font-mono">
          {rulerSteps.map(s => (
            <div key={s} className="absolute top-0 -translate-x-1/2"
              style={{ left: `${s * 100}%` }}>
              {fmtTime(s * videoDuration)}
            </div>
          ))}
        </div>

        {/* Track */}
        <div
          ref={trackRef}
          onMouseDown={onTrackMouseDown}
          onMouseMove={e => {
            const rect = trackRef.current?.getBoundingClientRect()
            if (rect) setHoverTime(pxToTime(e.clientX - rect.left))
          }}
          onMouseLeave={() => setHoverTime(null)}
          className="relative bg-zinc-200 dark:bg-zinc-800 rounded-md overflow-hidden cursor-pointer border border-zinc-300 dark:border-zinc-700"
          style={{ height: TIMELINE_HEIGHT }}
        >
          {/* Thumbnail strip nền */}
          {thumbs.length > 0 && (
            <div className="absolute inset-0 flex">
              {thumbs.map((src, i) => (
                <img key={i} src={src} alt=""
                  className="h-full object-cover flex-1 opacity-70"
                  style={{ filter: 'brightness(0.7)' }}
                  draggable={false} />
              ))}
            </div>
          )}
          {thumbs.length === 0 && (
            <div className="absolute inset-0 flex items-center justify-center text-[11px] text-zinc-500">
              {videoUrl ? 'Đang tạo thumbnails...' : 'Chưa có video'}
            </div>
          )}

          {/* Hover tooltip */}
          {hoverTime !== null && (
            <div className="absolute top-0 bottom-0 w-px bg-white/30 pointer-events-none"
              style={{ left: `${timeToPercent(hoverTime)}%` }}>
              <div className="absolute -top-5 -translate-x-1/2 px-1 bg-zinc-900 text-white text-[10px] font-mono rounded whitespace-nowrap">
                {fmtTime(hoverTime)}
              </div>
            </div>
          )}

          {/* Scrubber (vị trí preview hiện tại) */}
          {currentTime > 0 && (
            <div className="absolute top-0 bottom-0 w-0.5 bg-red-500 pointer-events-none z-20"
              style={{ left: `${timeToPercent(currentTime)}%` }}>
              <div className="absolute -top-1.5 -translate-x-1/2 w-3 h-3 bg-red-500 rounded-full" />
            </div>
          )}

          {/* Clips */}
          {clips.map((c, i) => {
            const left = timeToPercent(c.source_start)
            const width = timeToPercent(c.source_end) - left
            const isSel = selectedId === c.id
            return (
              <div
                key={c.id}
                data-clip="1"
                onMouseDown={e => onClipMouseDown(e, c, 'body')}
                onDoubleClick={() => setEditing(c.id)}
                onClick={e => { e.stopPropagation(); setSelectedId(c.id) }}
                className={`absolute z-10 rounded transition-shadow cursor-move ${
                  isSel
                    ? 'bg-blue-500/85 ring-2 ring-blue-300 shadow-lg'
                    : 'bg-blue-500/70 hover:bg-blue-500/80'
                }`}
                style={{
                  left: `${left}%`,
                  width: `${Math.max(0.5, width)}%`,
                  top: (TIMELINE_HEIGHT - CLIP_HEIGHT) / 2,
                  height: CLIP_HEIGHT,
                }}
                title="Click chọn · Drag để di chuyển · Drag handle 2 bên để chỉnh · Double-click để nhập time"
              >
                {/* Handle trái */}
                <div
                  data-clip="1"
                  onMouseDown={e => onClipMouseDown(e, c, 'left')}
                  className="absolute left-0 top-0 bottom-0 w-2 cursor-ew-resize bg-white/50 hover:bg-white"
                  style={{ borderTopLeftRadius: 4, borderBottomLeftRadius: 4 }}
                />
                {/* Handle phải */}
                <div
                  data-clip="1"
                  onMouseDown={e => onClipMouseDown(e, c, 'right')}
                  className="absolute right-0 top-0 bottom-0 w-2 cursor-ew-resize bg-white/50 hover:bg-white"
                  style={{ borderTopRightRadius: 4, borderBottomRightRadius: 4 }}
                />
                {/* Label */}
                <div className="absolute inset-0 flex items-center justify-center text-[11px] text-white font-medium pointer-events-none px-2 truncate">
                  {c.label || `Đoạn ${i + 1}`} ({fmtTime(c.source_end - c.source_start)})
                </div>
                {/* Delete button khi selected */}
                {isSel && (
                  <button
                    data-clip="1"
                    onClick={e => { e.stopPropagation(); removeClip(c.id) }}
                    className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-500 text-white text-[10px] flex items-center justify-center hover:bg-red-600 z-30"
                    title="Xóa"
                  >
                    ×
                  </button>
                )}
              </div>
            )
          })}
        </div>

        {/* Hướng dẫn */}
        <div className="text-[10.5px] text-zinc-500 mt-1.5 leading-relaxed">
          💡 <b>Shift + click & kéo</b> trên timeline để tạo khoảng giữ mới ·
          <b> Drag 2 cạnh xanh</b> để chỉnh start/end ·
          <b> Drag giữa</b> để di chuyển ·
          <b> Double-click</b> để nhập time chính xác ·
          <b> Click thường</b> để scrub (xem video tại vị trí đó)
        </div>
      </div>

      {/* Popup edit time chính xác */}
      {editing && (() => {
        const c = clips.find(x => x.id === editing)
        if (!c) return null
        return (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setEditing(null)}>
            <div className="bg-white dark:bg-zinc-900 rounded-lg p-5 max-w-sm w-full shadow-xl" onClick={e => e.stopPropagation()}>
              <h3 className="text-[14px] font-semibold mb-3">Chỉnh khoảng cắt</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-[11px] text-zinc-500 mb-1 uppercase tracking-wider">Tên</label>
                  <input type="text" defaultValue={c.label || ''}
                    onBlur={e => onChange(clips.map(x => x.id === c.id ? { ...x, label: e.target.value } : x))}
                    className="input w-full text-[13px]" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] text-zinc-500 mb-1 uppercase tracking-wider">Từ</label>
                    <input type="text" defaultValue={fmtTime(c.source_start)}
                      onBlur={e => onChange(clips.map(x => x.id === c.id ? { ...x, source_start: parseTime(e.target.value) } : x))}
                      className="input w-full text-[13px] font-mono text-center" />
                  </div>
                  <div>
                    <label className="block text-[11px] text-zinc-500 mb-1 uppercase tracking-wider">Đến</label>
                    <input type="text" defaultValue={fmtTime(c.source_end)}
                      onBlur={e => onChange(clips.map(x => x.id === c.id ? { ...x, source_end: parseTime(e.target.value) } : x))}
                      className="input w-full text-[13px] font-mono text-center" />
                  </div>
                </div>
                <div className="text-[11px] text-zinc-500 text-center">
                  Thời lượng: <span className="font-mono">{fmtTime(c.source_end - c.source_start)}</span>
                </div>
              </div>
              <div className="flex justify-end gap-2 mt-4">
                <button onClick={() => removeClip(c.id)} className="text-[12px] text-red-600 hover:text-red-700 px-3">🗑 Xóa</button>
                <button onClick={() => setEditing(null)} className="btn btn-primary text-[12px]">Xong</button>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
