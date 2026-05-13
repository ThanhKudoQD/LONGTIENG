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
  // v2 fields
  name_zh?: string | null
  aliases_zh?: string | null            // JSON array string
  aliases_vi?: string | null
  role?: string                          // nam_chinh|nu_chinh|nam_phu|nu_phu|phan_dien|phu|khach
  gender?: 'nam' | 'nu' | '?'
  age_group?: string | null
  social_status?: string | null
  personality?: string
  speaking_style?: string
  self_address?: string | null           // JSON Pronouns
  addresses?: string | null              // JSON {char_zh: how_to_call}
  relationships_json?: string | null
  notes?: string
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
  index: number
  start_time: number
  end_time: number
  text: string
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
  speaker_confidence?: 'high' | 'mid' | 'low'
  speaker_reason?: string
  emotion?: string | null
  intensity?: number
  cps_value?: number | null
  needs_review?: boolean
  review_reason?: string
  text_draft?: string | null
  is_hook?: boolean
  translation_version?: number
  // v3: per-line voice mode override
  tts_voice_mode?: string | null
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
  // v2 fields
  project_type?: 'short_drama' | 'drama_series' | 'movie'
  genre_pack?: string | null
  translate_status?: 'idle' | 'running' | 'done' | 'error'
  translate_progress?: number
  translate_error?: string | null
  has_bible?: boolean
  scene_count?: number
  // v3: TTS toggle
  use_emotion_voice?: boolean
  tts_voice_mode?: string | null
}

// ─── Translate v2 types ──────────────────────────────────────────────────────

export type GenreMain =
  | 'do_thi' | 'co_trang' | 'dan_quoc' | 'tien_hiep'
  | 'huyen_huyen' | 'vo_hiep' | 'khoa_huyen' | 'khong_xac_dinh'

export type GenreSub =
  | 'ngon_tinh' | 'trong_sinh' | 'bao_thu' | 'cung_dau'
  | 'tong_tai' | 'chien_than' | 'hac_dao' | 'than_y'
  | 'trong_dau' | 'hai_huoc' | 'kinh_di' | 'trinh_tham'
  | 'gia_dau' | 'hoc_duong' | 'khong_xac_dinh'

export type EmotionTag =
  | 'neutral' | 'happy' | 'sad' | 'angry' | 'cold' | 'tense'
  | 'intimate' | 'fearful' | 'sarcastic' | 'shocked' | 'determined'
  | 'regretful' | 'humorous' | 'threatening'

// Bible (lấy từ DB qua BibleOut)

export interface Pronouns {
  default: string
  when_angry?: string | null
  when_intimate?: string | null
  when_formal?: string | null
  when_inferior?: string | null
  when_superior?: string | null
}

export interface BibleCharacter {
  zh: string
  vi: string
  aliases_zh?: string[]
  aliases_vi?: string[]
  role: string
  gender: string
  age_group?: string | null
  social_status?: string | null
  personality?: string
  speaking_style?: string
  self_address?: Pronouns
  addresses?: Record<string, string>
  relationships?: Record<string, string>
  notes?: string
}

export interface BibleStoryArc {
  index: number
  title: string
  summary: string
  start_line: number
  end_line: number
  emotional_tone: string
  key_events: string[]
}

export interface BibleCast { characters: BibleCharacter[] }

export interface BibleWorld {
  genre_main: GenreMain
  genre_sub: GenreSub[]
  era?: string | null
  setting?: string | null
  plot_summary?: string
  main_conflict?: string
  tone_overall?: string
  story_arcs: BibleStoryArc[]
}

export interface GlossaryTerm {
  zh: string
  vi: string
  category: string
  notes?: string
}

export interface BibleGlossary { terms: GlossaryTerm[] }

export interface Bible {
  id: number
  version: number
  is_active: boolean
  cast: BibleCast
  world: BibleWorld
  glossary: BibleGlossary
  genre_pack_id?: string | null
  tokens_in: number
  tokens_out: number
  cost_usd: number
  created_at?: string
}

// Scenes

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

// Polish issues

export type IssueType =
  | 'speaker' | 'pronoun' | 'consistency' | 'glossary'
  | 'intensity' | 'literal' | 'tts_unfriendly' | 'cps' | 'other'

export interface PolishIssue {
  id: number
  line_index: number
  subtitle_id?: number | null
  issue_type: IssueType
  description: string
  current_text: string
  suggested_text?: string | null
  confidence: 'high' | 'mid' | 'low'
  evidence: string
  resolved: boolean
}

// Pipeline status & progress

export interface TranslateStatus {
  project_id: number
  status: 'idle' | 'running' | 'done' | 'error'
  current_stage?: string | null
  progress: number
  has_bible: boolean
  scene_count: number
  speaker_assigned_count: number
  translated_count: number
  review_count: number
  avg_cps: number
  cost_usd: number
  tokens_in: number
  tokens_out: number
  error_message?: string | null
}

export interface ProgressEvent {
  stage: string
  progress: number
  message: string
  detail?: Record<string, any>
}

export interface GenrePackInfo {
  id: string
  name_vi: string
  name_zh: string
  description: string
}

// Translate config (request)

export interface TranslateConfig {
  api_key: string
  provider: 'gemini' | 'openai' | 'deepseek'
  model_heavy: string
  model_medium: string
  model_light: string
  project_type: 'short_drama' | 'drama_series' | 'movie'
  genre_pack: string | null
  cps_max: number | null
  concurrency: number
  source_lang: 'zh'
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

export const GENRE_MAIN_LABELS: Record<string, string> = {
  do_thi: 'Đô thị', co_trang: 'Cổ trang', dan_quoc: 'Dân quốc',
  tien_hiep: 'Tiên hiệp', huyen_huyen: 'Huyền huyễn', vo_hiep: 'Võ hiệp',
  khoa_huyen: 'Khoa huyễn', khong_xac_dinh: 'Chưa rõ',
}

export const GENRE_SUB_LABELS: Record<string, string> = {
  ngon_tinh: 'Ngôn tình', trong_sinh: 'Trọng sinh', bao_thu: 'Báo thù',
  cung_dau: 'Cung đấu', tong_tai: 'Tổng tài', chien_than: 'Chiến thần',
  hac_dao: 'Hắc đạo', than_y: 'Thần y', gia_dau: 'Gia đấu',
  hoc_duong: 'Học đường', hai_huoc: 'Hài hước', kinh_di: 'Kinh dị',
  trinh_tham: 'Trinh thám', khong_xac_dinh: 'Chưa rõ',
}

export const ISSUE_TYPE_LABELS: Record<string, string> = {
  speaker: 'Speaker sai', pronoun: 'Xưng hô', consistency: 'Không nhất quán',
  glossary: 'Thuật ngữ', intensity: 'Cường độ', literal: 'Dịch literal',
  tts_unfriendly: 'Khó phát âm', cps: 'CPS quá cao', other: 'Khác',
}