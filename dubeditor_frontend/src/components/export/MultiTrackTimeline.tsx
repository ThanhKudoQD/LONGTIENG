/**
 * MultiTrackTimeline v2 — layout 2 cột:
 *   ┌──────────┬──────────────────────────────────┐
 *   │ Labels   │    Tracks (scroll ngang)          │
 *   │ (sticky) │                                   │
 *   │          │  ─── ruler ────                   │
 *   │ 📹 Video │  [thumbnails][CLIP]               │
 *   │ 🎤 Voice │  ▌▌▌  ▌▌▌                        │
 *   │ ♪ BGM 1  │  [════════ bgm1 ════════]         │
 *   └──────────┴──────────────────────────────────┘
 *                ↑ playhead đỏ chỉ chạy TRONG đây
 *
 * Sticky label = không scroll khi zoom in, track scroll mượt.
 */
import React, { useRef, useState, useEffect, useCallback } from 'react'
import { VideoClip, AudioTrack, AudioConfig } from './types'

interface Props {
  videoUrl: string | null
  videoDuration: number
  clips: VideoClip[]
  onClipsChange: (clips: VideoClip[]) => void
  audio: AudioConfig
  onAudioChange: (audio: AudioConfig) => void
  voiceSegments?: Array<{ start: number; end: number; id: number }>
  currentTime: number
  onScrub: (t: number) => void
}

type DragState =
  | { type: 'clip-move'; id: string; startX: number; origStart: number; origEnd: number }
  | { type: 'clip-left'; id: string; startX: number }
  | { type: 'clip-right'; id: string; startX: number }
  | { type: 'clip-create'; startX: number; startTime: number; id: string }
  | { type: 'bgm-move'; id: string; startX: number; origStart: number; origEnd: number }
  | { type: 'bgm-left'; id: string; startX: number }
  | { type: 'bgm-right'; id: string; startX: number }
  | { type: 'scrub' }
  | null

