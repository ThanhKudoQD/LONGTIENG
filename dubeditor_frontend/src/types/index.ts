// ─── Core types ──────────────────────────────────────────────────────────────

export interface Character {
  id: number
  project_id: number
  name: string
  description: string
  color: string
  avatar: string
  voxcpm_role_id: string | null
  voxcpm_actor_name: string
  voxcpm_role_name: string
  audio?: string
  shortcut_key?: string | null
  tts_speed?: number
  // v2 fields (giữ legacy data, không hiển thị)
  name_zh?: string | null
  aliases_zh?: string | null
  aliases_vi?: string | null
  role?: string                          // nam_chinh|nu_chinh|nam_phu|nu_phu|phan_dien|phu|khach
  gender?: 'nam' | 'nu' | '?'
  age_group?: string | null
  personality?: string                   // = char (mô tả 1 câu)
  relationships_json?: string | null
  notes?: string
  // v3 deprecated (đã bỏ trong Bible mới)
  social_status?: string | null
  speaking_style?: string
  self_address?: string | null
  addresses?: string | null
}

export interface Chapter {
  id: number
  project_id: number
  name: string
  start_sub_index: number
  end_sub_index: number
  status: 'pending' | 'in_progress' | 'done'
  collapsed: boolean
  sort_order: number
  created_at: string
}

export interface VoxRole {
  id: string
  character_name: string
  show_name: string
  type: string
  genre: string
  audio: string
  lora_path: string
}

export interface VoxActor {
  id: string
  name: string
  gender: string
  avatar: string
  roles: VoxRole[]
}

export interface Subtitle {
  id: number
  project_id: number
  scene_id?: number | null
  chunk_id?: number | null              // v3
  index: number
  start_time: number
  end_time: number
  text: string                           // text active (= text_v1 hoặc text_v2)
  original_text?: string | null
  character_id: number | null
  character?: Character
  audio_path: string | null
  audio_offset: number
  tts_done: boolean
  wav_duration: number | null
  tts_speed?: number | null
  // v2 fields
  speaker_zh?: string | null
  speaker_confidence?: 'h' | 'm' | 'l' | 'high' | 'mid' | 'low'
  speaker_reason?: string
  emotion?: string | null
  intensity?: number
  cps_value?: number | null
  needs_review?: boolean
  review_reason?: string
  text_draft?: string | null
  is_hook?: boolean
  translation_version?: number
  // v3: 2 variants
  text_v1?: string | null                // sát nghĩa (v1, ràng buộc rule)
  text_v2?: string | null                // thoát ý (v2, AI tự do)
  variant_selected?: 1 | 2
  // v3.1: noise filter — true nếu là marker [音乐] / (笑) / filler
  is_noise?: boolean
  // v3.2: Stage 0 normalize
  is_cleaned?: boolean
  original_raw?: string | null
  clean_reason?: string | null
  // v3: per-line voice mode
  tts_voice_mode?: string | null
  voice_mode?: string
  audio_voice_mode?: string | null
}

export interface Project {
  id: number
  name: string
  video_path: string | null
  video_name: string | null
  duration: number
  created_at: string
  subtitle_count: number
  tts_done_count: number
  current_chapter_id?: number | null
  source_lang?: 'zh' | 'vi'
  project_type?: 'short_drama' | 'drama_series' | 'movie'
  translate_status?: 'idle' | 'running' | 'done' | 'error'
  translate_progress?: number
  translate_error?: string | null
  has_bible?: boolean
  chunk_count?: number                   // v3
  scene_count?: number
  use_emotion_voice?: boolean
  tts_voice_mode?: string | null
}

// ─── Translate v3 types ──────────────────────────────────────────────────────

export type EmotionTag =
  | 'neutral' | 'happy' | 'sad' | 'angry' | 'cold' | 'tense'
  | 'intimate' | 'fearful' | 'sarcastic' | 'shocked' | 'determined'
  | 'regretful' | 'humorous' | 'threatening'

// Bible v3 (compact)

export interface BibleCharacter {
  zh: string
  vi: string
  alias?: string[]
  g?: 'nam' | 'nu' | '?'
  role?: string
  age?: string | null
  char?: string                          // tính cách + kiểu nói 1 câu
  rel?: Record<string, string>           // zh_name → quan hệ
  catchphrase?: string | null
}

export interface BibleStoryArc {
  index: number
  r: [number, number]                    // [start_line, end_line]
  t: string                              // title
  summary?: string                       // tóm tắt 2-3 câu (v3 mới)
  tone: string                           // tense|warm|sad|intimate|angry|neutral|mixed
}

export interface BibleCast { characters: BibleCharacter[] }

export interface BibleWorld {
  genre: string[]                        // ['đô thị', 'tổng tài', ...]
  era: string                            // hiện đại | cổ đại | dân quốc | tương lai
  tone: string
  plot: string
  arcs: BibleStoryArc[]
}

