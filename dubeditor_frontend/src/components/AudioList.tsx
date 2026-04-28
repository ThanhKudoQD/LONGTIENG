import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import useStore, { usePlayTimeStore } from '../store'
import api from '../api'
import { findOverlapsSweep, assignLanes, maxOf } from '../utils/perf'
import { playSubAudio, stopGlobalAudio, subscribePlayingId } from '../audio'
import type { Subtitle } from '../types'

// Re-export để code khác (CharSidebar, Editor) dùng tiếp các API cũ
export { playSubAudio, stopGlobalAudio, getGlobalPlayingId } from '../audio'

const PX_PER_SEC = 120
const SUB_ROW_H  = 26
const LANE_H     = 36
const HEADER_H   = 24
const RESIZE_H   = 6
const DEFAULT_H  = 200
const MIN_H      = 100
const MAX_H      = 500

// ─── Playhead riêng component ──────────────────────────────────────────────
// Tách Playhead ra thành component riêng subscribe playTime store.
// → 60 tick/giây của playhead KHÔNG re-render toàn bộ AudioList nữa.
function Playhead({ pxPerSec }: { pxPerSec: number }) {
  const playTime = usePlayTimeStore(s => s.playTime)
  return (
    <div className="absolute top-0 bottom-0 pointer-events-none z-20"
      style={{ left: Math.round(playTime * pxPerSec), width: 1 }}>
      <div className="absolute top-0 bottom-0 w-px bg-red-500 opacity-90"/>
      <div className="absolute w-0 h-0 border-l-[4px] border-r-[4px] border-t-[6px] border-l-transparent border-r-transparent border-t-red-500"
        style={{ top: 0, left: -3.5 }}/>
    </div>
  )
}

// ─── Subtitle bar (hàng trên) ──────────────────────────────────────────────
interface SubBarProps {
  s: Subtitle
  isActive: boolean
  pxPerSec: number
  onClick: (id: number) => void
}
const SubBar = React.memo(function SubBar({ s, isActive, pxPerSec, onClick }: SubBarProps) {
  const leftPx  = Math.round(s.start_time * pxPerSec)
  const widthPx = Math.max(2, Math.round((s.end_time - s.start_time) * pxPerSec))
  const color   = s.character?.color || '#475569'
  return (
    <div
      className="absolute top-0.5 rounded-sm cursor-pointer overflow-hidden"
      style={{
        left: leftPx, width: widthPx, height: SUB_ROW_H - 4,
        background: color + (isActive ? 'cc' : '35'),
        border: `1px solid ${color}${isActive ? 'ff' : '55'}`,
        zIndex: isActive ? 5 : 1,
      }}
      onClick={e => { e.stopPropagation(); onClick(s.id) }}
      title={`#${s.index} ${s.text?.slice(0, 40)}`}>
      {widthPx > 25 && (
        <span className="text-[10px] px-1 truncate w-full block font-semibold leading-tight"
          style={{ color: isActive ? '#fff' : color, marginTop: 2 }}>
          {s.text?.slice(0, 30)}
        </span>
      )}
    </div>
  )
})