function genId() { return Math.random().toString(36).slice(2, 10) }
function fmtTime(s: number): string {
  if (!isFinite(s) || s < 0) return '0:00'
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = Math.floor(s % 60)
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`
  return `${m}:${String(sec).padStart(2, '0')}`
}

const TRACK_H = 48
const CLIP_INSET = 6
const LABEL_W = 128
const RULER_H = 22

export default function MultiTrackTimeline({
  videoUrl, videoDuration, clips, onClipsChange,
  audio, onAudioChange, voiceSegments = [],
  currentTime, onScrub,
}: Props) {
  // Ref cho track area (scrollable) — dùng để tính px → time
  const tracksScrollRef = useRef<HTMLDivElement>(null)
  // Inner div = phần content có width = zoom × baseW
  const tracksInnerRef = useRef<HTMLDivElement>(null)
  const [drag, setDrag] = useState<DragState>(null)
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null)
  const [selectedBgmId, setSelectedBgmId] = useState<string | null>(null)
  const [editingClipId, setEditingClipId] = useState<string | null>(null)
  const [hoverTime, setHoverTime] = useState<number | null>(null)
  const [thumbs, setThumbs] = useState<string[]>([])
  const [zoom, setZoom] = useState(1)

  // Tổng chiều rộng tracks (px) = base × zoom
  // base = chiều rộng container scrollable (đo khi mount/resize)
  const [baseTrackW, setBaseTrackW] = useState(0)
  useEffect(() => {
    if (!tracksScrollRef.current) return
    const el = tracksScrollRef.current
    const update = () => setBaseTrackW(el.clientWidth)
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const totalTrackW = baseTrackW * zoom

  // ─── px ↔ time (px ở đây là vị trí trong inner div, từ 0 đến totalTrackW) ───
  const pxToTime = useCallback((pxInInner: number): number => {
    if (totalTrackW === 0 || videoDuration === 0) return 0
    return Math.max(0, Math.min(videoDuration, (pxInInner / totalTrackW) * videoDuration))
  }, [totalTrackW, videoDuration])

  // Helper: clientX → pxInInner (cộng scrollLeft, trừ rect.left)
  const clientXToInnerPx = useCallback((clientX: number): number => {
    if (!tracksScrollRef.current) return 0
    const rect = tracksScrollRef.current.getBoundingClientRect()
    const scrollLeft = tracksScrollRef.current.scrollLeft
    return (clientX - rect.left) + scrollLeft
  }, [])

  const timeToPercent = useCallback((t: number): number => {
    if (videoDuration === 0) return 0
    return Math.max(0, Math.min(100, (t / videoDuration) * 100))
  }, [videoDuration])

  // ─── Thumbnails generation ──────────────────────────────────────────────
  useEffect(() => {
    if (!videoUrl || videoDuration === 0) { setThumbs([]); return }
    let cancelled = false
    const COUNT = 16
    const video = document.createElement('video')
    video.crossOrigin = 'anonymous'
    video.src = videoUrl
    video.muted = true
    video.preload = 'metadata'
    const canvas = document.createElement('canvas')
    canvas.width = 160; canvas.height = 90
    const ctx = canvas.getContext('2d')!
    const result: string[] = []
    let idx = 0
    const grabNext = () => {
      if (cancelled || idx >= COUNT) {
        if (!cancelled) setThumbs(result)
        return
      }
      video.currentTime = (idx / COUNT) * videoDuration
    }
    video.addEventListener('loadedmetadata', grabNext)
    video.addEventListener('seeked', () => {
      if (cancelled) return
      try {
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
        result.push(canvas.toDataURL('image/jpeg', 0.6))
      } catch {}
      idx++; grabNext()
    })
    video.addEventListener('error', () => setThumbs([]))
    return () => { cancelled = true }
  }, [videoUrl, videoDuration])

  // ─── Global drag handler ────────────────────────────────────────────────
  useEffect(() => {
    if (!drag) return
    const onMove = (e: MouseEvent) => {
      if (!tracksScrollRef.current) return
      const dx = e.clientX - (drag as any).startX
      const dtSec = (dx / totalTrackW) * videoDuration

      if (drag.type === 'clip-create') {
        const cur = pxToTime(clientXToInnerPx(e.clientX))
        const start = Math.min(drag.startTime, cur)
        const end = Math.max(drag.startTime, cur)
        onClipsChange(clips.map(c => c.id === drag.id ? { ...c, source_start: start, source_end: end } : c))
      } else if (drag.type === 'clip-move') {
        const len = drag.origEnd - drag.origStart
        let newStart = Math.max(0, Math.min(videoDuration - len, drag.origStart + dtSec))
        onClipsChange(clips.map(c => c.id === drag.id ? { ...c, source_start: newStart, source_end: newStart + len } : c))
      } else if (drag.type === 'clip-left') {
        const t = pxToTime(clientXToInnerPx(e.clientX))
        onClipsChange(clips.map(c => c.id === drag.id
          ? { ...c, source_start: Math.max(0, Math.min(c.source_end - 0.5, t)) } : c))
      } else if (drag.type === 'clip-right') {
        const t = pxToTime(clientXToInnerPx(e.clientX))
        onClipsChange(clips.map(c => c.id === drag.id
          ? { ...c, source_end: Math.min(videoDuration, Math.max(c.source_start + 0.5, t)) } : c))
      } else if (drag.type === 'bgm-move') {
        const len = drag.origEnd - drag.origStart
        let newStart = Math.max(0, Math.min(videoDuration - len, drag.origStart + dtSec))
        onAudioChange({ ...audio, tracks: audio.tracks.map(t => t.id === drag.id
          ? { ...t, start_time: newStart, end_time: newStart + len } : t) })
      } else if (drag.type === 'bgm-left') {
        const t = pxToTime(clientXToInnerPx(e.clientX))
        onAudioChange({ ...audio, tracks: audio.tracks.map(tr => tr.id === drag.id
          ? { ...tr, start_time: Math.max(0, Math.min(tr.end_time - 0.5, t)) } : tr) })
      } else if (drag.type === 'bgm-right') {
        const t = pxToTime(clientXToInnerPx(e.clientX))
        onAudioChange({ ...audio, tracks: audio.tracks.map(tr => tr.id === drag.id
          ? { ...tr, end_time: Math.min(videoDuration, Math.max(tr.start_time + 0.5, t)) } : tr) })
      } else if (drag.type === 'scrub') {
        onScrub(pxToTime(clientXToInnerPx(e.clientX)))
      }
    }
    const onUp = () => setDrag(null)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [drag, clips, audio, pxToTime, clientXToInnerPx, totalTrackW, videoDuration, onClipsChange, onAudioChange, onScrub])

  // ─── Video track mousedown ──────────────────────────────────────────────
  const onVideoTrackMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).dataset.block) return
    const t = pxToTime(clientXToInnerPx(e.clientX))
    if (e.shiftKey) {
      const id = genId()
      const newClip: VideoClip = {
        id, source_start: t,
        source_end: Math.min(videoDuration, t + 5),
        label: `Đoạn ${clips.length + 1}`,
      }
      onClipsChange([...clips, newClip])
      setSelectedClipId(id)
      setDrag({ type: 'clip-create', startX: e.clientX, startTime: t, id })
    } else {
      onScrub(t)
      setDrag({ type: 'scrub' })
      setSelectedClipId(null)
      setSelectedBgmId(null)
    }
  }

  const onClipMouseDown = (e: React.MouseEvent, clip: VideoClip, h: 'l' | 'r' | 'b') => {
    e.stopPropagation()
    setSelectedClipId(clip.id); setSelectedBgmId(null)
    if (h === 'l') setDrag({ type: 'clip-left', id: clip.id, startX: e.clientX })
    else if (h === 'r') setDrag({ type: 'clip-right', id: clip.id, startX: e.clientX })
    else setDrag({ type: 'clip-move', id: clip.id, startX: e.clientX, origStart: clip.source_start, origEnd: clip.source_end })
  }

  const onBgmMouseDown = (e: React.MouseEvent, tr: AudioTrack, h: 'l' | 'r' | 'b') => {
    e.stopPropagation()
    setSelectedBgmId(tr.id); setSelectedClipId(null)
    if (h === 'l') setDrag({ type: 'bgm-left', id: tr.id, startX: e.clientX })
    else if (h === 'r') setDrag({ type: 'bgm-right', id: tr.id, startX: e.clientX })
    else setDrag({ type: 'bgm-move', id: tr.id, startX: e.clientX, origStart: tr.start_time, origEnd: tr.end_time })
  }

  const onScrubAreaMouseDown = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).dataset.block) return
    const t = pxToTime(clientXToInnerPx(e.clientX))
    onScrub(t)
    setDrag({ type: 'scrub' })
  }

  const removeClip = (id: string) => {
    onClipsChange(clips.filter(c => c.id !== id))
    if (selectedClipId === id) setSelectedClipId(null)
  }

  // ─── Ruler ──────────────────────────────────────────────────────────────
  const numTicks = Math.min(20, Math.max(6, Math.round(10 * zoom)))
  const rulerSteps = videoDuration > 0
    ? Array.from({ length: numTicks + 1 }, (_, i) => i / numTicks)
    : []

  // Total content height (TRƯỚC tracks bao gồm ruler)
  const numBgmTracks = audio.tracks.length || 1  // ít nhất 1 row "empty BGM"
  const totalRowsH = RULER_H + TRACK_H + TRACK_H * 0.7 + numBgmTracks * (TRACK_H * 0.8)

  return (
    <div className="select-none">
      {/* Toolbar nhỏ */}
      <div className="flex items-center justify-between mb-2 text-[11px]">
        <div className="flex items-center gap-3">
          <span className="text-zinc-500">Timeline</span>
          <span className="font-mono text-zinc-400">·</span>
          <span className="text-zinc-600 dark:text-zinc-400">
            {clips.length} cắt · {audio.tracks.length} BGM
          </span>
          {videoDuration > 0 && (
            <>
              <span className="font-mono text-zinc-400">·</span>
              <span className="font-mono text-zinc-500">{fmtTime(videoDuration)}</span>
            </>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-zinc-500">Zoom:</span>
          {[1, 2, 4, 8].map(z => (
            <button key={z} onClick={() => setZoom(z)}
              className={`px-2 py-0.5 rounded ${
                zoom === z ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40' : 'hover:bg-zinc-100 dark:hover:bg-zinc-800'
              }`}>{z}×</button>
          ))}
        </div>
      </div>

      {/* ─── Main timeline: 2 cột ──────────────────────────────────────── */}
      <div className="border border-zinc-200 dark:border-zinc-700 rounded-md bg-white dark:bg-zinc-950 flex"
        onMouseLeave={() => setHoverTime(null)}>

        {/* CỘT LABELS (sticky bên trái) */}
        <div className="flex-shrink-0 bg-zinc-50 dark:bg-zinc-900 border-r border-zinc-200 dark:border-zinc-800"
          style={{ width: LABEL_W }}>
          {/* Ruler row label (empty) */}
          <div className="border-b border-zinc-200 dark:border-zinc-800" style={{ height: RULER_H }} />
          {/* Video label */}
          <div className="border-b border-zinc-200 dark:border-zinc-800" style={{ height: TRACK_H }}>
            <TrackLabel icon="📹" label="Video" hint={`${clips.length} cắt`} />
          </div>
          {/* Voice TTS label */}
          <div className="border-b border-zinc-200 dark:border-zinc-800" style={{ height: TRACK_H * 0.7 }}>
            <TrackLabel icon="🎤" label="Voice TTS"
              hint={audio.voice_enabled ? `${voiceSegments.length} dòng` : 'TẮT'} />
          </div>
          {/* BGM labels */}
          {audio.tracks.length === 0 ? (
            <div className="border-b border-zinc-200 dark:border-zinc-800" style={{ height: TRACK_H * 0.8 }}>
              <TrackLabel icon="♪" label="BGM" hint="trống" />
            </div>
          ) : (
            audio.tracks.map((tr, i) => (
              <div key={tr.id} className="border-b border-zinc-200 dark:border-zinc-800" style={{ height: TRACK_H * 0.8 }}>
                <TrackLabel icon="♪" label={tr.name || `BGM ${i + 1}`} hint={`${Math.round(tr.volume * 100)}%`} />
              </div>
            ))
          )}
        </div>

        {/* CỘT TRACKS (scroll ngang) */}
        <div ref={tracksScrollRef} className="flex-1 overflow-x-auto overflow-y-hidden relative">
          <div ref={tracksInnerRef} className="relative"
            style={{ width: totalTrackW || '100%' }}
            onMouseMove={e => setHoverTime(pxToTime(clientXToInnerPx(e.clientX)))}
          >
            {/* ─── Ruler ───────────────────────────────────────────────── */}
            <div className="relative border-b border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 text-[10px] font-mono text-zinc-500"
              style={{ height: RULER_H }}>
              {rulerSteps.map(s => (
                <div key={s} className="absolute top-0 bottom-0 flex items-center"
                  style={{ left: `${s * 100}%` }}>
                  <div className="absolute left-0 top-0 h-1.5 w-px bg-zinc-300 dark:bg-zinc-600" />
                  <span className="pl-1">{fmtTime(s * videoDuration)}</span>
                </div>
              ))}
            </div>

            {/* ─── Track Video ─────────────────────────────────────────── */}
            <div
              onMouseDown={onVideoTrackMouseDown}
              className="relative cursor-pointer border-b border-zinc-200 dark:border-zinc-800"
              style={{ height: TRACK_H, background: 'linear-gradient(to bottom, #1a1a1a, #0a0a0a)' }}
            >
              {thumbs.length > 0 && (
                <div className="absolute inset-0 flex">
                  {thumbs.map((src, i) => (
                    <img key={i} src={src} alt="" className="h-full object-cover flex-1 opacity-90" draggable={false} />
                  ))}
                </div>
              )}
              {thumbs.length === 0 && videoUrl && (
                <div className="absolute inset-0 flex items-center justify-center text-[10px] text-zinc-500">
                  Đang tạo thumbnails...
                </div>
              )}

              {/* Mask ngoài clip */}
              {clips.length > 0 && (
                <div className="absolute inset-0 bg-black/55 pointer-events-none" />
              )}

              {/* Clip blocks */}
              {clips.map((c, i) => {
                const left = timeToPercent(c.source_start)
                const width = timeToPercent(c.source_end) - left
                const isSel = selectedClipId === c.id
                return (
                  <div key={c.id} data-block="1"
                    onMouseDown={e => onClipMouseDown(e, c, 'b')}
                    onDoubleClick={() => setEditingClipId(c.id)}
                    className={`absolute z-10 cursor-move transition-shadow ${isSel ? 'ring-2 ring-emerald-300' : ''}`}
                    style={{
                      left: `${left}%`, width: `${Math.max(0.5, width)}%`,
                      top: CLIP_INSET, height: TRACK_H - CLIP_INSET * 2,
                      background: 'rgba(16,185,129,0.25)',
                      borderTop: '2px solid rgb(16,185,129)',
                      borderBottom: '2px solid rgb(16,185,129)',
                    }}>
                    <div data-block="1" onMouseDown={e => onClipMouseDown(e, c, 'l')}
                      className="absolute left-0 top-0 bottom-0 w-1.5 cursor-ew-resize bg-emerald-500 hover:bg-emerald-300" />
                    <div data-block="1" onMouseDown={e => onClipMouseDown(e, c, 'r')}
                      className="absolute right-0 top-0 bottom-0 w-1.5 cursor-ew-resize bg-emerald-500 hover:bg-emerald-300" />
                    <div className="absolute inset-0 flex items-center justify-center text-[10px] text-white font-medium pointer-events-none px-2 truncate"
                      style={{ textShadow: '0 1px 2px rgba(0,0,0,0.8)' }}>
                      {c.label || `Đoạn ${i + 1}`} ({fmtTime(c.source_end - c.source_start)})
                    </div>
                    {isSel && (
                      <button data-block="1" onClick={e => { e.stopPropagation(); removeClip(c.id) }}
                        className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-500 text-white text-[10px] flex items-center justify-center hover:bg-red-600 z-30">×</button>
                    )}
                  </div>
                )
              })}
            </div>

            {/* ─── Voice TTS track ─────────────────────────────────────── */}
            <div className="relative bg-purple-50 dark:bg-purple-950/30 border-b border-zinc-200 dark:border-zinc-800"
              style={{ height: TRACK_H * 0.7 }}
              onMouseDown={onScrubAreaMouseDown}>
              {voiceSegments.length === 0 ? (
                <div className="absolute inset-0 flex items-center justify-center text-[10px] text-zinc-400">
                  {audio.voice_enabled ? '(chưa có voice — TTS các sub trước)' : '(voice TTS đã tắt)'}
                </div>
              ) : (
                voiceSegments.slice(0, 500).map(seg => (
                  <div key={seg.id} className="absolute bg-purple-400/70 dark:bg-purple-500/60 rounded-sm pointer-events-none"
                    style={{
                      left: `${timeToPercent(seg.start)}%`,
                      width: `${Math.max(0.05, timeToPercent(seg.end) - timeToPercent(seg.start))}%`,
                      top: 4, bottom: 4,
                    }}
                    title={`Sub #${seg.id}: ${fmtTime(seg.start)} → ${fmtTime(seg.end)}`}
                  />
                ))
              )}
            </div>

            {/* ─── BGM tracks ──────────────────────────────────────────── */}
            {audio.tracks.length === 0 ? (
              <div className="relative bg-amber-50/30 dark:bg-amber-950/10 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-center text-[10px] text-zinc-400"
                style={{ height: TRACK_H * 0.8 }}
                onMouseDown={onScrubAreaMouseDown}>
                (chưa có BGM — vào tab Audio để upload)
              </div>
            ) : audio.tracks.map((tr, i) => {
              const left = timeToPercent(tr.start_time)
              const width = timeToPercent(tr.end_time) - left
              const isSel = selectedBgmId === tr.id
              return (
                <div key={tr.id} className="relative bg-amber-50/50 dark:bg-amber-950/20 border-b border-zinc-200 dark:border-zinc-800"
                  style={{ height: TRACK_H * 0.8 }}
                  onMouseDown={onScrubAreaMouseDown}>
                  <div data-block="1"
                    onMouseDown={e => onBgmMouseDown(e, tr, 'b')}
                    className={`absolute cursor-move rounded transition-shadow ${isSel ? 'ring-2 ring-amber-400 shadow-md' : ''}`}
                    style={{
                      left: `${left}%`, width: `${Math.max(0.5, width)}%`,
                      top: 4, bottom: 4,
                      background: 'linear-gradient(to bottom, rgba(245,158,11,0.8), rgba(217,119,6,0.9))',
                    }}>
                    <div data-block="1" onMouseDown={e => onBgmMouseDown(e, tr, 'l')}
                      className="absolute left-0 top-0 bottom-0 w-1.5 cursor-ew-resize bg-amber-700/60 hover:bg-white/80 rounded-l" />
                    <div data-block="1" onMouseDown={e => onBgmMouseDown(e, tr, 'r')}
                      className="absolute right-0 top-0 bottom-0 w-1.5 cursor-ew-resize bg-amber-700/60 hover:bg-white/80 rounded-r" />
                    <div className="absolute inset-0 flex items-center justify-around pointer-events-none px-2 opacity-50">
                      {Array.from({ length: 30 }).map((_, k) => (
                        <div key={k} className="w-px bg-white"
                          style={{ height: `${20 + Math.abs(Math.sin(k * 0.7)) * 50}%` }} />
                      ))}
                    </div>
                    <div className="absolute inset-0 flex items-center justify-center text-[10px] text-white font-medium pointer-events-none px-2 truncate"
                      style={{ textShadow: '0 1px 2px rgba(0,0,0,0.6)' }}>
                      {tr.name} ({fmtTime(tr.end_time - tr.start_time)})
                    </div>
                    {isSel && (
                      <button data-block="1" onClick={e => {
                        e.stopPropagation()
                        onAudioChange({ ...audio, tracks: audio.tracks.filter(t => t.id !== tr.id) })
                        setSelectedBgmId(null)
                      }}
                        className="absolute -top-2 -right-2 w-5 h-5 rounded-full bg-red-500 text-white text-[10px] flex items-center justify-center hover:bg-red-600 z-30">×</button>
                    )}
                  </div>
                </div>
              )
            })}

            {/* ─── Playhead (scrubber đỏ) — TRONG inner div ─────────────── */}
            {videoDuration > 0 && (
              <div className="absolute top-0 bg-red-500 pointer-events-none z-40"
                style={{
                  left: `${timeToPercent(currentTime)}%`,
                  width: 2,
                  height: totalRowsH,
                }}>
                <div className="absolute -top-1 -left-1.5 w-3 h-3 rounded-full bg-red-500" />
              </div>
            )}

            {/* ─── Hover tooltip ──────────────────────────────────────── */}
            {hoverTime !== null && (
              <div className="absolute top-0 bottom-0 w-px bg-blue-400/40 pointer-events-none z-30"
                style={{ left: `${timeToPercent(hoverTime)}%`, height: totalRowsH }}>
                <div className="absolute -top-0 left-1 px-1 bg-zinc-900 text-white text-[10px] font-mono rounded whitespace-nowrap"
                  style={{ marginTop: 2 }}>
                  {fmtTime(hoverTime)}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Hints */}
      <div className="text-[10.5px] text-zinc-500 mt-2 leading-relaxed">
        💡 <b>Track Video</b>: Shift+drag tạo khoảng giữ · drag cạnh xanh chỉnh start/end · double-click block để nhập time<br />
        <b>Track BGM</b>: drag để di chuyển vị trí · drag cạnh để chỉnh start/end · click chọn rồi × xóa<br />
        Click track Video chỗ trống để scrub xem video tại vị trí đó · zoom in rồi scroll ngang để xem chi tiết
      </div>

      {/* Popup edit clip */}
      {editingClipId && (() => {
        const c = clips.find(x => x.id === editingClipId)
        if (!c) return null
        const parseTime = (str: string) => {
          const parts = str.split(':').map(p => parseInt(p.trim()) || 0)
          if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2]
          if (parts.length === 2) return parts[0] * 60 + parts[1]
          return parts[0] || 0
        }
        return (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={() => setEditingClipId(null)}>
            <div className="bg-white dark:bg-zinc-900 rounded-lg p-5 max-w-sm w-full shadow-xl" onClick={e => e.stopPropagation()}>
              <h3 className="text-[14px] font-semibold mb-3">Chỉnh khoảng cắt</h3>
              <div className="space-y-3">
                <div>
                  <label className="block text-[11px] text-zinc-500 mb-1 uppercase tracking-wider">Tên</label>
                  <input type="text" defaultValue={c.label || ''}
                    onBlur={e => onClipsChange(clips.map(x => x.id === c.id ? { ...x, label: e.target.value } : x))}
                    className="input w-full text-[13px]" />
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] text-zinc-500 mb-1 uppercase tracking-wider">Từ</label>
                    <input type="text" defaultValue={fmtTime(c.source_start)}
                      onBlur={e => onClipsChange(clips.map(x => x.id === c.id ? { ...x, source_start: parseTime(e.target.value) } : x))}
                      className="input w-full text-[13px] font-mono text-center" />
                  </div>
                  <div>
                    <label className="block text-[11px] text-zinc-500 mb-1 uppercase tracking-wider">Đến</label>
                    <input type="text" defaultValue={fmtTime(c.source_end)}
                      onBlur={e => onClipsChange(clips.map(x => x.id === c.id ? { ...x, source_end: parseTime(e.target.value) } : x))}
                      className="input w-full text-[13px] font-mono text-center" />
                  </div>
                </div>
                <div className="text-[11px] text-zinc-500 text-center">
                  Thời lượng: <span className="font-mono">{fmtTime(c.source_end - c.source_start)}</span>
                </div>
              </div>
              <div className="flex justify-end gap-2 mt-4">
                <button onClick={() => removeClip(c.id)} className="text-[12px] text-red-600 hover:text-red-700 px-3">🗑 Xóa</button>
                <button onClick={() => setEditingClipId(null)} className="btn btn-primary text-[12px]">Xong</button>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}

function TrackLabel({ icon, label, hint }: { icon: string; label: string; hint?: string }) {
  return (
    <div className="h-full px-3 py-1 flex flex-col justify-center">
      <div className="text-[11.5px] font-semibold text-zinc-700 dark:text-zinc-300 flex items-center gap-1.5 truncate">
        <span className="text-[13px]">{icon}</span>
        <span className="truncate">{label}</span>
      </div>
      {hint && <div className="text-[10px] text-zinc-500 truncate">{hint}</div>}
    </div>
  )
}