export interface GlossaryTerm {
  zh: string
  vi: string
  cat?: string                           // chuc_vu|tu_xung|dia_danh|khai_niem|cliche|khac
  n?: number                             // số lần xuất hiện
  note?: string | null
}

export interface BibleGlossary { terms: GlossaryTerm[] }

export interface Bible {
  id: number
  version: number
  is_active: boolean
  cast: BibleCast
  world: BibleWorld
  glossary: BibleGlossary
  tokens_in: number
  tokens_out: number
  cost_usd: number
  created_at?: string
}

// ─── Chunks + Scenes (v3 — 3 tầng) ───────────────────────────────────────────

export interface Chunk {
  id: number
  project_id: number
  arc_index: number
  chunk_index: number
  title: string
  start_line: number
  end_line: number
  status: 'pending' | 'speaker' | 'translated' | 'done' | 'error'
  line_count: number
  scene_count: number
  arc_title?: string | null
  arc_tone?: string | null
}

export interface Scene {
  id: number
  project_id: number
  scene_index: number
  start_line: number
  end_line: number
  start_time_sec: number
  end_time_sec: number
  location: string
  time_of_day?: string | null
  characters_present: string[]
  emotion_primary: EmotionTag
  emotion_arc: string
  summary: string
  purpose: string
  story_arc_id?: number | null
  chunk_id?: number | null               // v3
  is_hook: boolean
  is_emotion_peak: boolean
  status: 'pending' | 'speaker' | 'translated' | 'polished' | 'error'
  error_message?: string | null
  line_count: number
}

export interface StoryArc {
  id: number
  arc_index: number
  title: string
  summary: string
  start_line: number
  end_line: number
  emotional_tone: string
  key_events: string[]
  scene_count: number
}

// ─── Polish issues (v3 — đơn giản hóa) ───────────────────────────────────────

export type IssueType =
  | 'untranslated' | 'empty' | 'chinese_remains' | 'other'

export interface PolishIssue {
  id: number
  line_index: number
  subtitle_id?: number | null
  issue_type: IssueType
  description: string
  current_text: string
  suggested_text?: string | null
  confidence: 'h' | 'm' | 'l' | 'high' | 'mid' | 'low'
  evidence: string
  resolved: boolean
}

// ─── Pipeline status & progress ──────────────────────────────────────────────

export interface TranslateStatus {
  project_id: number
  status: 'idle' | 'running' | 'done' | 'error'
  current_stage?: string | null
  progress: number
  has_bible: boolean
  chunk_count: number                    // v3
  scene_count: number
  speaker_assigned_count: number
  translated_count: number
  variants_count: number                 // v3: dòng có text_v2
  review_count: number
  avg_cps: number
  cost_usd: number
  tokens_in: number
  tokens_out: number
  error_message?: string | null
  // v3.2: Stage 0 normalize
  cleaned_count?: number                 // số dòng đã được Stage 0 sửa
  removed_count?: number                 // số dòng đã bị Stage 0 đánh dấu noise
}

// v3.2: Stage 0 — dòng đã được chuẩn hóa
export interface CleanedSubtitle {
  id: number
  index: number
  start_time: number
  end_time: number
  original_raw: string | null            // text gốc trước Stage 0
  current_text: string                   // text hiện tại (rỗng nếu removed)
  is_noise: boolean                      // true = removed
  clean_reason: string | null            // AI giải thích lý do
  action: 'remove' | 'clean'             // derived
}

// v3.2: Stage 0 — kết quả scan heuristic (chưa qua AI)
export interface SuspiciousLine {
  index: number
  text: string
  reasons: string[]                      // lý do bị flag (regex pattern, watermark, ...)
}

export interface ScanResult {
  total_lines: number
  suspicious_count: number
  cluster_count: number
  suspicious_lines: SuspiciousLine[]
}

export interface Stage0RunResult {
  total_lines: number
  suspicious_count: number
  cluster_count: number
  removed_count: number
  cleaned_count: number
  kept_count: number
  cost_usd: number
  tokens_in: number
  tokens_out: number
}

export interface ProgressEvent {
  stage: string
  progress: number
  message: string
  detail?: Record<string, any>
}

// ─── Translate config (request) ──────────────────────────────────────────────

export type VariantMode = 'off' | 'important_only' | 'always'

