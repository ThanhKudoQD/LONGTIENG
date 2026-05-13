import axios from 'axios'
import type {
  Bible, Scene, StoryArc, PolishIssue,
  TranslateStatus, GenrePackInfo, TranslateConfig,
} from './types'

// API instance — timeout 5 phút cho LLM calls.
// Backend httpx 600s, FE 300s để fail-fast sớm hơn.
const api = axios.create({
  baseURL: '/dub/api',
  timeout: 300000,
})

export default api

// ─── Translate v2 API helpers ────────────────────────────────────────────────

// Status / control
export const translateApi = {
  getStatus: (pid: number) =>
    api.get<TranslateStatus>(`/projects/${pid}/translate/status`).then(r => r.data),

  start: (pid: number, config: TranslateConfig) =>
    api.post(`/projects/${pid}/translate/start`, config).then(r => r.data),

  runStage: (pid: number, config: TranslateConfig & { stage: string }) =>
    api.post(`/projects/${pid}/translate/run-stage`, config).then(r => r.data),

  cancel: (pid: number) =>
    api.post(`/projects/${pid}/translate/cancel`).then(r => r.data),

  reset: (pid: number) =>
    api.post(`/projects/${pid}/translate/reset`).then(r => r.data),

  // Bible
  getBible: (pid: number) =>
    api.get<Bible | null>(`/projects/${pid}/bible`).then(r => r.data),

  updateBible: (pid: number, payload: Partial<Pick<Bible, 'cast' | 'world' | 'glossary' | 'genre_pack_id'>>) =>
    api.put<Bible>(`/projects/${pid}/bible`, payload).then(r => r.data),

  listBibleVersions: (pid: number) =>
    api.get<Bible[]>(`/projects/${pid}/bibles`).then(r => r.data),

  // Scenes
  listScenes: (pid: number) =>
    api.get<Scene[]>(`/projects/${pid}/scenes`).then(r => r.data),

  getSceneDetail: (pid: number, sceneId: number) =>
    api.get<{ scene: Scene; subtitles: any[] }>(`/projects/${pid}/scenes/${sceneId}`).then(r => r.data),

  // Story arcs
  listStoryArcs: (pid: number) =>
    api.get<StoryArc[]>(`/projects/${pid}/story-arcs`).then(r => r.data),

  // Polish issues
  listIssues: (pid: number, filter?: { resolved?: boolean; issue_type?: string }) => {
    const params = new URLSearchParams()
    if (filter?.resolved !== undefined) params.set('resolved', String(filter.resolved))
    if (filter?.issue_type) params.set('issue_type', filter.issue_type)
    const qs = params.toString() ? `?${params.toString()}` : ''
    return api.get<PolishIssue[]>(`/projects/${pid}/polish-issues${qs}`).then(r => r.data)
  },

  applyIssue: (pid: number, issueId: number) =>
    api.post(`/projects/${pid}/polish-issues/${issueId}/apply`).then(r => r.data),

  dismissIssue: (pid: number, issueId: number) =>
    api.post(`/projects/${pid}/polish-issues/${issueId}/dismiss`).then(r => r.data),

  // Retranslate 1 line
  retranslate: (pid: number, payload: {
    subtitle_id: number
    hint: string
    api_key: string
    provider?: 'gemini' | 'openai' | 'deepseek'
    model?: string
    variants?: number
  }) =>
    api.post<{
      ok: boolean
      subtitle_id: number
      current_text: string
      variants: string[]
      tokens_in: number
      tokens_out: number
    }>(`/projects/${pid}/translate/retranslate`, payload).then(r => r.data),

  // Genre packs (global, không phụ thuộc project)
  listGenrePacks: () =>
    api.get<GenrePackInfo[]>(`/translate/genre-packs`).then(r => r.data),
}

// ─── SSE progress stream ─────────────────────────────────────────────────────

export interface ProgressMessage {
  stage: string
  progress: number
  message: string
  detail?: Record<string, any>
}

export interface LLMCallMessage {
  call_idx: number
  stage_tag: string
  model: string
  provider: string
  attempt: number
  prompt_length: number
  prompt_preview: string
  temperature: number
  json_mode: boolean
  ok: boolean
  // Khi ok=true
  tokens_in?: number
  tokens_out?: number
  cached_tokens?: number
  timing_ms?: number
  finish_reason?: string
  response_length?: number
  response_preview?: string
  // Khi ok=false
  error?: string
}

/**
 * Mở SSE stream cho progress của 1 project.
 *
 * @param pid project ID
 * @param onProgress callback khi nhận event progress
 * @param onLlmCall callback khi nhận event llm_call (kèm prompt + response)
 * @param onError callback khi mất connection / lỗi
 * @returns hàm close() để đóng stream
 */
export function openProgressSSE(
  pid: number,
  onProgress: (msg: ProgressMessage) => void,
  onLlmCall?: (msg: LLMCallMessage) => void,
  onError?: (err: Event) => void,
): () => void {
  const url = `/dub/api/projects/${pid}/translate/progress`
  const es = new EventSource(url)

  es.addEventListener('ready', () => {
    // Initial connection ack — không cần xử lý
  })

  es.addEventListener('progress', (e: MessageEvent) => {
    try {
      const data = JSON.parse(e.data) as ProgressMessage
      onProgress(data)
    } catch (err) {
      console.error('[SSE] parse error', err, e.data)
    }
  })

  es.addEventListener('llm_call', (e: MessageEvent) => {
    if (!onLlmCall) return
    try {
      const data = JSON.parse(e.data) as LLMCallMessage
      onLlmCall(data)
    } catch (err) {
      console.error('[SSE] llm_call parse error', err, e.data)
    }
  })

  es.onerror = (err) => {
    if (onError) onError(err)
  }

  return () => es.close()
}