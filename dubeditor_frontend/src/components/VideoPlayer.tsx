import React, { useRef, useEffect, useState, useCallback } from 'react'
import useStore, { usePlayTimeStore } from '../store'

// wav_duration lấy từ subtitle.wav_duration (backend)

// ─── TTS Engine ───────────────────────────────────────────────────────────────
class TTSEngine {
  private slots = new Map<number, HTMLAudioElement>()
  private volume = 1.0
  private enabled = true
  private playing = false
  version = 0  // tăng khi gen lại audio

  setVolume(v: number) { this.volume = v; this.slots.forEach(a => a.volume = v) }
  setEnabled(e: boolean) { this.enabled = e; if (!e) this.stopAll() }
  setPlaying(p: boolean) { this.playing = p; if (!p) this.stopAll() }
  bumpVersion() { this.version++; this.stopAll() }

  // PERF: với 6000 subs, duyệt full mỗi 100ms = 60k ops/giây. Dùng binary search
  // để giới hạn duyệt trong cửa sổ ~30s quanh currentTime (subs đã sort theo start_time).
  tick(currentTime: number, subtitles: any[]) {
    if (!this.enabled || !this.playing) return
    const ver = this.version
    const n = subtitles.length
    if (!n) return

    // Tìm index của sub đầu tiên có start_time >= currentTime - WINDOW
    // WINDOW = max wav duration possible (~30s là rộng rãi cho dubbing)
    const WINDOW_BACK = 30
    const target = currentTime - WINDOW_BACK
    let lo = 0, hi = n - 1, startIdx = n
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      const t = subtitles[mid].start_time + (subtitles[mid].audio_offset || 0)
      if (t >= target) { startIdx = mid; hi = mid - 1 }
      else lo = mid + 1
    }

    // Duyệt từ startIdx, dừng khi start > currentTime + 0.5s (xa quá phía sau)
    for (let i = startIdx; i < n; i++) {
      const s = subtitles[i]
      const offset  = s.audio_offset || 0
      const start   = s.start_time + offset
      if (start > currentTime + 0.5) break  // mọi sub sau nữa đều xa hơn

      if (!s.tts_done || !s.audio_path) continue

      const wavDur  = s.wav_duration ?? (s.end_time - s.start_time)
      const realEnd = start + wavDur
      const playing = this.slots.get(s.id)

      if (currentTime >= start && currentTime < realEnd) {
        if (!playing) {
          const seekTo = currentTime - start
          if (seekTo >= wavDur) continue
          const url = `${s.audio_path}?v=${ver}`
          const el = new Audio(url)
          el.volume = this.volume
          el.preload = 'auto'
          el.addEventListener('canplay', () => {
            if (seekTo > 0.15) {
              el.currentTime = seekTo
            }
            el.play().catch(() => {})
          }, { once: true })
          el.load()
          el.onended = () => { if (this.slots.get(s.id) === el) this.slots.delete(s.id) }
          this.slots.set(s.id, el)
        }
      } else {
        if (playing) {
          if (currentTime < start - 0.5) {
            playing.pause()
            this.slots.delete(s.id)
          }
        }
      }
    }
  }

  stopAll() {
    this.slots.forEach(a => a.pause())
    this.slots.clear()
  }
}

const ttsEngine = new TTSEngine()
export { ttsEngine }

