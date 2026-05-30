import React, { useRef, useEffect, useState, useCallback } from 'react'
import useStore, { usePlayTimeStore } from '../store'
import api from '../api'

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
      // Effective speed: sub.tts_speed → character.tts_speed → 1.0
      const speed = s.tts_speed != null ? s.tts_speed
                  : (s.character?.tts_speed != null ? s.character.tts_speed : 1.0)
      const effDur = wavDur / speed  // thời lượng thực sau khi tăng tốc
      const realEnd = start + effDur
      const playing = this.slots.get(s.id)

      if (currentTime >= start && currentTime < realEnd) {
        if (!playing) {
          const seekToReal = currentTime - start  // real-world time đã trôi qua từ start
          if (seekToReal >= effDur) continue
          // audio element seek phải nhân speed (vì internal time chạy nhanh hơn)
          const seekToAudio = seekToReal * speed
          const url = `${s.audio_path}?v=${ver}`
          const el = new Audio(url)
          el.volume = this.volume
          el.playbackRate = speed
          el.preload = 'auto'
          el.addEventListener('canplay', () => {
            if (seekToAudio > 0.15) {
              el.currentTime = seekToAudio
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


// ─── Stem Engine (Bass/Drums/Vocals từ Demucs) ──────────────────────────────
// 3 audio track FULL độ dài video, sync với video.currentTime / play / pause / seek.
type StemKey = 'bass' | 'drums' | 'vocals'

class StemEngine {
  private elements: Map<StemKey, HTMLAudioElement> = new Map()
  private urls: Partial<Record<StemKey, string>> = {}
  private volumes: Record<StemKey, number> = { bass: 0.3, drums: 0.3, vocals: 0.3 }
  private enabled: Record<StemKey, boolean> = { bass: false, drums: false, vocals: false }
  private playing = false

  /** Set URL cho 1 stem. Truyền null/empty để xóa. */
  setUrl(key: StemKey, url: string | null | undefined) {
    if (this.urls[key] === url) return
    this.urls[key] = url || undefined
    // Hủy element cũ
    const oldEl = this.elements.get(key)
    if (oldEl) { try { oldEl.pause() } catch {} ; this.elements.delete(key) }
    if (!url) return
    // Tạo element mới
    const el = new Audio(url)
    el.preload = 'auto'
    el.volume = this.volumes[key]
    el.crossOrigin = 'anonymous'
    el.muted = !this.enabled[key]
    this.elements.set(key, el)
  }

  setVolume(key: StemKey, v: number) {
    this.volumes[key] = v
    const el = this.elements.get(key)
    if (el) el.volume = v
  }

  setEnabled(key: StemKey, on: boolean) {
    this.enabled[key] = on
    const el = this.elements.get(key)
    if (!el) return
    el.muted = !on
    if (!on) {
      try { el.pause() } catch {}
    } else if (this.playing) {
      el.play().catch(() => {})
    }
  }

  setPlaying(p: boolean) {
    this.playing = p
    this.elements.forEach((el, key) => {
      if (!p) {
        try { el.pause() } catch {}
      } else if (this.enabled[key]) {
        el.play().catch(() => {})
      }
    })
  }

  seek(t: number) {
    this.elements.forEach(el => {
      try { el.currentTime = Math.max(0, t) } catch {}
    })
  }

  /** Sync nếu lệch quá threshold so với video.currentTime */
  sync(videoTime: number, threshold = 0.25) {
    this.elements.forEach((el, key) => {
      if (!this.enabled[key]) return
      const drift = Math.abs(el.currentTime - videoTime)
      if (drift > threshold) {
        try { el.currentTime = videoTime } catch {}
      }
    })
  }

  hasAny(): boolean {
    return Object.values(this.urls).some(Boolean)
  }
}

const stemEngine = new StemEngine()
export { stemEngine }


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

  // ─── Stem state (v5.1) ────────────────────────────────────────────────
  const [stemUrls, setStemUrls] = useState<Partial<Record<'bass'|'drums'|'vocals', string>>>({})
  const [bassVol, setBassVol]         = useState(0.3)
  const [drumsVol, setDrumsVol]       = useState(0.3)
  const [vocalsVol, setVocalsVol]     = useState(0.3)
  const [bassOn, setBassOn]           = useState(false)
  const [drumsOn, setDrumsOn]         = useState(false)
  const [vocalsOn, setVocalsOn]       = useState(false)

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

  // ─── Stem effects ─────────────────────────────────────────────────────
  // Load stem URLs khi project mở — call API stem-cache
  useEffect(() => {
    if (!project?.id) return
    let cancelled = false
    api.get(`/export_video/stem-cache/${project.id}`)
      .then(r => {
        if (cancelled) return
        const data = r.data
        console.log('[StemEngine] stem-cache response:', data)
        if (data?.cached && data.stems) {
          setStemUrls(data.stems)
        } else {
          setStemUrls({})
        }
      })
      .catch(e => {
        console.warn('[StemEngine] stem-cache failed:', e?.message)
      })
    return () => { cancelled = true }
  }, [project?.id])

  // Sync URLs với StemEngine
  useEffect(() => {
    stemEngine.setUrl('bass', stemUrls.bass)
    stemEngine.setUrl('drums', stemUrls.drums)
    stemEngine.setUrl('vocals', stemUrls.vocals)
  }, [stemUrls])

  // Sync volume + enabled
  useEffect(() => { stemEngine.setVolume('bass', bassVol) }, [bassVol])
  useEffect(() => { stemEngine.setVolume('drums', drumsVol) }, [drumsVol])
  useEffect(() => { stemEngine.setVolume('vocals', vocalsVol) }, [vocalsVol])
  useEffect(() => { stemEngine.setEnabled('bass', bassOn) }, [bassOn])
  useEffect(() => { stemEngine.setEnabled('drums', drumsOn) }, [drumsOn])
  useEffect(() => { stemEngine.setEnabled('vocals', vocalsOn) }, [vocalsOn])

  // Sync drift mỗi 2s khi đang play (tránh stem lệch sau khi loop/buffer)
  useEffect(() => {
    const id = setInterval(() => {
      const v = videoRef.current
      if (v && !v.paused && isPlayingRef.current) {
        stemEngine.sync(v.currentTime, 0.3)
      }
    }, 2000)
    return () => clearInterval(id)
  }, [])

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
    const onPlay  = () => { setPlaying(true);  isPlayingRef.current = true;  ttsEngine.setPlaying(true);  stemEngine.setPlaying(true) }
    const onPause = () => { setPlaying(false); isPlayingRef.current = false; ttsEngine.setPlaying(false); stemEngine.setPlaying(false) }
    const onEnded = () => { setPlaying(false); isPlayingRef.current = false; ttsEngine.setPlaying(false); stemEngine.setPlaying(false) }
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
    stemEngine.seek(seekRequest.time)
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
    stemEngine.seek(t)
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
      if (v) { v.currentTime = t; ttsEngine.stopAll(); stemEngine.seek(t) }
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

      {/* v5.1 — Stem volume (chỉ hiển thị nếu đã có stem) */}
      {(stemUrls.bass || stemUrls.drums || stemUrls.vocals) && (
        <div className="flex items-center gap-3 px-3 pb-2 bg-zinc-900 flex-shrink-0 border-t border-zinc-800/50 pt-1.5">
          {/* Bass */}
          <div className="flex items-center gap-1.5 flex-1">
            <span className="text-[12px] flex-shrink-0">🎸</span>
            <span className="text-[9px] text-zinc-500 flex-shrink-0 w-9">BASS</span>
            <input type="range" min={0} max={1} step={0.05} value={bassVol}
              disabled={!stemUrls.bass}
              onChange={e => setBassVol(parseFloat(e.target.value))}
              className="flex-1 accent-purple-500 cursor-pointer disabled:opacity-40" style={{ height: 4 }} />
            <span className="text-[9px] text-zinc-500 w-5 text-right tabular-nums">{Math.round(bassVol*100)}</span>
            <button onClick={() => setBassOn(v => !v)} disabled={!stemUrls.bass}
              className={`w-8 h-5 rounded text-[9px] font-bold flex-shrink-0 disabled:opacity-40 ${bassOn ? 'bg-purple-600 text-white' : 'bg-zinc-700 text-zinc-400'}`}>
              {bassOn ? 'ON' : 'OFF'}
            </button>
          </div>
          <div className="w-px h-4 bg-zinc-700 flex-shrink-0" />
          {/* Drums */}
          <div className="flex items-center gap-1.5 flex-1">
            <span className="text-[12px] flex-shrink-0">🥁</span>
            <span className="text-[9px] text-zinc-500 flex-shrink-0 w-9">DRUMS</span>
            <input type="range" min={0} max={1} step={0.05} value={drumsVol}
              disabled={!stemUrls.drums}
              onChange={e => setDrumsVol(parseFloat(e.target.value))}
              className="flex-1 accent-amber-500 cursor-pointer disabled:opacity-40" style={{ height: 4 }} />
            <span className="text-[9px] text-zinc-500 w-5 text-right tabular-nums">{Math.round(drumsVol*100)}</span>
            <button onClick={() => setDrumsOn(v => !v)} disabled={!stemUrls.drums}
              className={`w-8 h-5 rounded text-[9px] font-bold flex-shrink-0 disabled:opacity-40 ${drumsOn ? 'bg-amber-600 text-white' : 'bg-zinc-700 text-zinc-400'}`}>
              {drumsOn ? 'ON' : 'OFF'}
            </button>
          </div>
          <div className="w-px h-4 bg-zinc-700 flex-shrink-0" />
          {/* Vocals */}
          <div className="flex items-center gap-1.5 flex-1">
            <span className="text-[12px] flex-shrink-0">🎤</span>
            <span className="text-[9px] text-zinc-500 flex-shrink-0 w-9">VOCALS</span>
            <input type="range" min={0} max={1} step={0.05} value={vocalsVol}
              disabled={!stemUrls.vocals}
              onChange={e => setVocalsVol(parseFloat(e.target.value))}
              className="flex-1 accent-pink-500 cursor-pointer disabled:opacity-40" style={{ height: 4 }} />
            <span className="text-[9px] text-zinc-500 w-5 text-right tabular-nums">{Math.round(vocalsVol*100)}</span>
            <button onClick={() => setVocalsOn(v => !v)} disabled={!stemUrls.vocals}
              className={`w-8 h-5 rounded text-[9px] font-bold flex-shrink-0 disabled:opacity-40 ${vocalsOn ? 'bg-pink-600 text-white' : 'bg-zinc-700 text-zinc-400'}`}>
              {vocalsOn ? 'ON' : 'OFF'}
            </button>
          </div>
        </div>
      )}
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