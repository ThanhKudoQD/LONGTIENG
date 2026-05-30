/**
 * Types cho module Export Video.
 *
 * Config được sinh dưới dạng JSON gửi xuống BE để FFmpeg render.
 * Mỗi field tách rõ ràng từng tab.
 */

// ─── Cắt video ───────────────────────────────────────────────────────────────

export interface VideoClip {
  id: string                  // uuid local cho React key
  source_start: number        // giây — vị trí trong video gốc
  source_end: number          // giây
  label?: string              // tên gợi nhớ, vd "Intro", "Tập 1"
}

// ─── Phụ đề ──────────────────────────────────────────────────────────────────

export type SubPosition = 'top' | 'middle' | 'bottom'

export interface SubtitleStyle {
  enabled: boolean
  font_family: string
  font_size: number           // 12-72
  color: string               // hex #FFFFFF
  outline_enabled: boolean
  outline_color: string
  outline_width: number       // 0-6
  position: SubPosition
  y_offset: number            // px, có thể âm
  bold: boolean
  italic: boolean
  // Nền chữ (background box)
  background_enabled: boolean
  background_color: string
  background_opacity: number  // 0-1
  // Đổ bóng
  shadow_enabled: boolean
  shadow_color: string
  shadow_blur: number
}

// ─── Padding ─────────────────────────────────────────────────────────────────

export interface PaddingSide {
  enabled: boolean
  height_px: number           // chiều cao thanh padding
  color: string
}

export interface PaddingConfig {
  top: PaddingSide
  bottom: PaddingSide
}

// ─── Watermark ───────────────────────────────────────────────────────────────

export type WatermarkPosition =
  | 'top_left' | 'top_right' | 'top_center'
  | 'bottom_left' | 'bottom_right' | 'bottom_center'
  | 'center'

export interface WatermarkText {
  id: string
  type: 'text'
  text: string
  font_family: string
  font_size: number
  color: string
  opacity: number             // 0-1
  position: WatermarkPosition
  x_offset: number
  y_offset: number
  start_time: number          // giây
  duration: number | null     // null = suốt video
}

export interface WatermarkImage {
  id: string
  type: 'image'
  image_path: string          // path sau khi upload
  image_url?: string          // url để preview
  width_px: number
  opacity: number
  position: WatermarkPosition
  x_offset: number
  y_offset: number
  start_time: number
  duration: number | null
}

export type Watermark = WatermarkText | WatermarkImage

// ─── Audio (BGM tracks) ──────────────────────────────────────────────────────

export interface AudioTrack {
  id: string
  name: string                // tên gợi nhớ
  file_path: string           // path sau upload (BE)
  file_url?: string           // url để preview
  start_time: number          // giây — vị trí trong output video
  end_time: number            // giây
  duration_orig: number       // độ dài file gốc (để biết max)
  volume: number              // 0-1
  fade_in: number             // giây
  fade_out: number
  loop: boolean               // nếu file ngắn hơn end-start
}

export interface AudioConfig {
  voice_volume: number        // âm lượng TTS chính
  voice_enabled: boolean      // có chèn TTS không (mặc định true)
  ducking_enabled: boolean    // tự giảm BGM khi voice nói
  ducking_amount: number      // % giảm khi ducking (0-1, default 0.5)
  tracks: AudioTrack[]
}

// ─── Output ──────────────────────────────────────────────────────────────────

export type OutputResolution = '720p' | '1080p' | '1440p' | '4k' | 'custom'
export type OutputFormat = 'mp4' | 'mov' | 'webm'
export type VideoCodec = 'h264' | 'h265' | 'vp9'

// Aspect ratio = khung hình. Quyết định layout của TẤT CẢ preview + overlay.
export type AspectRatio = '16:9' | '9:16' | '4:3' | '1:1' | 'source' | 'custom'

