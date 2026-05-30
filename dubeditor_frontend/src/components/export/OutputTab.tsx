/**
 * OutputTab — aspect ratio, format, resolution, codec, bitrate.
 */
import React, { useState, useEffect } from 'react'
import api from '../../api'
import {
  OutputConfig, OutputResolution, OutputFormat, VideoCodec, AspectRatio, FitMode,
  ASPECT_PRESETS, FIT_MODES,
} from './types'

interface Props {
  output: OutputConfig
  sourceRatio: number | null
  onChange: (output: OutputConfig) => void
}

const RESOLUTIONS: { key: OutputResolution; label: string; rec_bitrate: string }[] = [
  { key: '720p',   label: '720p HD',     rec_bitrate: '3M'  },
  { key: '1080p',  label: '1080p Full HD', rec_bitrate: '5M'  },
  { key: '1440p',  label: '1440p 2K',   rec_bitrate: '10M' },
  { key: '4k',     label: '4K UHD',     rec_bitrate: '20M' },
  { key: 'custom', label: 'Tùy chỉnh',              rec_bitrate: '5M'  },
]

const FORMATS: { key: OutputFormat; label: string }[] = [
  { key: 'mp4',  label: 'MP4 (phổ thông)' },
  { key: 'mov',  label: 'MOV (Apple)' },
  { key: 'webm', label: 'WebM (web nhẹ)' },
]

const CODECS: { key: VideoCodec; label: string; desc: string }[] = [
  { key: 'h264', label: 'H.264', desc: 'Phổ thông, mọi thiết bị phát được' },
  { key: 'h265', label: 'H.265 (HEVC)', desc: 'File nhẹ hơn 50%, render lâu hơn' },
  { key: 'vp9',  label: 'VP9', desc: 'Cho WebM' },
]

const PRESETS: { key: OutputConfig['preset']; label: string; desc: string }[] = [
  { key: 'ultrafast', label: 'Ultra Fast', desc: 'Nhanh nhất, chất lượng vừa' },
  { key: 'fast',      label: 'Fast',       desc: 'Nhanh, chất lượng tốt' },
  { key: 'medium',    label: 'Medium',     desc: 'Cân bằng (khuyên dùng)' },
  { key: 'slow',      label: 'Slow',       desc: 'Chậm, chất lượng cao nhất' },
]

