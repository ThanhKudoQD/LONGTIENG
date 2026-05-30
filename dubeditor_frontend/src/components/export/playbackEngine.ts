/**
 * playbackEngine — module quản lý "virtual playback" cho Export preview.
 *
 * Nghiệp vụ:
 *   - Video phát theo các "khoảng giữ" (clips). Nếu không có clip → phát toàn bộ.
 *   - Voice TTS: phát các audio per-sub đúng timing (sourceTime của sub nằm trong clip).
 *   - BGM tracks: phát các <audio> với start/end/volume/fade.
 *   - Mọi thứ sync theo "output time" (timeline đã cắt).
 *
 * Mapping source ↔ output:
 *   - Source time = vị trí trong video gốc
 *   - Output time = vị trí trong video sau cắt (sum các clip)
 *
 * Nếu không có clip: source = output (toàn bộ video).
 */
import { VideoClip, AudioTrack } from './types'

export interface VoiceSeg {
  id: number
  start: number       // source time
  end: number
  audio_path: string
  speed?: number      // tốc độ phát (default 1.0)
}

export interface PlaybackOptions {
  videoEl: HTMLVideoElement
  clips: VideoClip[]
  videoDuration: number
  voiceSegments: VoiceSeg[]
  voiceVolume: number
  voiceEnabled: boolean
  bgmTracks: AudioTrack[]
  apiBaseUrl?: string             // để build URL audio voice nếu cần
  onTimeUpdate?: (outputTime: number, sourceTime: number) => void
  onEnded?: () => void
}

// Sorted clips theo source_start, đảm bảo monotonic
function normalizeClips(clips: VideoClip[], videoDuration: number): VideoClip[] {
  if (clips.length === 0) {
    return [{ id: '_all', source_start: 0, source_end: videoDuration, label: 'all' }]
  }
  return [...clips].sort((a, b) => a.source_start - b.source_start)
}

// Tổng output duration
export function getOutputDuration(clips: VideoClip[], videoDuration: number): number {
  if (clips.length === 0) return videoDuration
  return clips.reduce((s, c) => s + Math.max(0, c.source_end - c.source_start), 0)
}

// Output time → source time + clip index
export function outputToSource(outputTime: number, clips: VideoClip[], videoDuration: number): { source: number; clipIdx: number } | null {
  const norm = normalizeClips(clips, videoDuration)
  let acc = 0
  for (let i = 0; i < norm.length; i++) {
    const len = Math.max(0, norm[i].source_end - norm[i].source_start)
    if (outputTime <= acc + len) {
      return { source: norm[i].source_start + (outputTime - acc), clipIdx: i }
    }
    acc += len
  }
  // Quá end
  const last = norm[norm.length - 1]
  return { source: last.source_end, clipIdx: norm.length - 1 }
}

// Source time → output time (nếu source nằm trong clip nào)
export function sourceToOutput(sourceTime: number, clips: VideoClip[], videoDuration: number): number | null {
  const norm = normalizeClips(clips, videoDuration)
  let acc = 0
  for (const c of norm) {
    if (sourceTime >= c.source_start && sourceTime <= c.source_end) {
      return acc + (sourceTime - c.source_start)
    }
    acc += Math.max(0, c.source_end - c.source_start)
  }
  return null
}

// ─────────────────────────────────────────────────────────────────────────
// Class PlaybackEngine
// ─────────────────────────────────────────────────────────────────────────

export class PlaybackEngine {
  private opts: PlaybackOptions
  private rafId: number | null = null
  private startWallTime: number = 0    // performance.now() lúc bấm play
  private startOutputTime: number = 0  // output time tại lúc start
  private playing: boolean = false
  // Voice audio elements pool (1 element/sub)
  private voiceEls: Map<number, HTMLAudioElement> = new Map()
  // BGM audio elements (1 per track)
  private bgmEls: Map<string, HTMLAudioElement> = new Map()
  private outputDuration: number = 0
  private clipsNorm: VideoClip[] = []

  constructor(opts: PlaybackOptions) {
    this.opts = opts
    this.outputDuration = getOutputDuration(opts.clips, opts.videoDuration)
    this.clipsNorm = normalizeClips(opts.clips, opts.videoDuration)
  }