// Khi tỉ lệ output ≠ tỉ lệ video gốc → cần chiến lược fit:
//   letterbox: thanh đen 2 bên/trên dưới (an toàn, không mất hình)
//   crop:      cắt phần thừa giữ trọng tâm (đẹp nhưng mất hình ngoài)
//   pad_color: như letterbox nhưng padding = padding.color (kết hợp với tab Padding)
export type FitMode = 'letterbox' | 'crop' | 'pad_color'

export interface OutputConfig {
  format: OutputFormat
  resolution: OutputResolution
  custom_width?: number
  custom_height?: number
  fps: number                 // 24/30/60
  video_codec: VideoCodec
  video_bitrate: string       // "5M", "8M"...
  audio_bitrate: string       // "192k"
  preset: 'ultrafast' | 'fast' | 'medium' | 'slow'  // ffmpeg preset (tốc độ vs chất lượng)
  // Tỉ lệ khung hình
  aspect_ratio: AspectRatio
  custom_aspect_w?: number    // chỉ dùng khi aspect_ratio = 'custom'
  custom_aspect_h?: number
  fit_mode: FitMode           // chiến lược khi tỉ lệ khác video gốc
  use_gpu: boolean            // v4.0: dùng GPU encoder nếu có (NVIDIA NVENC)
}

// ─── Tổng hợp ───────────────────────────────────────────────────────────────

export interface ExportConfig {
  clips: VideoClip[]          // rỗng = export toàn bộ video
  subtitle_style: SubtitleStyle
  padding: PaddingConfig
  watermarks: Watermark[]
  audio: AudioConfig
  output: OutputConfig
}

// ─── Job state ──────────────────────────────────────────────────────────────

export type JobStatus = 'pending' | 'running' | 'done' | 'error' | 'cancelled'

export interface ExportJob {
  id: number
  project_id: number
  status: JobStatus
  progress_percent: number    // 0-100
  output_path?: string        // có khi done
  output_url?: string         // url download
  error_msg?: string
  config: ExportConfig
  created_at: string
  started_at?: string         // v4.0 — khi job thực sự bắt đầu render
  finished_at?: string
  estimated_remaining_sec?: number
}

// ─── Preset ─────────────────────────────────────────────────────────────────

export interface ExportPreset {
  id: number
  name: string
  config: Partial<ExportConfig>   // có thể save 1 phần (vd chỉ style sub)
  created_at: string
}

// ─── Defaults ────────────────────────────────────────────────────────────────

export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  enabled: true,
  font_family: 'Be Vietnam Pro',
  font_size: 32,
  color: '#FFFFFF',
  outline_enabled: true,
  outline_color: '#000000',
  outline_width: 2,
  position: 'bottom',
  y_offset: 0,
  bold: true,
  italic: false,
  background_enabled: false,
  background_color: '#000000',
  background_opacity: 0.5,
  shadow_enabled: false,
  shadow_color: '#000000',
  shadow_blur: 4,
}

export const DEFAULT_PADDING: PaddingConfig = {
  top: { enabled: false, height_px: 100, color: '#000000' },
  bottom: { enabled: false, height_px: 120, color: '#000000' },
}

export const DEFAULT_AUDIO: AudioConfig = {
  voice_volume: 1.0,
  voice_enabled: true,
  ducking_enabled: false,
  ducking_amount: 0.5,
  tracks: [],
}

export const DEFAULT_OUTPUT: OutputConfig = {
  format: 'mp4',
  resolution: '1080p',
  fps: 30,
  video_codec: 'h264',
  video_bitrate: '5M',
  audio_bitrate: '192k',
  preset: 'medium',
  aspect_ratio: 'source',
  fit_mode: 'letterbox',
  use_gpu: true,
}

export const DEFAULT_CONFIG: ExportConfig = {
  clips: [],
  subtitle_style: DEFAULT_SUBTITLE_STYLE,
  padding: DEFAULT_PADDING,
  watermarks: [],
  audio: DEFAULT_AUDIO,
  output: DEFAULT_OUTPUT,
}

