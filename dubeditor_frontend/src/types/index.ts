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
  index: number
  start_time: number
  end_time: number
  text: string
  character_id: number | null
  character?: Character
  audio_path: string | null
  audio_offset: number
  tts_done: boolean
  wav_duration: number | null
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
}

export const CHAR_COLORS = [
  '#185FA5','#993C1D','#0F6E56','#854F0B','#534AB7',
  '#D4537E','#3B6D11','#0C6E7A','#7A2D6E','#5F5E5A',
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
