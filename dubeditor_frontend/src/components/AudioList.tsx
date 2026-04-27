import React, { useRef, useEffect, useState, useCallback, useMemo } from 'react'
import useStore from '../store'
import api from '../api'

let _globalAudio: HTMLAudioElement | null = null
let _globalPlayingId: number | null = null

export function playSubAudio(subId: number, audioPath: string, onEnd?: () => void): boolean {
  if (_globalPlayingId === subId && _globalAudio && !_globalAudio.paused) {
    _globalAudio.pause(); _globalAudio.currentTime = 0
    _globalAudio = null; _globalPlayingId = null; return false
  }
  if (_globalAudio) { _globalAudio.pause(); _globalAudio = null; _globalPlayingId = null }
  const audio = new Audio(`${audioPath}?t=${Date.now()}`)
  _globalAudio = audio; _globalPlayingId = subId
  audio.play().catch(() => {})
  audio.onended = () => { _globalAudio = null; _globalPlayingId = null; onEnd?.() }
  return true
}
export function stopGlobalAudio() {
  if (_globalAudio) { _globalAudio.pause(); _globalAudio = null; _globalPlayingId = null }
}
export function getGlobalPlayingId() { return _globalPlayingId }

const PX_PER_SEC = 120
const SUB_ROW_H  = 26
const LANE_H     = 36
const HEADER_H   = 24
const RESIZE_H   = 6
const DEFAULT_H  = 200
const MIN_H      = 100
const MAX_H      = 500

function assignLanes(subs: any[]): Map<number, number> {
  const lanes = new Map<number, number>()
  const laneEnds: number[] = []
  const sorted = [...subs].sort((a, b) =>
    (a.start_time + (a.audio_offset||0)) - (b.start_time + (b.audio_offset||0)))
  for (const s of sorted) {
    const start = s.start_time + (s.audio_offset || 0)
    const end   = start + (s.wav_duration ?? (s.end_time - s.start_time))
    let lane = 0
    while (lane < laneEnds.length && laneEnds[lane] > start + 0.01) lane++
    lanes.set(s.id, lane)
    laneEnds[lane] = end
  }
  return lanes
}

function findOverlaps(subs: any[]): Set<number> {
  const overlaps = new Set<number>()
  for (let i = 0; i < subs.length; i++) {
    for (let j = i + 1; j < subs.length; j++) {
      const a = subs[i], b = subs[j]
      const aS = a.start_time+(a.audio_offset||0)
      const aE = aS + (a.wav_duration ?? (a.end_time - a.start_time))
      const bS = b.start_time+(b.audio_offset||0)
      const bE = bS + (b.wav_duration ?? (b.end_time - b.start_time))
      if (aS < bE - 0.01 && aE > bS + 0.01) { overlaps.add(a.id); overlaps.add(b.id) }
    }
  }
  return overlaps
}