// ─── Tab keys ────────────────────────────────────────────────────────────────

export type ExportTab = 'cut' | 'subtitle' | 'padding' | 'watermark' | 'audio' | 'output'

export const TAB_META: { key: ExportTab; label: string; icon: string }[] = [
  { key: 'cut',       label: 'Cắt',       icon: '✂' },
  { key: 'subtitle',  label: 'Phụ đề',    icon: 'Aa' },
  { key: 'padding',   label: 'Padding',   icon: '▭' },
  { key: 'watermark', label: 'Watermark', icon: '©' },
  { key: 'audio',     label: 'Audio',     icon: '♪' },
  { key: 'output',    label: 'Output',    icon: '⚙' },
]

// ─── Position presets cho watermark ──────────────────────────────────────────

export const WATERMARK_POSITIONS: { key: WatermarkPosition; label: string }[] = [
  { key: 'top_left',      label: '↖ Trên trái' },
  { key: 'top_center',    label: '↑ Trên giữa' },
  { key: 'top_right',     label: '↗ Trên phải' },
  { key: 'center',        label: '◉ Giữa' },
  { key: 'bottom_left',   label: '↙ Dưới trái' },
  { key: 'bottom_center', label: '↓ Dưới giữa' },
  { key: 'bottom_right',  label: '↘ Dưới phải' },
]

// ─── Font list (sẽ load từ BE trong tương lai, hiện hardcode font phổ biến)

export const FONT_FAMILIES = [
  'Be Vietnam Pro',
  'Roboto',
  'Inter',
  'Open Sans',
  'Montserrat',
  'Noto Sans',
  'Arial',
  'Helvetica',
  'Times New Roman',
  'Georgia',
]

// ─── Aspect ratio presets ────────────────────────────────────────────────────

export const ASPECT_PRESETS: { key: AspectRatio; label: string; ratio: number | null; icon: string }[] = [
  { key: '16:9',   label: '16:9 — Ngang YouTube',  ratio: 16/9,  icon: '▭' },
  { key: '9:16',   label: '9:16 — Dọc TikTok/Shorts/Reels', ratio: 9/16,  icon: '▯' },
  { key: '4:3',    label: '4:3 — TV cổ điển',      ratio: 4/3,   icon: '□' },
  { key: '1:1',    label: '1:1 — Vuông Instagram', ratio: 1,     icon: '◻' },
  { key: 'source', label: 'Theo video gốc',        ratio: null,  icon: '↔' },
  { key: 'custom', label: 'Tùy chỉnh',             ratio: null,  icon: '✎' },
]

export const FIT_MODES: { key: FitMode; label: string; desc: string }[] = [
  { key: 'letterbox', label: 'Letterbox', desc: 'Thanh đen 2 bên/trên dưới — giữ TOÀN BỘ video, không mất gì' },
  { key: 'crop',      label: 'Crop center', desc: 'Cắt phần thừa, giữ trung tâm — có thể mất nội dung ngoài rìa' },
  { key: 'pad_color', label: 'Pad theo màu', desc: 'Như letterbox nhưng dùng màu từ tab Padding (TikTok style)' },
]

/**
 * Tính ratio (width/height) thực tế dựa vào aspect_ratio config + video source.
 * sourceRatio = ratio của video gốc (chỉ dùng khi aspect = 'source').
 * Trả về null nếu không xác định được (chưa có video).
 */
export function getEffectiveRatio(
  output: OutputConfig,
  sourceRatio: number | null,
): number | null {
  if (output.aspect_ratio === 'source') return sourceRatio
  if (output.aspect_ratio === 'custom') {
    const w = output.custom_aspect_w || 16
    const h = output.custom_aspect_h || 9
    return w / h
  }
  return ASPECT_PRESETS.find(p => p.key === output.aspect_ratio)?.ratio ?? null
}
