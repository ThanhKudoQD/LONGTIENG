/**
 * PreviewPanel v4 — responsive size + sub render đúng vùng video (không bị padding đè).
 *
 * Thay đổi v4:
 *   - Preview RESPONSIVE: tự fit theo container (full height available, không cố định 420px)
 *   - Sub overlay nằm TRONG vùng video frame (không phải toàn bộ frame có padding)
 *     → khi padding bottom bật, sub vẫn ở đáy VIDEO không phải đáy padding
 *   - Watermark cũng chỉ render trong vùng video
 */
import React, { useRef, useState, useEffect, useCallback, useLayoutEffect } from 'react'
import { ExportConfig, WatermarkPosition, getEffectiveRatio } from './types'
import { PlaybackEngine, VoiceSeg, getOutputDuration, outputToSource } from './playbackEngine'

interface Props {
  config: ExportConfig
  videoUrl: string | null
  videoDuration: number
  sourceRatio: number | null
  currentTime: number              // OUTPUT time
  sourceTime: number               // SOURCE time
  onTimeChange: (t: number) => void
  voiceSegments: Array<{ id: number; start: number; end: number; audio_path?: string }>
  subtitleSegments: Array<{ id: number; start: number; end: number; text: string }>
}

export default function PreviewPanel({
  config, videoUrl, videoDuration, sourceRatio,
  currentTime, sourceTime, onTimeChange,
  voiceSegments, subtitleSegments,
}: Props) {
  const { subtitle_style, padding, watermarks, output } = config
  const containerRef = useRef<HTMLDivElement>(null)
  const videoRef = useRef<HTMLVideoElement>(null)
  const engineRef = useRef<PlaybackEngine | null>(null)
  // Lưu output time gần nhất engine đã báo về — để phân biệt update từ engine vs external seek
  const lastEngineTimeRef = useRef<number>(0)
  const [playing, setPlaying] = useState(false)
  const [dragging, setDragging] = useState(false)
  // Container size (đo bằng ResizeObserver)
  const [containerSize, setContainerSize] = useState({ w: 0, h: 0 })

  const effectiveRatio = getEffectiveRatio(output, sourceRatio) ?? (16/9)
  const outputDuration = getOutputDuration(config.clips, videoDuration)

  // ─── Đo container ──────────────────────────────────────────────────────
  useLayoutEffect(() => {
    if (!containerRef.current) return
    const el = containerRef.current
    const update = () => {
      const rect = el.getBoundingClientRect()
      setContainerSize({ w: rect.width, h: rect.height })
    }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // ─── Tính kích thước video frame (fit available space) ──────────────
  // Video frame full size theo aspect ratio — padding chỉ là OVERLAY đè lên.
  const CONTROLS_HEIGHT = 110
  const HEADER_HEIGHT = 24
  const GAP = 12
  const PADDING_BOX = 16

  // v4.0 — Zoom in/out preview (50% → 150%)
  const [zoom, setZoom] = useState<number>(1.0)

  const availableW = Math.max(160, containerSize.w - PADDING_BOX)
  const availableH = Math.max(160, containerSize.h - PADDING_BOX - CONTROLS_HEIGHT - HEADER_HEIGHT - GAP * 2)

  // Fit theo aspect ratio:
  // - Video DỌC (ratio < 1): ưu tiên fit theo HEIGHT để preview chiếm chiều cao tối đa
  // - Video NGANG (ratio >= 1): ưu tiên fit theo WIDTH
  let videoW: number, videoH: number
  if (effectiveRatio < 1) {
    // Dọc
    videoH = availableH
    videoW = videoH * effectiveRatio
    if (videoW > availableW) {
      videoW = availableW
      videoH = videoW / effectiveRatio
    }
  } else {
    // Ngang
    videoW = availableW
    videoH = videoW / effectiveRatio
    if (videoH > availableH) {
      videoH = availableH
      videoW = videoH * effectiveRatio
    }
  }
  // Apply zoom
  videoW = videoW * zoom
  videoH = videoH * zoom

  // Scale padding theo videoH (CHIỀU CAO — khớp logic BE & sub font scale theo 1080)
  const padScale = videoH / 1080
  const padTopH = padding.top.enabled ? Math.max(8, padding.top.height_px * padScale) : 0
  const padBotH = padding.bottom.enabled ? Math.max(8, padding.bottom.height_px * padScale) : 0

  // ─── Engine setup ─────────────────────────────────────────────────────
  const validVoiceSegs: VoiceSeg[] = voiceSegments
    .filter(s => !!s.audio_path)
    .map(s => ({ id: s.id, start: s.start, end: s.end, audio_path: s.audio_path! }))

  useEffect(() => {
    if (!videoRef.current) return
    const v = videoRef.current
    if (!engineRef.current) {
      engineRef.current = new PlaybackEngine({
        videoEl: v,
        clips: config.clips,
        videoDuration,
        voiceSegments: validVoiceSegs,
        voiceVolume: config.audio.voice_volume,
        voiceEnabled: config.audio.voice_enabled,
        bgmTracks: config.audio.tracks,
        onTimeUpdate: (outputTime) => {
          lastEngineTimeRef.current = outputTime
          onTimeChange(outputTime)
        },
        onEnded: () => setPlaying(false),
      })
    } else {
      engineRef.current.updateOptions({
        clips: config.clips,
        videoDuration,
        voiceSegments: validVoiceSegs,
        voiceVolume: config.audio.voice_volume,
        voiceEnabled: config.audio.voice_enabled,
        bgmTracks: config.audio.tracks,
      })
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [config.clips, videoDuration, voiceSegments.length, config.audio.voice_volume,
      config.audio.voice_enabled, config.audio.tracks])

  useEffect(() => {
    return () => {
      engineRef.current?.destroy()
      engineRef.current = null
    }
  }, [])

  // External seek detection: nếu currentTime prop khác giá trị engine vừa báo về → là timeline click/scrubber drag.
  useEffect(() => {
    if (!videoRef.current || !engineRef.current) return
    const drift = Math.abs(currentTime - lastEngineTimeRef.current)
    if (drift < 0.05) return    // engine update — không cần seek lại

    // External seek
    if (playing) {
      engineRef.current.seek(currentTime)
    } else {
      const r = outputToSource(currentTime, config.clips, videoDuration)
      if (r && Math.abs(videoRef.current.currentTime - r.source) > 0.1) {
        videoRef.current.currentTime = r.source
      }
    }
    lastEngineTimeRef.current = currentTime
  }, [currentTime, playing, config.clips, videoDuration])

  const togglePlay = useCallback(() => {
    if (!engineRef.current) return
    if (playing) {
      engineRef.current.pause()
      setPlaying(false)
    } else {
      engineRef.current.play(currentTime >= outputDuration - 0.1 ? 0 : currentTime)
      setPlaying(true)
    }
  }, [playing, currentTime, outputDuration])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target as HTMLElement).isContentEditable) return
      if (e.code === 'Space') { e.preventDefault(); togglePlay() }
      else if (e.code === 'ArrowLeft') { e.preventDefault(); onTimeChange(Math.max(0, currentTime - 5)) }
      else if (e.code === 'ArrowRight') { e.preventDefault(); onTimeChange(Math.min(outputDuration, currentTime + 5)) }
      else if (e.code === 'Home') { e.preventDefault(); onTimeChange(0) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [togglePlay, currentTime, outputDuration, onTimeChange])

  // ─── Style sub theo previewW thực tế ─────────────────────────────────
  // Scale font theo chiều cao preview (assume output 1080p reference height).
  // Min scale 0.4 để font nhỏ vẫn nhìn rõ. Bỏ min font cứng để slider đổi smooth hơn.
  // Scale font đúng tỉ lệ thật với chiều ngắn = 1080.
  // KHÔNG clamp min — để preview phản ánh CHÍNH XÁC kích thước output.
  // Nếu preview quá nhỏ → user phóng to bằng nút zoom (+) trên header.
  const fontScale = Math.min(videoW, videoH) / 1080
  const subStyle: React.CSSProperties = subtitle_style.enabled ? {
    fontFamily: subtitle_style.font_family,
    fontSize: subtitle_style.font_size * fontScale,
    color: subtitle_style.color,
    fontWeight: subtitle_style.bold ? 700 : 400,
    fontStyle: subtitle_style.italic ? 'italic' : 'normal',
    textShadow: subtitle_style.outline_enabled
      ? `0 0 ${subtitle_style.outline_width}px ${subtitle_style.outline_color}, 0 0 ${subtitle_style.outline_width}px ${subtitle_style.outline_color}, 0 0 ${subtitle_style.outline_width}px ${subtitle_style.outline_color}`
      : subtitle_style.shadow_enabled
        ? `0 2px ${subtitle_style.shadow_blur}px ${subtitle_style.shadow_color}`
        : 'none',
    background: subtitle_style.background_enabled
      ? `${subtitle_style.background_color}${Math.round(subtitle_style.background_opacity * 255).toString(16).padStart(2, '0')}`
      : 'transparent',
    padding: subtitle_style.background_enabled ? '4px 12px' : 0,
    borderRadius: 4,
    textAlign: 'center',
  } : {}

  // ─── Scrubber ───────────────────────────────────────────────────────
  const handleScrubMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    setDragging(true)
    updateScrubFromMouse(e.clientX, e.currentTarget)
  }
  const updateScrubFromMouse = useCallback((clientX: number, el: HTMLElement) => {
    const rect = el.getBoundingClientRect()
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
    const t = ratio * outputDuration
    onTimeChange(t)
    engineRef.current?.seek(t)
  }, [outputDuration, onTimeChange])

  useEffect(() => {
    if (!dragging) return
    const onMove = (e: MouseEvent) => {
      const el = document.getElementById('preview-scrubber-track')
      if (el) updateScrubFromMouse(e.clientX, el)
    }
    const onUp = () => setDragging(false)
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [dragging, updateScrubFromMouse])

  const videoObjectFit = output.fit_mode === 'crop' ? 'cover' : 'contain'
  const videoBg = output.fit_mode === 'pad_color'
    ? (padding.bottom.enabled ? padding.bottom.color : padding.top.enabled ? padding.top.color : '#000')
    : '#000'

  const fmtT = (s: number) => {
    if (!isFinite(s) || s < 0) return '0:00'
    const m = Math.floor(s / 60), sec = Math.floor(s % 60)
    return `${m}:${String(sec).padStart(2, '0')}`
  }

  return (
    <div ref={containerRef} className="h-full flex flex-col gap-3 p-2 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between flex-shrink-0 gap-2">
        <div className="text-[11px] uppercase tracking-wider text-zinc-500 font-medium">Preview</div>
        <div className="flex items-center gap-2 text-[11px] text-zinc-500">
          {/* Zoom controls */}
          <div className="flex items-center gap-0.5 bg-zinc-100 dark:bg-zinc-800 rounded">
            <button onClick={() => setZoom(z => Math.max(0.5, z - 0.1))}
              className="w-6 h-6 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded-l flex items-center justify-center" title="Thu nhỏ">−</button>
            <button onClick={() => setZoom(1.0)}
              className="px-1.5 h-6 font-mono hover:bg-zinc-200 dark:hover:bg-zinc-700 text-[10px]" title="Reset 100%">{Math.round(zoom * 100)}%</button>
            <button onClick={() => setZoom(z => Math.min(1.5, z + 0.1))}
              className="w-6 h-6 hover:bg-zinc-200 dark:hover:bg-zinc-700 rounded-r flex items-center justify-center" title="Phóng to">+</button>
          </div>
          <span className="font-mono">
            {Math.round(videoW)}×{Math.round(videoH)} · {output.aspect_ratio === 'source' ? 'theo gốc' : output.aspect_ratio}
          </span>
        </div>
      </div>

      {/* Frame wrapper - căn giữa */}
      <div className="flex-1 flex items-center justify-center min-h-0">
        <div className="relative rounded-lg overflow-hidden border border-zinc-300 dark:border-zinc-700 shadow-md"
          style={{ width: videoW, height: videoH, background: videoBg }}>

          {/* Video element nền */}
          {videoUrl ? (
            <video
              ref={videoRef}
              src={videoUrl}
              muted
              playsInline
              preload="metadata"
              className="absolute inset-0 w-full h-full"
              style={{ objectFit: videoObjectFit as any }}
            />
          ) : (
            <div className="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-zinc-700 to-zinc-900 text-zinc-500 text-[12px]">
              [Chưa có video preview]
            </div>
          )}

          {/* Padding TOP overlay — ĐÈ LÊN video */}
          {padding.top.enabled && (
            <div className="absolute top-0 left-0 right-0 pointer-events-none z-10"
              style={{ background: padding.top.color, height: padTopH }} />
          )}

          {/* Padding BOTTOM overlay — ĐÈ LÊN video */}
          {padding.bottom.enabled && (
            <div className="absolute bottom-0 left-0 right-0 pointer-events-none z-10"
              style={{ background: padding.bottom.color, height: padBotH }} />
          )}

          {/* Subtitle overlay — vị trí dựa vào padding để không bị padding đè */}
          {subtitle_style.enabled && (() => {
            const activeSub = subtitleSegments.find(s => sourceTime >= s.start && sourceTime <= s.end)
            const showSample = !activeSub && currentTime < 0.5
            const displayText = activeSub?.text || (showSample ? 'Đây là phụ đề mẫu — bấm Play để xem sub thật.' : '')
            if (!displayText) return null

            // Y offset semantics:
            //   y_offset = 0   → sub ở vị trí MẶC ĐỊNH (sát padding nếu có, sát mép video nếu không)
            //   y_offset âm    → đẩy LÊN (về phía top của video)
            //   y_offset dương → đẩy XUỐNG (về phía bottom của video)
            // Scale theo CHIỀU CAO video (sub size = px, scale theo height giả định 1080).
            const yOffsetPx = subtitle_style.y_offset * (videoH / 1080)
            const subContainerStyle: React.CSSProperties = {
              position: 'absolute',
              left: 0, right: 0,
              display: 'flex',
              justifyContent: 'center',
              padding: '0 12px',
              pointerEvents: 'none',
              zIndex: 20,
            }
            if (subtitle_style.position === 'top') {
              // Mặc định: sát padding top (hoặc mép trên video nếu không padding)
              // y_offset âm = đẩy lên (vào padding) → top giảm
              // y_offset dương = đẩy xuống → top tăng
              subContainerStyle.top = Math.max(0, padTopH + yOffsetPx)
              subContainerStyle.alignItems = 'flex-start'
            } else if (subtitle_style.position === 'middle') {
              subContainerStyle.top = '50%'
              subContainerStyle.transform = `translateY(calc(-50% + ${yOffsetPx}px))`
            } else {
              // bottom: mặc định SÁT padding bottom (y_offset=0)
              // y_offset âm = đẩy lên (xa khỏi đáy) → bottom tăng
              // y_offset dương = đẩy xuống (vào padding) → bottom giảm
              subContainerStyle.bottom = Math.max(0, padBotH - yOffsetPx)
              subContainerStyle.alignItems = 'flex-end'
            }
            return (
              <div style={subContainerStyle}>
                <span style={subStyle}>{displayText}</span>
              </div>
            )
          })()}

          {/* Watermarks overlay - z-30 cao nhất để luôn thấy */}
          {watermarks.map(wm => {
            const pos = positionToStyle(wm.position, wm.x_offset * (videoW/1920), wm.y_offset * (videoW/1920))
            const wmStyle: React.CSSProperties = { ...pos, opacity: wm.opacity, zIndex: 30 }
            if (wm.type === 'text') {
              return (
                <div key={wm.id} className="absolute pointer-events-none whitespace-nowrap"
                  style={{
                    ...wmStyle,
                    color: wm.color,
                    fontFamily: wm.font_family,
                    fontSize: Math.max(8, wm.font_size * (videoW/1920)),
                    fontWeight: 600,
                  }}>{wm.text}</div>
              )
            }
            return (
              <div key={wm.id} className="absolute pointer-events-none" style={wmStyle}>
                {wm.image_url ? (
                  <img src={wm.image_url} alt="wm" style={{ width: wm.width_px * (videoW/1920), height: 'auto' }} />
                ) : (
                  <div className="bg-zinc-600 text-white text-[10px] p-2 rounded">[logo]</div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* ─── Controls (cố định ở dưới) ─────────────────────────────── */}
      {videoUrl && videoDuration > 0 && (
        <div className="flex-shrink-0 space-y-2" style={{ maxWidth: videoW, marginInline: 'auto', width: '100%' }}>
          <div className="flex items-center gap-2">
            <button
              onClick={togglePlay}
              className="flex-shrink-0 w-9 h-9 rounded-full bg-blue-600 hover:bg-blue-700 text-white flex items-center justify-center transition-colors"
              title={playing ? 'Pause (Space)' : 'Play (Space)'}
            >
              {playing ? (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                  <rect x="3" y="2" width="3" height="10" rx="0.5" />
                  <rect x="8" y="2" width="3" height="10" rx="0.5" />
                </svg>
              ) : (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                  <path d="M4 2 L12 7 L4 12 Z" />
                </svg>
              )}
            </button>
            <button onClick={() => { onTimeChange(0); engineRef.current?.seek(0) }}
              className="flex-shrink-0 w-7 h-7 rounded-full hover:bg-zinc-200 dark:hover:bg-zinc-800 flex items-center justify-center"
              title="Về đầu (Home)">⏮</button>
            <div className="font-mono text-[11px] text-zinc-600 dark:text-zinc-400 tabular-nums">
              {fmtT(currentTime)} / {fmtT(outputDuration)}
            </div>
            <div className="ml-auto text-[10px] text-zinc-400">Space · ←→ · Home</div>
          </div>

          <div
            id="preview-scrubber-track"
            onMouseDown={handleScrubMouseDown}
            className="relative h-2 bg-zinc-300 dark:bg-zinc-700 rounded-full cursor-pointer"
          >
            <div className="absolute top-0 left-0 h-full bg-blue-500 rounded-full pointer-events-none"
              style={{ width: `${(currentTime / outputDuration) * 100}%` }} />
            <div className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 w-3.5 h-3.5 bg-white border-2 border-blue-500 rounded-full shadow pointer-events-none"
              style={{ left: `${(currentTime / outputDuration) * 100}%` }} />
          </div>

          {config.clips.length > 0 && (
            <div className="text-[10px] text-emerald-700 dark:text-emerald-500 text-center bg-emerald-50 dark:bg-emerald-950/30 rounded py-1">
              ✂ Đã cắt còn {fmtT(outputDuration)} (gốc {fmtT(videoDuration)}) · {config.clips.length} đoạn giữ
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function positionToStyle(pos: WatermarkPosition, x: number, y: number): React.CSSProperties {
  switch (pos) {
    case 'top_left':      return { top: y, left: x }
    case 'top_center':    return { top: y, left: '50%', transform: `translateX(calc(-50% + ${x}px))` }
    case 'top_right':     return { top: y, right: x }
    case 'center':        return { top: '50%', left: '50%', transform: `translate(calc(-50% + ${x}px), calc(-50% + ${y}px))` }
    case 'bottom_left':   return { bottom: y, left: x }
    case 'bottom_center': return { bottom: y, left: '50%', transform: `translateX(calc(-50% + ${x}px))` }
    case 'bottom_right':  return { bottom: y, right: x }
  }
}