export default function OutputTab({ output, sourceRatio, onChange }: Props) {
  const patch = <K extends keyof OutputConfig>(key: K, value: OutputConfig[K]) => {
    onChange({ ...output, [key]: value })
  }
  const selectedRes = RESOLUTIONS.find(r => r.key === output.resolution)

  // v4.0: detect GPU NVENC
  const [gpuInfo, setGpuInfo] = useState<{ nvenc_available: boolean } | null>(null)
  useEffect(() => {
    api.get('/export_video/gpu-info').then(r => setGpuInfo(r.data)).catch(() => setGpuInfo({ nvenc_available: false }))
  }, [])

  // Tính dimensions thực tế dựa vào resolution + aspect ratio
  const dims = computeDims(output, sourceRatio)

  return (
    <div className="max-w-3xl space-y-5">

      {/* ─── Aspect ratio (mới) ────────────────────────────────────────── */}
      <div className="surface-card p-4">
        <h3 className="text-[13px] font-semibold mb-1">Tỉ lệ khung hình</h3>
        <p className="text-[11px] text-zinc-500 mb-3">
          Quyết định layout output. Preview + tất cả overlay sẽ render theo tỉ lệ này.
        </p>

        <div className="grid grid-cols-3 gap-2 mb-3">
          {ASPECT_PRESETS.map(p => {
            const isSelected = output.aspect_ratio === p.key
            const isSource = p.key === 'source'
            const ratioText = isSource
              ? (sourceRatio ? formatRatio(sourceRatio) : '—')
              : (p.ratio ? formatRatio(p.ratio) : 'custom')
            return (
              <button
                key={p.key}
                onClick={() => patch('aspect_ratio', p.key)}
                className={`p-2.5 text-[12px] rounded-md border text-left transition-colors ${
                  isSelected
                    ? 'bg-blue-50 border-blue-400 text-blue-800 dark:bg-blue-900/30 dark:border-blue-700'
                    : 'border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                }`}
              >
                <div className="flex items-center gap-2">
                  <AspectIcon ratio={p.ratio || (isSource ? sourceRatio : null) || 16/9} size={20} />
                  <div className="flex-1">
                    <div className="font-medium">{p.key}</div>
                    <div className="text-[10px] text-zinc-500">{ratioText}</div>
                  </div>
                </div>
              </button>
            )
          })}
        </div>

        {/* Custom aspect input */}
        {output.aspect_ratio === 'custom' && (
          <div className="grid grid-cols-2 gap-3 pt-3 border-t border-zinc-200 dark:border-zinc-800">
            <div>
              <Label>Ratio W</Label>
              <input type="number" min={1} step={1} value={output.custom_aspect_w || 16}
                onChange={e => patch('custom_aspect_w', parseInt(e.target.value) || 16)}
                className="input w-full text-[13px]" />
            </div>
            <div>
              <Label>Ratio H</Label>
              <input type="number" min={1} step={1} value={output.custom_aspect_h || 9}
                onChange={e => patch('custom_aspect_h', parseInt(e.target.value) || 9)}
                className="input w-full text-[13px]" />
            </div>
          </div>
        )}

        {/* Fit mode (chỉ hiện khi aspect ≠ source và sourceRatio biết) */}
        {output.aspect_ratio !== 'source' && sourceRatio !== null && (
          <div className="mt-4 pt-3 border-t border-zinc-200 dark:border-zinc-800">
            <Label>Khi tỉ lệ khác video gốc</Label>
            <div className="space-y-1.5 mt-1.5">
              {FIT_MODES.map(m => (
                <label key={m.key} className="flex items-start gap-2 p-2 rounded hover:bg-zinc-50 dark:hover:bg-zinc-900 cursor-pointer">
                  <input type="radio" checked={output.fit_mode === m.key}
                    onChange={() => patch('fit_mode', m.key)} className="w-4 h-4 mt-0.5" />
                  <div className="flex-1">
                    <div className="text-[12.5px] font-medium">{m.label}</div>
                    <div className="text-[10.5px] text-zinc-500">{m.desc}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>
        )}

        {/* Kích thước thực tế */}
        {dims && (
          <div className="mt-4 pt-3 border-t border-zinc-200 dark:border-zinc-800 text-[11.5px] text-zinc-600 dark:text-zinc-400">
            📐 Kích thước output: <span className="font-mono font-semibold">{dims.w} × {dims.h} px</span>
          </div>
        )}
      </div>

      {/* ─── Format + codec ─────────────────────────────────────────────── */}
      <div className="surface-card p-4">
        <h3 className="text-[13px] font-semibold mb-3">Định dạng file</h3>
        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Format</Label>
            <select value={output.format}
              onChange={e => patch('format', e.target.value as OutputFormat)}
              className="input w-full text-[13px]">
              {FORMATS.map(f => <option key={f.key} value={f.key}>{f.label}</option>)}
            </select>
          </div>
          <div>
            <Label>Codec video</Label>
            <select value={output.video_codec}
              onChange={e => patch('video_codec', e.target.value as VideoCodec)}
              className="input w-full text-[13px]">
              {CODECS.map(c => <option key={c.key} value={c.key}>{c.label}</option>)}
            </select>
            <div className="text-[10px] text-zinc-500 mt-1">
              {CODECS.find(c => c.key === output.video_codec)?.desc}
            </div>
          </div>
        </div>
      </div>

      {/* ─── Resolution ────────────────────────────────────────────────── */}
      <div className="surface-card p-4">
        <h3 className="text-[13px] font-semibold mb-3">Độ phân giải (chiều dài cạnh dài)</h3>
        <div className="space-y-2">
          {RESOLUTIONS.map(r => (
            <label key={r.key} className="flex items-center gap-3 p-2 rounded hover:bg-zinc-50 dark:hover:bg-zinc-900 cursor-pointer">
              <input type="radio" checked={output.resolution === r.key}
                onChange={() => patch('resolution', r.key)} className="w-4 h-4" />
              <span className="text-[13px] flex-1">{r.label}</span>
              <span className="text-[11px] text-zinc-500 font-mono">~{r.rec_bitrate}</span>
            </label>
          ))}
        </div>
        {output.resolution === 'custom' && (
          <div className="grid grid-cols-2 gap-3 mt-3 pt-3 border-t border-zinc-200 dark:border-zinc-800">
            <div>
              <Label>Width (px)</Label>
              <input type="number" min={320} step={2} value={output.custom_width || 1920}
                onChange={e => patch('custom_width', parseInt(e.target.value) || 1920)}
                className="input w-full text-[13px]" />
            </div>
            <div>
              <Label>Height (px)</Label>
              <input type="number" min={240} step={2} value={output.custom_height || 1080}
                onChange={e => patch('custom_height', parseInt(e.target.value) || 1080)}
                className="input w-full text-[13px]" />
            </div>
          </div>
        )}
      </div>

      {/* ─── FPS + Bitrate ─────────────────────────────────────────────── */}
      <div className="surface-card p-4">
        <h3 className="text-[13px] font-semibold mb-3">Chất lượng</h3>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <div>
            <Label>FPS</Label>
            <div className="flex gap-1">
              {[24, 30, 60].map(f => (
                <button key={f} onClick={() => patch('fps', f)}
                  className={`flex-1 px-3 py-1.5 text-[12px] rounded-md border ${
                    output.fps === f
                      ? 'bg-blue-50 border-blue-400 text-blue-700 dark:bg-blue-900/30 dark:border-blue-700'
                      : 'border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                  }`}>
                  {f}
                </button>
              ))}
            </div>
          </div>
          <div>
            <Label>Bitrate video</Label>
            <input type="text" value={output.video_bitrate}
              onChange={e => patch('video_bitrate', e.target.value)}
              placeholder="vd 5M, 10M, 1500k"
              className="input w-full text-[13px] font-mono" />
            <div className="text-[10px] text-zinc-500 mt-1">Khuyên: {selectedRes?.rec_bitrate}</div>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <Label>Bitrate audio</Label>
            <select value={output.audio_bitrate}
              onChange={e => patch('audio_bitrate', e.target.value)}
              className="input w-full text-[13px]">
              <option value="128k">128 kbps</option>
              <option value="192k">192 kbps (khuyên dùng)</option>
              <option value="256k">256 kbps</option>
              <option value="320k">320 kbps</option>
            </select>
          </div>
          <div>
            <Label>Preset render</Label>
            <select value={output.preset}
              onChange={e => patch('preset', e.target.value as OutputConfig['preset'])}
              className="input w-full text-[13px]">
              {PRESETS.map(p => <option key={p.key} value={p.key}>{p.label}</option>)}
            </select>
            <div className="text-[10px] text-zinc-500 mt-1">
              {PRESETS.find(p => p.key === output.preset)?.desc}
            </div>
          </div>
        </div>

        {/* v4.0 — GPU acceleration */}
        <div className="mt-4 pt-4 border-t border-zinc-200 dark:border-zinc-700">
          <label className={`flex items-start gap-3 ${gpuInfo?.nvenc_available ? 'cursor-pointer' : 'opacity-60 cursor-not-allowed'}`}>
            <input type="checkbox"
              checked={output.use_gpu && !!gpuInfo?.nvenc_available}
              disabled={!gpuInfo?.nvenc_available}
              onChange={e => patch('use_gpu', e.target.checked)}
              className="w-4 h-4 mt-0.5" />
            <div className="flex-1">
              <div className="text-[13px] font-medium flex items-center gap-2">
                🚀 Sử dụng GPU (NVIDIA NVENC)
                {gpuInfo?.nvenc_available && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40">phát hiện GPU</span>
                )}
                {gpuInfo && !gpuInfo.nvenc_available && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-zinc-100 text-zinc-600 dark:bg-zinc-800">không có NVENC</span>
                )}
              </div>
              <div className="text-[11px] text-zinc-500 mt-0.5">
                {gpuInfo?.nvenc_available
                  ? 'Render nhanh 5-10× so với CPU. Chỉ hỗ trợ H.264/H.265.'
                  : 'Không phát hiện NVIDIA GPU. Cài driver + ffmpeg có NVENC để bật.'}
              </div>
            </div>
          </label>
        </div>
      </div>

      <div className="text-[11px] text-zinc-500 leading-relaxed bg-zinc-50 dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg p-3">
        💡 Ước lượng: video 10 phút 1080p H.264 5M ≈ 350MB · render preset Medium ≈ 5-15 phút.
      </div>
    </div>
  )
}

// ─── Helpers ────────────────────────────────────────────────────────────────

function Label({ children }: { children: React.ReactNode }) {
  return <label className="block text-[11px] text-zinc-500 mb-1.5 uppercase tracking-wider font-medium">{children}</label>
}

function formatRatio(r: number): string {
  // Tìm gcd nhỏ để hiển thị X:Y
  if (Math.abs(r - 16/9) < 0.01) return '16:9'
  if (Math.abs(r - 9/16) < 0.01) return '9:16'
  if (Math.abs(r - 4/3) < 0.01) return '4:3'
  if (Math.abs(r - 3/4) < 0.01) return '3:4'
  if (Math.abs(r - 1) < 0.01) return '1:1'
  if (Math.abs(r - 21/9) < 0.05) return '21:9'
  return r.toFixed(2)
}

function AspectIcon({ ratio, size }: { ratio: number; size: number }) {
  // SVG icon thể hiện tỉ lệ
  let w = size, h = size
  if (ratio >= 1) {
    h = size / ratio
  } else {
    w = size * ratio
  }
  return (
    <div className="flex items-center justify-center" style={{ width: size, height: size }}>
      <div className="border-2 border-current rounded-sm" style={{ width: w, height: h }} />
    </div>
  )
}

function computeDims(output: OutputConfig, sourceRatio: number | null): { w: number; h: number } | null {
  // Resolution → cạnh dài
  const longSides: Record<OutputResolution, number> = {
    '720p': 1280, '1080p': 1920, '1440p': 2560, '4k': 3840, 'custom': 0,
  }
  if (output.resolution === 'custom') {
    return { w: output.custom_width || 1920, h: output.custom_height || 1080 }
  }
  const longSide = longSides[output.resolution]

  // Aspect ratio
  let ratio: number | null = null
  if (output.aspect_ratio === 'source') ratio = sourceRatio
  else if (output.aspect_ratio === 'custom') {
    ratio = (output.custom_aspect_w || 16) / (output.custom_aspect_h || 9)
  } else {
    const preset = ASPECT_PRESETS.find(p => p.key === output.aspect_ratio)
    ratio = preset?.ratio || null
  }
  if (!ratio) return null

  // Cạnh dài = max(w,h). Nếu ratio >= 1 (ngang) → w = longSide, h = w/ratio.
  // Nếu ratio < 1 (dọc) → h = longSide, w = h*ratio.
  let w: number, h: number
  if (ratio >= 1) {
    w = longSide
    h = Math.round(longSide / ratio / 2) * 2  // làm tròn chẵn (yêu cầu encoder)
  } else {
    h = longSide
    w = Math.round(longSide * ratio / 2) * 2
  }
  return { w, h }
}