// ─── Component ────────────────────────────────────────────────────────────────
export default function VideoPlayer() {
  const videoRef    = useRef<HTMLVideoElement>(null)
  const progressRef = useRef<HTMLDivElement>(null)
  const draggingRef = useRef(false)
  const durationRef = useRef(0)
  const isPlayingRef = useRef(false)

  const [playing, setPlaying]         = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration]       = useState(0)
  const [videoVol, setVideoVol]       = useState(1)
  const [ttsVol, setTtsVol]           = useState(1)
  const [ttsEnabled, setTtsEnabled]   = useState(true)
  const [draggingUI, setDraggingUI]   = useState(false)

  // PERF: selectors riêng — KHÔNG destructure useStore()
  const project = useStore(s => s.project)
  const subtitles = useStore(s => s.subtitles)
  const activeSubId = useStore(s => s.activeSubId)
  const seekRequest = useStore(s => s.seekRequest)
  const clearSeekRequest = useStore(s => s.clearSeekRequest)
  const lastTtsAt = useStore(s => s.lastTtsAt)

  // Khi gen lại audio → bump version → engine dùng URL mới
  useEffect(() => {
    if (!lastTtsAt) return
    ttsEngine.bumpVersion()
  }, [lastTtsAt])

  useEffect(() => { ttsEngine.setVolume(ttsVol) }, [ttsVol])
  useEffect(() => { ttsEngine.setEnabled(ttsEnabled) }, [ttsEnabled])

  // TTS tick — setInterval hoạt động khi tab ẩn
  useEffect(() => {
    const id = setInterval(() => {
      const v = videoRef.current
      if (v && !v.paused && isPlayingRef.current) {
        ttsEngine.tick(v.currentTime, subtitles)
      }
    }, 100)
    return () => clearInterval(id)
  }, [subtitles])

  useEffect(() => {
    const v = videoRef.current
    if (!v || !project?.video_path) return
    const syncDur = () => { if (v.duration && isFinite(v.duration)) { durationRef.current = v.duration; setDuration(v.duration) } }
    const onTime  = () => { if (!draggingRef.current) { setCurrentTime(v.currentTime); usePlayTimeStore.getState().setPlayTime(v.currentTime) } }
    const onPlay  = () => { setPlaying(true);  isPlayingRef.current = true;  ttsEngine.setPlaying(true) }
    const onPause = () => { setPlaying(false); isPlayingRef.current = false; ttsEngine.setPlaying(false) }
    const onEnded = () => { setPlaying(false); isPlayingRef.current = false; ttsEngine.setPlaying(false) }
    v.addEventListener('timeupdate', onTime)
    v.addEventListener('play', onPlay)
    v.addEventListener('pause', onPause)
    v.addEventListener('ended', onEnded)
    v.addEventListener('loadedmetadata', syncDur)
    v.addEventListener('durationchange', syncDur)
    v.addEventListener('canplay', syncDur)
    if (v.readyState >= 2) syncDur()
    return () => {
      v.removeEventListener('timeupdate', onTime)
      v.removeEventListener('play', onPlay)
      v.removeEventListener('pause', onPause)
      v.removeEventListener('ended', onEnded)
      v.removeEventListener('loadedmetadata', syncDur)
      v.removeEventListener('durationchange', syncDur)
      v.removeEventListener('canplay', syncDur)
    }
  }, [project?.video_path])

  useEffect(() => {
    if (!seekRequest) return
    const v = videoRef.current; if (!v) return
    v.currentTime = seekRequest.time
    setCurrentTime(seekRequest.time)
    ttsEngine.stopAll()
    clearSeekRequest()
  }, [seekRequest?.id])

  const togglePlay = useCallback(() => {
    const v = videoRef.current; if (!v) return
    if (v.paused) v.play().catch(() => {})
    else v.pause()
  }, [])

  const skip = useCallback((s: number) => {
    const v = videoRef.current; if (!v) return
    const t = Math.max(0, Math.min(durationRef.current, v.currentTime + s))
    v.currentTime = t
    ttsEngine.stopAll()
  }, [])

  const onSeekDown = (e: React.MouseEvent) => {
    e.preventDefault()
    const v = videoRef.current; if (!v || !durationRef.current) return
    draggingRef.current = true; setDraggingUI(true)
    const calc = (cx: number) => {
      const bar = progressRef.current; if (!bar) return 0
      const r = bar.getBoundingClientRect()
      return Math.max(0, Math.min(1, (cx - r.left) / r.width)) * durationRef.current
    }
    const onMove = (ev: MouseEvent) => setCurrentTime(calc(ev.clientX))
    const onUp = (ev: MouseEvent) => {
      const t = calc(ev.clientX)
      if (v) { v.currentTime = t; ttsEngine.stopAll() }
      setCurrentTime(t)
      draggingRef.current = false; setDraggingUI(false)
      document.removeEventListener('mousemove', onMove)
      document.removeEventListener('mouseup', onUp)
    }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
    setCurrentTime(calc(e.clientX))
  }

  const fmt = (s: number) => (!s || !isFinite(s)) ? '0:00' : `${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`
  const pct = duration > 0 ? Math.min(100, currentTime / duration * 100) : 0

  return (
    <div className="flex flex-col bg-zinc-950 flex-shrink-0 select-none" style={{ height: '100%' }}>
      <div className="relative bg-black cursor-pointer flex-1 min-h-0" onClick={togglePlay}>
        {project?.video_path ? (
          <video ref={videoRef} src={project.video_path}
            className="w-full h-full object-contain block" preload="auto" playsInline />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-zinc-500 text-sm">Chưa có video</div>
        )}
        {!playing && project?.video_path && (
          <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
            <div className="w-14 h-14 rounded-full bg-black/50 flex items-center justify-center">
              <svg width="22" height="22" viewBox="0 0 22 22" fill="white"><path d="M6 4L17 11L6 18V4Z"/></svg>
            </div>
          </div>
        )}
        <ActiveSubtitleOverlay subtitles={subtitles} currentTime={currentTime} />
      </div>

      {/* Seekbar */}
      <div ref={progressRef} onMouseDown={onSeekDown}
        className="relative bg-zinc-800 cursor-pointer flex-shrink-0"
        style={{ height: draggingUI ? 8 : 5, transition: 'height 0.1s' }}>
        <div className="absolute inset-y-0 left-0 bg-blue-500 pointer-events-none" style={{ width: `${pct}%` }} />
        <div className="absolute top-1/2 -translate-y-1/2 w-3 h-3 bg-white rounded-full pointer-events-none shadow"
          style={{ left: `calc(${pct}% - 6px)`, opacity: draggingUI ? 1 : 0 }} />
        {duration > 0 && subtitles.slice(0, 500).map(s => (
          <div key={s.id} className="absolute top-0 h-full pointer-events-none" style={{
            left: `${(s.start_time / duration) * 100}%`, width: 2,
            background: s.id === activeSubId ? '#60A5FA' : s.tts_done ? 'rgba(52,211,153,0.5)' : 'rgba(255,255,255,0.12)'
          }} />
        ))}
      </div>

      {/* Controls */}
      <div className="flex items-center gap-2 px-3 pt-2 pb-1 bg-zinc-900 flex-shrink-0">
        <button onClick={() => skip(-5)} className="w-7 h-7 rounded flex items-center justify-center text-zinc-400 hover:text-white hover:bg-zinc-700 text-[11px] font-mono font-bold">‹5</button>
        <button onClick={togglePlay} className="w-9 h-9 rounded-full flex items-center justify-center bg-blue-600 hover:bg-blue-500 text-white flex-shrink-0">
          {playing
            ? <svg width="12" height="12" viewBox="0 0 12 12" fill="white"><rect x="1" y="0" width="4" height="12" rx="1"/><rect x="7" y="0" width="4" height="12" rx="1"/></svg>
            : <svg width="12" height="12" viewBox="0 0 12 12" fill="white"><path d="M2 1L11 6L2 11V1Z"/></svg>}
        </button>
        <button onClick={() => skip(5)} className="w-7 h-7 rounded flex items-center justify-center text-zinc-400 hover:text-white hover:bg-zinc-700 text-[11px] font-mono font-bold">5›</button>
        <span className="text-[11px] text-zinc-400 font-mono tabular-nums ml-1 flex-shrink-0">{fmt(currentTime)} / {fmt(duration)}</span>
      </div>

      {/* Volume */}
      <div className="flex items-center gap-3 px-3 pb-2 bg-zinc-900 flex-shrink-0">
        <div className="flex items-center gap-1.5 flex-1">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="text-zinc-400 flex-shrink-0">
            <path d="M11 5L6 9H2v6h4l5 4V5z" fill="currentColor"/>
            {videoVol > 0.05 && <path d="M15.54 8.46a5 5 0 0 1 0 7.07" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"/>}
          </svg>
          <span className="text-[9px] text-zinc-500 flex-shrink-0 w-5">VID</span>
          <input type="range" min={0} max={1} step={0.05} value={videoVol}
            onChange={e => { const v = parseFloat(e.target.value); setVideoVol(v); if (videoRef.current) videoRef.current.volume = v }}
            className="flex-1 accent-blue-500 cursor-pointer" style={{ height: 4 }} />
          <span className="text-[9px] text-zinc-500 w-5 text-right tabular-nums">{Math.round(videoVol*100)}</span>
        </div>
        <div className="w-px h-4 bg-zinc-700 flex-shrink-0" />
        <div className="flex items-center gap-1.5 flex-1">
          <svg width="13" height="13" viewBox="0 0 14 14" fill="none" className={`flex-shrink-0 ${ttsEnabled ? 'text-emerald-400' : 'text-zinc-600'}`}>
            <rect x="4.5" y="1" width="5" height="7" rx="2.5" fill="currentColor"/>
            <path d="M2.5 7C2.5 9.5 11.5 9.5 11.5 7" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
            <line x1="7" y1="9.5" x2="7" y2="12" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
          </svg>
          <span className="text-[9px] text-zinc-500 flex-shrink-0 w-5">TTS</span>
          <input type="range" min={0} max={1} step={0.05} value={ttsVol}
            onChange={e => setTtsVol(parseFloat(e.target.value))}
            className="flex-1 accent-emerald-500 cursor-pointer" style={{ height: 4 }} />
          <span className="text-[9px] text-zinc-500 w-5 text-right tabular-nums">{Math.round(ttsVol*100)}</span>
          <button onClick={() => setTtsEnabled(v => !v)}
            className={`w-8 h-5 rounded text-[9px] font-bold flex-shrink-0 ${ttsEnabled ? 'bg-emerald-600 text-white' : 'bg-zinc-700 text-zinc-400'}`}>
            {ttsEnabled ? 'ON' : 'OFF'}
          </button>
        </div>
      </div>
    </div>
  )
}

function ActiveSubtitleOverlay({ subtitles, currentTime }: { subtitles: any[], currentTime: number }) {
  const visible = subtitles.filter(s => s.start_time <= currentTime && s.end_time >= currentTime)
  if (!visible.length) return null
  return (
    <div className="absolute bottom-3 left-0 right-0 flex flex-col items-center gap-1 pointer-events-none">
      {visible.map(s => (
        <span key={s.id} className="text-white text-[14px] font-medium px-3 py-1 rounded max-w-[90%] text-center"
          style={{ background: 'rgba(0,0,0,0.75)', textShadow: '0 1px 3px #000' }}>
          {s.text}
        </span>
      ))}
    </div>
  )
}