// ─── Audio block (hàng dưới) ───────────────────────────────────────────────
interface AudioBlockProps {
  s: Subtitle
  lane: number
  isActive: boolean
  isPlaying: boolean
  isDragging: boolean
  isOverlap: boolean
  pxPerSec: number
  audioTopOffset: number
  onClick: (id: number) => void
  onDragStart: (e: React.MouseEvent, s: Subtitle) => void
  blockRef?: React.RefObject<HTMLDivElement>
}
const AudioBlock = React.memo(function AudioBlock({
  s, lane, isActive, isPlaying, isDragging, isOverlap, pxPerSec, audioTopOffset, onClick, onDragStart, blockRef,
}: AudioBlockProps) {
  const offset    = s.audio_offset || 0
  const start     = s.start_time + offset
  const dur       = s.wav_duration ?? (s.end_time - s.start_time)
  const char      = s.character

  const leftPx  = Math.round(start * pxPerSec)
  const widthPx = Math.max(30, Math.round(dur * pxPerSec))
  const topPx   = audioTopOffset + lane * LANE_H + 3

  const base = char?.color || '#3B82F6'
  let bg = base+'25', border = base+'70', text = '#94A3B8'
  if (isOverlap && !isActive && !isPlaying) { bg='#450A0A80'; border='#EF4444'; text='#FCA5A5' }
  if (isActive)   { bg='#1E3A8A50'; border='#60A5FA'; text='#BFDBFE' }
  if (isPlaying)  { bg='#052E1660'; border='#10B981'; text='#6EE7B7' }
  if (isDragging) { bg='#2E1065cc'; border='#A78BFA'; text='#DDD6FE' }

  return (
    <div
      ref={blockRef}
      data-audio-block="1"
      className="absolute rounded flex items-center overflow-hidden select-none"
      style={{
        left: leftPx, width: widthPx, top: topPx, height: LANE_H-6,
        background: bg, border: `1.5px solid ${border}`,
        cursor: isDragging ? 'grabbing' : 'grab',
        boxShadow: isPlaying ? `0 0 8px ${border}60`
          : isOverlap && !isActive ? `inset 0 0 0 1px #EF4444, 0 0 0 2px #EF444430` : 'none',
        zIndex: isDragging ? 30 : isActive||isPlaying ? 10 : isOverlap ? 5 : 1,
        transition: isDragging ? 'none' : 'border-color 0.15s',
      }}
      title={`#${s.index} ${char?.name||''} | ${dur.toFixed(2)}s`}
      onClick={e => { e.stopPropagation(); onClick(s.id) }}
      onMouseDown={e => onDragStart(e, s)}>

      {/* PERF: ĐÃ BỎ "fake waveform" 40 bars/block — tiết kiệm 240k DOM nodes
          với 6000 audio. Nếu muốn waveform thật, render bằng SVG path từ
          peak data, chỉ khi block trong viewport và đủ rộng. */}

      {isPlaying && (
        <div className="flex items-end gap-px ml-1.5 flex-shrink-0 z-10" style={{ height: 16 }}>
          {[5,9,13,10,6].map((h,i) => (
            <div key={i} className="w-0.5 rounded-full animate-bounce"
              style={{ height: h, background: border, animationDelay: `${i*0.08}s` }}/>
          ))}
        </div>
      )}

      {isOverlap && !isPlaying && !isDragging && <span className="ml-1 text-[10px] flex-shrink-0 z-10">⚠</span>}

      <span className="px-1.5 text-[11px] font-bold truncate flex-1 z-10" style={{ color: text }}>
        #{s.index}{char?.name ? ` · ${char.name}` : ''}
      </span>

      {widthPx > 60 && (
        <span className="text-[9px] pr-1 flex-shrink-0 z-10 tabular-nums opacity-60" style={{ color: text }}>
          {dur.toFixed(1)}s
        </span>
      )}

      {Math.abs(offset) > 0.05 && widthPx > 80 && (
        <span className="text-[9px] pr-1 flex-shrink-0 z-10 tabular-nums font-medium" style={{ color: '#F59E0B' }}>
          {offset > 0 ? '+' : ''}{offset.toFixed(1)}s
        </span>
      )}
    </div>
  )
})