export default function AudioList() {
  const { subtitles, activeSubId, setActiveSubId, updateSubtitle, playTime } = useStore()
  const [playingId,  setPlayingId]  = useState<number | null>(null)
  const [draggingId, setDraggingId] = useState<number | null>(null)
  const [height, setHeight]         = useState(DEFAULT_H)
  const [zoom, setZoom]             = useState(1)
  const scrollRef    = useRef<HTMLDivElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const resizeRef    = useRef<{ startY: number; startH: number } | null>(null)
  const zoomRef      = useRef(zoom)
  zoomRef.current    = zoom
  const snapLanesRef   = useRef<Map<number, number>>(new Map())
  const dragBlockRef   = useRef<HTMLDivElement | null>(null)
  const userInteractingRef = useRef(false)
  const isDraggingRef  = useRef(false)

  const withAudio = useMemo(() =>
    subtitles.filter(s => s.tts_done && s.audio_path), [subtitles])

  const withDur = useMemo(() =>
    withAudio.map(s => ({ ...s, wav_duration: s.wav_duration ?? (s.end_time - s.start_time) })),
    [withAudio])

  const computedLanes = useMemo(() => assignLanes(withDur), [withDur])
  const lanes    = draggingId ? snapLanesRef.current : computedLanes
  const overlaps = useMemo(() => findOverlaps(withDur), [withDur])
  const maxLane  = useMemo(() =>
    withAudio.length ? Math.max(0, ...Array.from(lanes.values())) : 0, [lanes, withAudio])

  const totalDur = useMemo(() => {
    const ends = [
      ...withDur.map(s => s.start_time + (s.audio_offset||0) + (s.wav_duration ?? (s.end_time - s.start_time))),
      ...subtitles.map(s => s.end_time)
    ]
    return ends.length ? Math.max(...ends) + 5 : 60
  }, [withDur, subtitles])

  const pxPerSec     = PX_PER_SEC * zoom
  const totalWidth   = Math.ceil(totalDur * pxPerSec) + 40
  const audioTopOffset = SUB_ROW_H + 4

  useEffect(() => {
    const id = setInterval(() => setPlayingId(getGlobalPlayingId()), 150)
    return () => clearInterval(id)
  }, [])

  // Block browser Ctrl+zoom
  useEffect(() => {
    const el = containerRef.current; if (!el) return
    const block = (e: WheelEvent) => { if (e.ctrlKey) e.preventDefault() }
    el.addEventListener('wheel', block, { passive: false })
    return () => el.removeEventListener('wheel', block)
  }, [])

  // Ctrl+scroll zoom anchor tại con trỏ
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

  // Zoom +/- giữ center
  const zoomBy = useCallback((factor: number) => {
    const el = scrollRef.current
    const anchorSec = el ? (el.scrollLeft + el.clientWidth / 2) / (PX_PER_SEC * zoomRef.current) : 0
    const newZoom   = Math.max(0.2, Math.min(5, zoomRef.current * factor))
    setZoom(newZoom)
    if (el) requestAnimationFrame(() => {
      el.scrollLeft = Math.max(0, anchorSec * PX_PER_SEC * newZoom - el.clientWidth / 2)
    })
  }, [])

  // Auto scroll theo activeSubId — dùng subtitles để tìm kể cả sub chưa có audio
  useEffect(() => {
    if (!activeSubId || isDraggingRef.current) return
    const sub = subtitles.find(s => s.id === activeSubId); if (!sub) return
    setTimeout(() => {
      const el = scrollRef.current; if (!el) return
      const offset = (sub as any).audio_offset || 0
      const px = (sub.start_time + offset) * pxPerSec
      if (px < el.scrollLeft + 20 || px > el.scrollLeft + el.clientWidth - 80)
        el.scrollTo({ left: Math.max(0, px - el.clientWidth / 3), behavior: 'smooth' })
    }, 60)
  }, [activeSubId])

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

  // Drag: DOM only trong onMove, React update khi mouseup
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
      // Block playhead auto-scroll 2s sau khi thả
      userInteractingRef.current = true
      updateSubtitle(sub.id, { audio_offset: rounded })
      await api.patch(`/subtitles/${sub.id}`, { audio_offset: rounded })
      isDraggingRef.current = false
      setTimeout(() => { userInteractingRef.current = false }, 2000)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }, [computedLanes, updateSubtitle])

  if (withAudio.length === 0) {
    return (
      <>
        <div onMouseDown={onResizeDown}
          className="border-t border-zinc-700 bg-zinc-800/50 flex-shrink-0 cursor-row-resize flex items-center justify-center hover:bg-blue-900/30 transition-colors"
          style={{ height: RESIZE_H }}>
          <div className="flex gap-1">{[0,1,2,3].map(i => <div key={i} className="w-4 h-px bg-zinc-600"/>)}</div>
        </div>
        <div className="bg-[#0F172A] flex-shrink-0 flex items-center justify-center" style={{ height }}>
          <span className="text-[11px] text-zinc-500">Chưa có audio — bấm TTS để tạo</span>
        </div>
      </>
    )
  }

  const tickInterval = pxPerSec >= 60 ? 1 : pxPerSec >= 20 ? 5 : 10
  const ticks = Array.from({ length: Math.ceil(totalDur / tickInterval) + 1 }, (_, i) => i * tickInterval)

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

            {/* ── Hàng phụ đề ── */}
            <div className="absolute left-0 right-0 border-b border-zinc-800/60"
              style={{ top: 0, height: SUB_ROW_H, background: 'rgba(15,23,42,0.9)' }}>
              {subtitles.map(s => {
                const leftPx  = Math.round(s.start_time * pxPerSec)
                const widthPx = Math.max(2, Math.round((s.end_time - s.start_time) * pxPerSec))
                const isActive = s.id === activeSubId
                const color    = s.character?.color || '#475569'
                return (
                  <div key={s.id}
                    className="absolute top-0.5 rounded-sm cursor-pointer overflow-hidden"
                    style={{
                      left: leftPx, width: widthPx, height: SUB_ROW_H - 4,
                      background: color + (isActive ? 'cc' : '35'),
                      border: `1px solid ${color}${isActive ? 'ff' : '55'}`,
                      zIndex: isActive ? 5 : 1,
                    }}
                    onClick={e => { e.stopPropagation(); setActiveSubId(s.id) }}
                    title={`#${s.index} ${s.text?.slice(0, 40)}`}>
                    {widthPx > 25 && (
                      <span className="text-[10px] px-1 truncate w-full block font-semibold leading-tight"
                        style={{ color: isActive ? '#fff' : color, marginTop: 2 }}>
                        {s.text?.slice(0, 30)}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>

            {/* ── Lane backgrounds ── */}
            {Array.from({ length: maxLane+1 }, (_, i) => (
              <div key={i} className="absolute left-0 right-0"
                style={{ top: audioTopOffset + i*LANE_H, height: LANE_H,
                  background: i%2===0 ? 'rgba(255,255,255,0.015)' : 'transparent',
                  borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                <span className="text-[8px] text-slate-800 ml-1 select-none" style={{ lineHeight: LANE_H+'px' }}>L{i+1}</span>
              </div>
            ))}

            {/* ── Ruler ── */}
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

            {/* ── Playhead ── */}
            <div className="absolute top-0 bottom-0 pointer-events-none z-20"
              style={{ left: Math.round(playTime * pxPerSec), width: 1 }}>
              <div className="absolute top-0 bottom-0 w-px bg-red-500 opacity-90"/>
              <div className="absolute w-0 h-0 border-l-[4px] border-r-[4px] border-t-[6px] border-l-transparent border-r-transparent border-t-red-500"
                style={{ top: 0, left: -3.5 }}/>
            </div>

            {/* ── Audio blocks ── */}
            {withDur.map(s => {
              const lane      = lanes.get(s.id) ?? 0
              const offset    = s.audio_offset || 0
              const start     = s.start_time + offset
              const dur       = s.wav_duration ?? (s.end_time - s.start_time)
              const isActive   = s.id === activeSubId
              const isPlaying  = s.id === playingId
              const isDragging = s.id === draggingId
              const isOverlap  = overlaps.has(s.id)
              const char = s.character

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
                <div key={s.id}
                  ref={isDragging ? dragBlockRef : null}
                  data-audio-block="1"
                  className="absolute rounded flex items-center overflow-hidden select-none"
                  style={{ left: leftPx, width: widthPx, top: topPx, height: LANE_H-6,
                    background: bg, border: `1.5px solid ${border}`,
                    cursor: isDragging ? 'grabbing' : 'grab',
                    boxShadow: isPlaying ? `0 0 8px ${border}60`
                      : isOverlap && !isActive ? `inset 0 0 0 1px #EF4444, 0 0 0 2px #EF444430` : 'none',
                    zIndex: isDragging ? 30 : isActive||isPlaying ? 10 : isOverlap ? 5 : 1,
                    transition: isDragging ? 'none' : 'border-color 0.15s',
                  }}
                  title={`#${s.index} ${char?.name||''} | ${dur.toFixed(2)}s`}
                  onClick={e => { e.stopPropagation(); setActiveSubId(s.id) }}
                  onMouseDown={e => startDrag(e, s)}>

                  <div className="absolute inset-0 flex items-center justify-around px-1 pointer-events-none opacity-20">
                    {Array.from({ length: Math.min(40, Math.ceil(widthPx/5)) }, (_, i) => (
                      <div key={i} className="flex-shrink-0 rounded-full" style={{ width: 2,
                        height: `${25+Math.abs(Math.sin(i*0.7+s.id))*50+Math.abs(Math.cos(i*1.1))*25}%`,
                        background: border }}/>
                    ))}
                  </div>

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
            })}
          </div>
        </div>
      </div>
    </div>
  )
}