export interface TranslateConfig {
  api_key: string
  provider: 'gemini' | 'openai' | 'deepseek'
  model_heavy: string
  model_medium: string
  model_light: string
  project_type: 'short_drama' | 'drama_series' | 'movie'
  cps_max: number | null
  concurrency: number
  source_lang: 'zh'
  // v3
  variant_mode: VariantMode
  chunk_overlap: number
  cache_enabled: boolean
  chunks_parallel: boolean  // Bước 2: true=song song, false=tuần tự (mặc định, tiết kiệm)
  speaker_parallel: boolean // Bước 3: true=song song (mặc định), false=tuần tự (cache Bible)
  speaker_context_window: number  // Bước 3: số dòng context trước/sau (mặc định 20)
  // v3.2: Stage 0 normalize
  stage0_enabled: boolean   // Bước 0: bật/tắt chuẩn hóa phụ đề
  stage0_model: string | null  // Model cho Stage 0 (null = dùng model_light)
  stage0_context_window: number  // Số dòng context xung quanh cluster (mặc định 10)
}

// ─── Retranslate (1 dòng) ────────────────────────────────────────────────────

export interface RetranslateResult {
  ok: boolean
  subtitle_id: number
  current_text_v1?: string | null
  current_text_v2?: string | null
  new_text_v1: string
  new_text_v2?: string | null
  emotion?: string
  intensity?: number
  tokens_in: number
  tokens_out: number
}

// ─── Utilities ───────────────────────────────────────────────────────────────

export const CHAR_COLORS = [
  '#185FA5', '#993C1D', '#0F6E56', '#854F0B', '#534AB7',
  '#D4537E', '#3B6D11', '#0C6E7A', '#7A2D6E', '#5F5E5A',
]

export function secToSrt(s: number): string {
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const sec = s % 60
  return `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${sec.toFixed(3).replace('.', ',').padStart(6,'0')}`
}

export function srtToSec(t: string): number {
  const [hms, ms] = t.replace(',','.').split('.')
  const [h, m, s] = hms.split(':').map(Number)
  return h*3600 + m*60 + s + (ms ? parseFloat('0.'+ms) : 0)
}

export function getEffectiveSpeed(sub: Subtitle, character?: Character | null): number {
  if (sub.tts_speed != null) return sub.tts_speed
  if (character?.tts_speed != null) return character.tts_speed
  return 1.0
}

// Confidence display
export function confidenceLabel(c: string | undefined): string {
  if (!c) return ''
  const m: Record<string, string> = {
    h: 'cao', high: 'cao',
    m: 'TB', mid: 'TB',
    l: 'thấp', low: 'thấp',
  }
  return m[c.toLowerCase()] || c
}

// Format helpers

export const EMOTION_LABELS: Record<string, string> = {
  neutral: 'Bình thường', happy: 'Vui', sad: 'Buồn', angry: 'Giận',
  cold: 'Lạnh', tense: 'Căng', intimate: 'Thân mật', fearful: 'Sợ',
  sarcastic: 'Mỉa mai', shocked: 'Sốc', determined: 'Quyết tâm',
  regretful: 'Hối hận', humorous: 'Hài hước', threatening: 'Đe dọa',
}

export const EMOTION_COLORS: Record<string, string> = {
  neutral: '#9CA3AF', happy: '#FBBF24', sad: '#60A5FA', angry: '#EF4444',
  cold: '#94A3B8', tense: '#F59E0B', intimate: '#EC4899', fearful: '#A855F7',
  sarcastic: '#06B6D4', shocked: '#F97316', determined: '#10B981',
  regretful: '#6366F1', humorous: '#84CC16', threatening: '#DC2626',
}

export const ROLE_LABELS: Record<string, string> = {
  nam_chinh: 'Nam chính', nu_chinh: 'Nữ chính',
  nam_phu: 'Nam phụ', nu_phu: 'Nữ phụ',
  phan_dien: 'Phản diện', phu: 'Phụ', khach: 'Khách',
}

export const ISSUE_TYPE_LABELS: Record<string, string> = {
  untranslated: 'Chưa dịch',
  empty: 'Rỗng',
  chinese_remains: 'Còn tiếng Trung',
  other: 'Khác',
}

export const VARIANT_MODE_LABELS: Record<VariantMode, string> = {
  off: 'Tắt (1 bản)',
  important_only: 'Cảnh quan trọng (2 bản)',
  always: 'Luôn 2 bản',
}

export const ARC_TONE_LABELS: Record<string, string> = {
  tense: 'Căng thẳng',
  warm: 'Ấm áp',
  sad: 'Buồn',
  intimate: 'Thân mật',
  angry: 'Giận dữ',
  neutral: 'Trung lập',
  mixed: 'Hỗn hợp',
}

export const GLOSSARY_CAT_LABELS: Record<string, string> = {
  tu_xung: 'Tự xưng',
  chuc_vu: 'Chức vụ / Danh xưng',
  dia_danh: 'Địa danh / Tổ chức',
  khai_niem: 'Khái niệm',
  cliche: 'Cliché / Cụm điển hình',
  khac: 'Khác',
}

export const GLOSSARY_CAT_ORDER = [
  'tu_xung', 'chuc_vu', 'dia_danh', 'khai_niem', 'cliche', 'khac',
]