// ─── Main ──────────────────────────────────────────────────────────────────
export default function AudioList() {
  // PERF: selectors riêng — KHÔNG destructure useStore()
  const subtitles = useStore(s => s.subtitles)
  const activeSubId = useStore(s => s.activeSubId)
  const setActiveSubId = useStore(s => s.setActiveSubId)
  const updateSubtitle = useStore(s => s.updateSubtitle)

  const [playingId,  setPlayingId]  = useState<number | null>(null)
  const [draggingId, setDraggingId] = useState<number | null>(null)
  const [height, setHeight]         = useState(DEFAULT_H)
  const [zoom, setZoom]             = useState(1)
  const [scrollLeft, setScrollLeft] = useState(0)
  const [viewportWidth, setViewportWidth] = useState(2000)

  const scrollRef    = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const resizeRef    = useRef<{ startY: number; startH: number } | null>(null)
  const zoomRef      = useRef(zoom); zoomRef.current = zoom
  const snapLanesRef   = useRef<Map<number, number>>(new Map())
  const dragBlockRef   = useRef<HTMLDivElement | null>(null)
  const userInteractingRef = useRef(false)
  const isDraggingRef  = useRef(false)
  const scrollRafRef   = useRef<number | null>(null)

  // PERF: pub/sub thay setInterval(150ms)
  useEffect(() => subscribePlayingId(setPlayingId), [])

  const withAudio = useMemo(() =>
    subtitles.filter(s => s.tts_done && s.audio_path), [subtitles])

  const withDur = useMemo(() =>
    withAudio.map(s => ({ ...s, wav_duration: s.wav_duration ?? (s.end_time - s.start_time) })),
    [withAudio])

  const computedLanes = useMemo(() => assignLanes(withDur), [withDur])
  const lanes    = draggingId ? snapLanesRef.current : computedLanes

  // PERF: O(n log n) sweep thay O(n²)
  const overlaps = useMemo(() => findOverlapsSweep(withDur), [withDur])

  const maxLane  = useMemo(() => {
    if (!withAudio.length) return 0
    // PERF: maxOf reduce thay vì Math.max(...arr) spread
    const vals = Array.from(lanes.values())
    return Math.max(0, maxOf(vals))
  }, [lanes, withAudio.length])

  const totalDur = useMemo(() => {
    if (!subtitles.length && !withDur.length) return 60
    let m = 0
    for (const s of withDur) {
      const e = s.start_time + (s.audio_offset||0) + (s.wav_duration ?? (s.end_time - s.start_time))
      if (e > m) m = e
    }
    for (const s of subtitles) {
      if (s.end_time > m) m = s.end_time
    }
    return m + 5
  }, [withDur, subtitles])

  const pxPerSec     = PX_PER_SEC * zoom
  const totalWidth   = Math.ceil(totalDur * pxPerSec) + 40
  const audioTopOffset = SUB_ROW_H + 4

  // ─── Viewport tracking — chỉ render block trong vùng nhìn thấy ─────────
  // PERF: với 6000 audio blocks, render hết là 6000+ DOM nodes. Chỉ render
  // các block visible (+ buffer 1 viewport hai bên để smooth scroll).
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const updateViewport = () => {
      setViewportWidth(el.clientWidth)
      setScrollLeft(el.scrollLeft)
    }
    updateViewport()

    const onScroll = () => {
      // RAF throttle — tránh setState 60+/giây
      if (scrollRafRef.current) return
      scrollRafRef.current = requestAnimationFrame(() => {
        scrollRafRef.current = null
        if (el) setScrollLeft(el.scrollLeft)
      })
    }
    el.addEventListener('scroll', onScroll, { passive: true })

    const ro = new ResizeObserver(() => setViewportWidth(el.clientWidth))
    ro.observe(el)

    return () => {
      el.removeEventListener('scroll', onScroll)
      ro.disconnect()
      if (scrollRafRef.current) cancelAnimationFrame(scrollRafRef.current)
    }
  }, [])

  // Buffer = 1 viewport hai bên → smooth khi scroll nhanh
  const visibleRange = useMemo(() => {
    const buffer = viewportWidth
    const fromPx = scrollLeft - buffer
    const toPx   = scrollLeft + viewportWidth + buffer
    return {
      fromSec: fromPx / pxPerSec,
      toSec:   toPx / pxPerSec,
    }
  }, [scrollLeft, viewportWidth, pxPerSec])

  // PERF: lọc subtitles & audio blocks theo viewport
  // Subtitles ngắn (vài giây), filter tuyến tính ổn. Nếu sau này chậm hơn,
  // chuyển sang interval tree.
  const visibleSubs = useMemo(() => {
    return subtitles.filter(s =>
      s.end_time >= visibleRange.fromSec && s.start_time <= visibleRange.toSec
    )
  }, [subtitles, visibleRange.fromSec, visibleRange.toSec])

  const visibleAudio = useMemo(() => {
    return withDur.filter(s => {
      const start = s.start_time + (s.audio_offset || 0)
      const end = start + (s.wav_duration ?? (s.end_time - s.start_time))
      return end >= visibleRange.fromSec && start <= visibleRange.toSec
    })
  }, [withDur, visibleRange.fromSec, visibleRange.toSec])

  // Block browser Ctrl+zoom
  useEffect(() => {
    const el = containerRef.current; if (!el) return
    const block = (e: WheelEvent) => { if (e.ctrlKey) e.preventDefault() }
    el.addEventListener('wheel', block, { passive: false })
    return () => el.removeEventListener('wheel', block)
  }, [])

  // Ctrl+scroll zoom
  useEffect(() => {
    const el = scrollRef.current; if (!el) return
    const fn = (e: WheelEvent) => {
      if (e.ctrlKey) {
        e.preventDefault()
        const rect    = el.getBoundingClientRect()
        const mouseX  = e.clientX - rect.left
        const timeSec = (el.scrollLeft + mouseX) / (PX_PER_SEC * zoomRef.current)
        const factor  = e.deltaY > 0 ? 0.85 : 1.18
        const newZoom = Math.max(0.2, Math.min(5, zoomRef.current * factor))
        setZoom(newZoom)
        requestAnimationFrame(() => { el.scrollLeft = Math.max(0, timeSec * PX_PER_SEC * newZoom - mouseX) })
      } else {
        e.preventDefault()
        el.scrollLeft += e.deltaY || e.deltaX
      }
    }
    el.addEventListener('wheel', fn, { passive: false })
    return () => el.removeEventListener('wheel', fn)
  }, [])

  const zoomBy = useCallback((factor: number) => {
    const el = scrollRef.current
    const anchorSec = el ? (el.scrollLeft + el.clientWidth / 2) / (PX_PER_SEC * zoomRef.current) : 0
    const newZoom   = Math.max(0.2, Math.min(5, zoomRef.current * factor))
    setZoom(newZoom)
    if (el) requestAnimationFrame(() => {
      el.scrollLeft = Math.max(0, anchorSec * PX_PER_SEC * newZoom - el.clientWidth / 2)
    })
  }, [])

  // Auto scroll theo activeSubId
  // PERF: bỏ setTimeout(60) — gây trễ rõ khi click sub
  // PERF: bỏ behavior:'smooth' — smooth scroll bắn ~30 scroll events trong ~400ms
  //       mỗi event re-compute visibleRange → re-filter audio blocks → re-render.
  //       Với 6000 subs và viewport virtualization, smooth scroll = layout thrash.
  // PERF: dùng ref để đọc start_time hiện tại của activeSub thay vì subtitles dep —
  //       subtitles đổi mỗi lần TTS xong, không nên trigger lại scroll.
  const subtitlesRef = useRef(subtitles)
  subtitlesRef.current = subtitles

  useEffect(() => {
    if (!activeSubId || isDraggingRef.current) return
    const sub = subtitlesRef.current.find(s => s.id === activeSubId)
    if (!sub) return
    const el = scrollRef.current; if (!el) return

    const offset = (sub as any).audio_offset || 0
    const px = (sub.start_time + offset) * pxPerSec

    // Chỉ scroll khi sub ngoài viewport (giữ logic cũ)
    if (px < el.scrollLeft + 20 || px > el.scrollLeft + el.clientWidth - 80) {
      // Instant scroll — nhanh hơn smooth ~10x với big lists
      el.scrollLeft = Math.max(0, px - el.clientWidth / 3)
    }
  }, [activeSubId, pxPerSec])

  // Resize
  const onResizeDown = (e: React.MouseEvent) => {
    e.preventDefault()
    resizeRef.current = { startY: e.clientY, startH: height }
    const onMove = (ev: MouseEvent) => {
      if (!resizeRef.current) return
      setHeight(Math.max(MIN_H, Math.min(MAX_H, resizeRef.current.startH - (ev.clientY - resizeRef.current.startY))))
    }
    const onUp = () => { resizeRef.current = null; document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  // Drag block — DOM only trong onMove, React update khi mouseup
  const startDrag = useCallback((e: React.MouseEvent, sub: any) => {
    e.preventDefault(); e.stopPropagation()
    const startX   = e.clientX
    const startOff = sub.audio_offset || 0
    const pps      = PX_PER_SEC * zoomRef.current
    snapLanesRef.current  = new Map(computedLanes)
    isDraggingRef.current = true
    setDraggingId(sub.id)

    const onMove = (ev: MouseEvent) => {
      const newOff = Math.max(-sub.start_time, startOff + (ev.clientX - startX) / pps)
      if (dragBlockRef.current)
        dragBlockRef.current.style.left = Math.round((sub.start_time + newOff) * pps) + 'px'
    }
    const onUp = async (ev: MouseEvent) => {
      const newOff  = Math.max(-sub.start_time, startOff + (ev.clientX - startX) / pps)
      const rounded = Math.round(newOff * 100) / 100
      dragBlockRef.current = null
      setDraggingId(null)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
      userInteractingRef.current = true
      updateSubtitle(sub.id, { audio_offset: rounded })
      await api.patch(`/subtitles/${sub.id}`, { audio_offset: rounded })
      isDraggingRef.current = false
      setTimeout(() => { userInteractingRef.current = false }, 2000)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [computedLanes, updateSubtitle])

  // Ruler — chỉ render ticks trong viewport
  const tickInterval = pxPerSec >= 60 ? 1 : pxPerSec >= 20 ? 5 : 10
  const ticks = useMemo(() => {
    const fromTick = Math.max(0, Math.floor(visibleRange.fromSec / tickInterval) * tickInterval)
    const toTick = Math.ceil(Math.min(totalDur, visibleRange.toSec) / tickInterval) * tickInterval
    const arr: number[] = []
    for (let t = fromTick; t <= toTick; t += tickInterval) arr.push(t)
    return arr
  }, [visibleRange.fromSec, visibleRange.toSec, totalDur, tickInterval])

  return (
    <div ref={containerRef} style={{display:'contents'}}>
      <div onMouseDown={onResizeDown}
        className="border-t border-zinc-700 bg-zinc-800/60 flex-shrink-0 cursor-row-resize flex items-center justify-center group hover:bg-blue-900/40 transition-colors"
        style={{ height: RESIZE_H }}>
        <div className="flex gap-1">
          {[0,1,2,3,4].map(i => <div key={i} className="w-4 h-px bg-zinc-600 group-hover:bg-blue-400 transition-colors"/>)}
        </div>
      </div>

      <div className="bg-[#0F172A] flex-shrink-0 flex flex-col overflow-hidden" style={{ height }}>

        {/* Header */}
        <div className="flex items-center justify-between px-3 flex-shrink-0 border-b border-zinc-800/60"
          style={{ height: HEADER_H }}>
          <div className="flex items-center gap-3">
            <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">🎵 Audio Timeline</span>
            <span className="text-[10px] text-slate-600">{withAudio.length} audio · {maxLane + 1} lane{maxLane > 0 ? 's' : ''}</span>
          </div>
          <div className="flex items-center gap-2">
            {overlaps.size > 0 && (
              <div className="flex items-center gap-1.5 px-2 py-0.5 rounded bg-red-950/60 border border-red-800/50">
                <div className="w-1.5 h-1.5 rounded-full bg-red-500 animate-pulse"/>
                <span className="text-[10px] text-red-400 font-medium">{overlaps.size} chồng lấn</span>
              </div>
            )}
            <div className="flex items-center gap-1">
              <button onClick={() => zoomBy(0.8)} className="w-5 h-5 rounded text-[11px] text-zinc-400 hover:bg-zinc-700 hover:text-white flex items-center justify-center">−</button>
              <span className="text-[9px] text-zinc-500 tabular-nums w-8 text-center">{Math.round(zoom*100)}%</span>
              <button onClick={() => zoomBy(1.25)} className="w-5 h-5 rounded text-[11px] text-zinc-400 hover:bg-zinc-700 hover:text-white flex items-center justify-center">+</button>
              <button onClick={() => { setZoom(1); requestAnimationFrame(() => { if (scrollRef.current) scrollRef.current.scrollLeft = 0 }) }}
                className="w-5 h-5 rounded text-[9px] text-zinc-500 hover:bg-zinc-700 hover:text-white flex items-center justify-center">↺</button>
            </div>
          </div>
        </div>

        {/* Scroll */}
        <div ref={scrollRef} className="flex-1 overflow-x-auto overflow-y-hidden"
          style={{ scrollbarWidth: 'thin', scrollbarColor: '#475569 #0F172A' }}
          onMouseDown={() => { userInteractingRef.current = true }}
          onMouseUp={() => { setTimeout(() => { userInteractingRef.current = false }, 1000) }}
          onClick={e => {
            const target = e.target as HTMLElement
            if (target.closest('[data-audio-block]')) return
            const el = scrollRef.current; if (!el) return
            const rect    = el.getBoundingClientRect()
            const clickX  = e.clientX - rect.left + el.scrollLeft
            const timeSec = clickX / pxPerSec
            const video   = document.querySelector('video') as HTMLVideoElement | null
            if (video) video.currentTime = Math.max(0, timeSec)
          }}>
          <div className="relative" style={{ width: totalWidth, height: '100%', minHeight: audioTopOffset + (maxLane+1)*LANE_H + 8 }}>

            {/* Hàng phụ đề — chỉ render visibleSubs */}
            <div className="absolute left-0 right-0 border-b border-zinc-800/60"
              style={{ top: 0, height: SUB_ROW_H, background: 'rgba(15,23,42,0.9)' }}>
              {visibleSubs.map(s => (
                <SubBar key={s.id}
                  s={s}
                  isActive={s.id === activeSubId}
                  pxPerSec={pxPerSec}
                  onClick={setActiveSubId} />
              ))}
            </div>

            {/* Lane backgrounds */}
            {Array.from({ length: maxLane+1 }, (_, i) => (
              <div key={i} className="absolute left-0 right-0"
                style={{ top: audioTopOffset + i*LANE_H, height: LANE_H,
                  background: i%2===0 ? 'rgba(255,255,255,0.015)' : 'transparent',
                  borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                <span className="text-[8px] text-slate-800 ml-1 select-none" style={{ lineHeight: LANE_H+'px' }}>L{i+1}</span>
              </div>
            ))}

            {/* Ruler — chỉ ticks visible */}
            {ticks.map(sec => {
              const x = sec * pxPerSec
              const isMajor = sec % (tickInterval*5) === 0 || tickInterval >= 5
              return (
                <div key={sec} className="absolute top-0 bottom-0 pointer-events-none" style={{ left: x }}>
                  <div className="absolute top-0 bottom-0 w-px"
                    style={{ background: isMajor ? 'rgba(100,116,139,0.2)' : 'rgba(100,116,139,0.06)' }}/>
                  {isMajor && (
                    <span className="absolute text-[8px] text-slate-600 tabular-nums select-none whitespace-nowrap"
                      style={{ top: SUB_ROW_H + 2, left: 2 }}>
                      {Math.floor(sec/60)}:{String(sec%60).padStart(2,'0')}
                    </span>
                  )}
                </div>
              )
            })}

            {/* Playhead — subscribe playTime store riêng */}
            <Playhead pxPerSec={pxPerSec} />

            {/* Empty state */}
            {withAudio.length === 0 && (
              <div className="absolute inset-0 flex items-center justify-center pointer-events-none"
                style={{ top: audioTopOffset }}>
                <span className="text-[11px] text-zinc-600">Chưa có audio — bấm TTS để tạo</span>
              </div>
            )}

            {/* Audio blocks — chỉ render visibleAudio */}
            {visibleAudio.map(s => {
              const lane = lanes.get(s.id) ?? 0
              return (
                <AudioBlock key={s.id}
                  s={s}
                  lane={lane}
                  isActive={s.id === activeSubId}
                  isPlaying={s.id === playingId}
                  isDragging={s.id === draggingId}
                  isOverlap={overlaps.has(s.id)}
                  pxPerSec={pxPerSec}
                  audioTopOffset={audioTopOffset}
                  onClick={setActiveSubId}
                  onDragStart={startDrag}
                  blockRef={s.id === draggingId ? (dragBlockRef as any) : undefined}
                />
              )
            })}
          </div>
        </div>
      </div>
    </div>
  )
}