  /** Cập nhật config (clips/voice/bgm thay đổi) — giữ playing state */
  updateOptions(opts: Partial<PlaybackOptions>) {
    this.opts = { ...this.opts, ...opts }
    this.outputDuration = getOutputDuration(this.opts.clips, this.opts.videoDuration)
    this.clipsNorm = normalizeClips(this.opts.clips, this.opts.videoDuration)
    // Nếu đang play, không cần restart — vòng tick sẽ tự re-evaluate
  }

  get isPlaying() { return this.playing }
  get duration() { return this.outputDuration }

  /** Bắt đầu play từ outputTime */
  play(fromOutputTime?: number) {
    if (this.playing) return
    const startOT = fromOutputTime ?? 0
    this.startOutputTime = Math.max(0, Math.min(this.outputDuration, startOT))
    this.startWallTime = performance.now()
    this.playing = true

    // Sync video
    this._syncVideoToOutput(this.startOutputTime, true)
    // Schedule voice + BGM
    this._scheduleAudios(this.startOutputTime)

    this._tick()
  }

  pause() {
    if (!this.playing) return
    this.playing = false
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId)
      this.rafId = null
    }
    // Pause video
    try { this.opts.videoEl.pause() } catch {}
    // Pause + stop tất cả audio
    this.voiceEls.forEach(a => { try { a.pause(); a.currentTime = 0 } catch {} })
    this.bgmEls.forEach(a => { try { a.pause() } catch {} })
  }

  /** Seek đến outputTime (giữ playing state). Atomic update, không pause/play full. */
  seek(outputTime: number) {
    const ot = Math.max(0, Math.min(this.outputDuration, outputTime))
    if (this.playing) {
      // Atomic update: reset startWallTime + startOutputTime ĐỒNG THỜI
      // _tick tiếp theo sẽ compute time từ giá trị mới này.
      this.startOutputTime = ot
      this.startWallTime = performance.now()
      // Sync video element ngay (không restart play, vì đã đang play)
      const r = outputToSource(ot, this.opts.clips, this.opts.videoDuration)
      if (r && this.opts.videoEl) {
        try { this.opts.videoEl.currentTime = r.source } catch {}
      }
      // Pause + reset voice/bgm audio đang phát — _tick sẽ start lại nếu cần
      this.voiceEls.forEach(a => { try { a.pause(); a.currentTime = 0 } catch {} })
      this.bgmEls.forEach(a => { try { a.pause() } catch {} })
      // Trigger onTimeUpdate ngay để UI cập nhật mượt
      this.opts.onTimeUpdate?.(ot, r ? r.source : 0)
    } else {
      this.startOutputTime = ot
      this._syncVideoToOutput(ot, false)
      this.opts.onTimeUpdate?.(ot, this._outputToSourceSafe(ot))
    }
  }

  /** Get current output time */
  getCurrentOutputTime(): number {
    if (!this.playing) return this.startOutputTime
    const elapsed = (performance.now() - this.startWallTime) / 1000
    return Math.min(this.outputDuration, this.startOutputTime + elapsed)
  }

  destroy() {
    this.pause()
    this.voiceEls.forEach(a => { try { a.pause(); a.src = '' } catch {} })
    this.voiceEls.clear()
    this.bgmEls.forEach(a => { try { a.pause(); a.src = '' } catch {} })
    this.bgmEls.clear()
  }

  // ─── Internal ─────────────────────────────────────────────────────────

  private _outputToSourceSafe(outputTime: number): number {
    const r = outputToSource(outputTime, this.opts.clips, this.opts.videoDuration)
    return r ? r.source : 0
  }

  private _syncVideoToOutput(outputTime: number, willPlay: boolean) {
    const r = outputToSource(outputTime, this.opts.clips, this.opts.videoDuration)
    if (!r) return
    const v = this.opts.videoEl
    if (Math.abs(v.currentTime - r.source) > 0.2) v.currentTime = r.source
    if (willPlay) {
      v.muted = true   // mute video, dùng voice TTS thay
      v.play().catch(() => {})
    }
  }

  private _scheduleAudios(fromOutputTime: number) {
    // Lúc bắt đầu play, mọi audio đã pause. Vòng tick sẽ trigger play khi đến đúng output time.
    // Pre-create audio elements để giảm latency khi đến time.
    for (const seg of this.opts.voiceSegments) {
      if (!this.voiceEls.has(seg.id)) {
        const a = new Audio(seg.audio_path)
        a.preload = 'auto'
        a.volume = this.opts.voiceVolume
        this.voiceEls.set(seg.id, a)
      } else {
        const a = this.voiceEls.get(seg.id)!
        a.volume = this.opts.voiceVolume
      }
    }
    for (const tr of this.opts.bgmTracks) {
      if (!this.bgmEls.has(tr.id)) {
        const a = new Audio(tr.file_url || tr.file_path)
        a.preload = 'auto'
        this.bgmEls.set(tr.id, a)
      }
    }
  }

  private _tick = () => {
    if (!this.playing) return
    const outputTime = this.getCurrentOutputTime()

    // Check end
    if (outputTime >= this.outputDuration) {
      this.pause()
      this.startOutputTime = 0
      this.opts.onEnded?.()
      return
    }

    // ── Sync video ────────────────────────────────────────────────────────
    // Nếu source time hiện tại không nằm trong clip → skip đến clip kế.
    const r = outputToSource(outputTime, this.opts.clips, this.opts.videoDuration)
    if (r) {
      const v = this.opts.videoEl
      const drift = Math.abs(v.currentTime - r.source)
      if (drift > 0.4) {
        // Drift lớn (vd qua biên clip) — seek lại
        v.currentTime = r.source
      }
      if (v.paused) v.play().catch(() => {})
    }

    // ── Voice TTS ─────────────────────────────────────────────────────────
    if (this.opts.voiceEnabled) {
      for (const seg of this.opts.voiceSegments) {
        const segOutputStart = sourceToOutput(seg.start, this.opts.clips, this.opts.videoDuration)
        if (segOutputStart === null) continue  // sub này ở ngoài khoảng giữ → skip
        const segOutputEnd = segOutputStart + (seg.end - seg.start)
        const a = this.voiceEls.get(seg.id)
        if (!a) continue

        if (outputTime >= segOutputStart - 0.05 && outputTime < segOutputEnd) {
          if (a.paused) {
            try {
              a.currentTime = Math.max(0, outputTime - segOutputStart)
              a.volume = this.opts.voiceVolume
              a.play().catch(() => {})
            } catch {}
          }
        } else {
          if (!a.paused) {
            try { a.pause(); a.currentTime = 0 } catch {}
          }
        }
      }
    } else {
      this.voiceEls.forEach(a => { if (!a.paused) try { a.pause() } catch {} })
    }

    // ── BGM ───────────────────────────────────────────────────────────────
    for (const tr of this.opts.bgmTracks) {
      const a = this.bgmEls.get(tr.id)
      if (!a) continue
      // BGM dùng OUTPUT time (vì start/end của BGM là theo timeline output sau cắt)
      // → Đơn giản: trong khoảng start_time → end_time → phát
      if (outputTime >= tr.start_time && outputTime < tr.end_time) {
        if (a.paused) {
          try {
            a.currentTime = Math.max(0, outputTime - tr.start_time)
          } catch {}
          // Volume + fade
          const t = outputTime - tr.start_time
          const len = tr.end_time - tr.start_time
          let vol = tr.volume
          if (tr.fade_in > 0 && t < tr.fade_in) vol *= t / tr.fade_in
          if (tr.fade_out > 0 && t > len - tr.fade_out) vol *= (len - t) / tr.fade_out
          a.volume = Math.max(0, Math.min(1, vol))
          a.play().catch(() => {})
        } else {
          // Update volume liên tục cho fade
          const t = outputTime - tr.start_time
          const len = tr.end_time - tr.start_time
          let vol = tr.volume
          if (tr.fade_in > 0 && t < tr.fade_in) vol *= t / tr.fade_in
          if (tr.fade_out > 0 && t > len - tr.fade_out) vol *= (len - t) / tr.fade_out
          a.volume = Math.max(0, Math.min(1, vol))
        }
      } else {
        if (!a.paused) try { a.pause() } catch {}
      }
    }

    // Notify
    this.opts.onTimeUpdate?.(outputTime, r ? r.source : 0)

    this.rafId = requestAnimationFrame(this._tick)
  }
}
