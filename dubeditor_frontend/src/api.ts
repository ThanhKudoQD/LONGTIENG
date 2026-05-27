import axios from 'axios'
import type {
  Bible, Scene, StoryArc, Chunk, PolishIssue,
  TranslateStatus, TranslateConfig, RetranslateResult,
  RetranslateChunkResult,
  CleanedSubtitle, ScanResult, Stage0RunResult,
  ApiKeys, ModelPreset, ModelPresetInput,
} from './types'

// API instance — timeout 5 phút cho LLM calls.
const api = axios.create({
  baseURL: '/dub/api',
  timeout: 300000,
})

export default api

// ─── Translate v3 API helpers ────────────────────────────────────────────────

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

  // v3.9: Persistent logs (load lại khi F5 / mở lại Translate)
  listEvents: (pid: number, limit = 500) =>
    api.get<ProgressMessage[]>(`/projects/${pid}/translate/events?limit=${limit}`)
       .then(r => r.data),

  listLlmCalls: (pid: number, limit = 200) =>
    api.get<LLMCallMessage[]>(`/projects/${pid}/translate/llm-calls?limit=${limit}`)
       .then(r => r.data),

  clearLogs: (pid: number) =>
    api.delete(`/projects/${pid}/translate/logs`).then(r => r.data),

  // Bible
  getBible: (pid: number) =>
    api.get<Bible | null>(`/projects/${pid}/bible`).then(r => r.data),

  updateBible: (pid: number, payload: Partial<Pick<Bible, 'cast' | 'world' | 'glossary'>>) =>
    api.put<Bible>(`/projects/${pid}/bible`, payload).then(r => r.data),

  listBibleVersions: (pid: number) =>
    api.get<Bible[]>(`/projects/${pid}/bibles`).then(r => r.data),

  // Chunks v3
  listChunks: (pid: number) =>
    api.get<Chunk[]>(`/projects/${pid}/chunks`).then(r => r.data),

  getChunkDetail: (pid: number, chunkId: number) =>
    api.get<any>(`/projects/${pid}/chunks/${chunkId}`).then(r => r.data),

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

  // Stage 0 normalize — danh sách dòng đã clean / remove
  listCleaned: (pid: number) =>
    api.get<CleanedSubtitle[]>(`/projects/${pid}/translate/normalize/cleaned`).then(r => r.data),

  revertCleaned: (pid: number, subtitleId: number) =>
    api.post(`/projects/${pid}/translate/normalize/revert/${subtitleId}`).then(r => r.data),

  // Stage 0 — Quét heuristic preview (không gọi AI)
  scanSuspicious: (pid: number) =>
    api.get<ScanResult>(`/projects/${pid}/translate/normalize/scan`).then(r => r.data),

  // Stage 0 — Chạy full (scan + AI) SYNC. Đợi xong rồi trả kết quả.
  runNormalize: (pid: number, config: TranslateConfig) =>
    api.post<Stage0RunResult>(`/projects/${pid}/translate/normalize/run`, config, {
      timeout: 10 * 60 * 1000,  // 10 phút cho task nặng
    }).then(r => r.data),

  applyIssue: (pid: number, issueId: number) =>
    api.post(`/projects/${pid}/polish-issues/${issueId}/apply`).then(r => r.data),

  dismissIssue: (pid: number, issueId: number) =>
    api.post(`/projects/${pid}/polish-issues/${issueId}/dismiss`).then(r => r.data),

  // Retranslate 1 line — trả 2 bản v1/v2
  retranslate: (pid: number, payload: {
    subtitle_id: number
    hint: string
    api_key: string
    provider?: 'gemini' | 'openai' | 'deepseek'
    model?: string
    thinking?: boolean | null     // v3.3: toggle thinking (mặc định false ở BE)
    context_window?: number       // v3.6: số dòng context trước/sau (1-5, default 2)
  }) =>
    api.post<RetranslateResult>(`/projects/${pid}/translate/retranslate`, payload).then(r => r.data),

  // v3.6: Retranslate BATCH — dịch lại 1-5 dòng cùng lúc
  retranslateBatch: (pid: number, payload: {
    subtitle_ids: number[]
    hint: string
    api_key: string
    provider?: 'gemini' | 'openai' | 'deepseek'
    model?: string
    thinking?: boolean | null
    context_window?: number       // số dòng context trước/sau (1-5, default 2)
  }) =>
    api.post<{
      ok: boolean
      lines: Array<{
        line_index: number
        subtitle_id: number
        text_v1: string
        text_v2: string | null
        emotion: string | null
        intensity: number | null
        current_text_v1: string | null
        current_text_v2: string | null
      }>
      tokens_in: number
      tokens_out: number
    }>(`/projects/${pid}/translate/retranslate-batch`, payload).then(r => r.data),

  // v3.13: Retranslate 1 CHUNK
  retranslateChunk: (pid: number, payload: {
    chunk_id: number
    mode: 'all' | 'errors_only'
    api_key: string
    provider?: 'gemini' | 'openai' | 'deepseek'
    // Có thể truyền full TranslateConfig (model per-stage, thinking, variant_mode...)
    // Backend kế thừa TranslateConfig nên mọi field config đều được nhận.
    [key: string]: any
  }) =>
    api.post<RetranslateChunkResult>(
      `/projects/${pid}/translate/retranslate-chunk`,
      payload
    ).then(r => r.data),

  // v3: chọn variant cho 1 dòng
  selectVariant: (pid: number, subtitleId: number, variant: 1 | 2) =>
    api.post(`/projects/${pid}/subtitles/${subtitleId}/select-variant`, { variant })
       .then(r => r.data),

  // v3: bulk chọn variant
  bulkSelectVariant: (pid: number, variant: 1 | 2, subtitleIds?: number[]) =>
    api.post(`/projects/${pid}/subtitles/bulk-select-variant`,
             { variant, subtitle_ids: subtitleIds || null })
       .then(r => r.data),
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

// ─── v3.12: Settings (API keys + Model Presets) ─────────────────────

export const settingsApi = {
  getApiKeys: () =>
    api.get<ApiKeys>('/settings/api-keys').then(r => r.data),

  putApiKeys: (keys: Partial<ApiKeys>) =>
    api.put('/settings/api-keys', keys).then(r => r.data),

  listPresets: () =>
    api.get<ModelPreset[]>('/settings/presets').then(r => r.data),

  createPreset: (preset: ModelPresetInput) =>
    api.post<ModelPreset>('/settings/presets', preset).then(r => r.data),

  updatePreset: (id: number, preset: ModelPresetInput) =>
    api.put<ModelPreset>(`/settings/presets/${id}`, preset).then(r => r.data),

  deletePreset: (id: number) =>
    api.delete(`/settings/presets/${id}`).then(r => r.data),

  setDefaultPreset: (id: number) =>
    api.post(`/settings/presets/${id}/default`).then(r => r.data),
}


// ─── v3.15: Manual Translate (Dịch Thủ công) ────────────────────────────────
//
// Code build prompt → user copy ra ChatGPT/Claude/Gemini web → user paste
// response về → code parse và lưu DB. KHÔNG gọi API LLM thật.

export interface ManualStageInfo {
  stage: string
  label: string
  description: string
  ready: boolean
  has_data: boolean
  units_count: number
  dependency_msg?: string | null
  // v3.15: progress thủ công
  applied_units_count: number
  built_units_count: number
  failed_units_count: number
}

export interface ManualUnitInfo {
  unit_key: string
  label: string
  status: string  // pending | built | applied | failed
  has_prompt: boolean
  has_response: boolean
  applied_at?: string | null
  apply_summary?: string | null
}

export interface ManualBuiltPrompt {
  stage: string
  unit_key: string
  label: string
  prompt: string
  meta: Record<string, any>
  char_count: number
  // v3.15
  status: string
  raw_response: string
  apply_summary?: string | null
  applied_at?: string | null
  from_cache: boolean
}

export interface ManualApplyResult {
  stage: string
  unit_key: string
  ok: boolean
  summary: string
  counts: Record<string, number>
  warnings: string[]
  errors: string[]
  status: string
  applied_at?: string | null
}

export interface ManualUnitState {
  stage: string
  unit_key: string
  label?: string | null
  status: string
  prompt: string
  raw_response: string
  meta: Record<string, any>
  apply_summary?: string | null
  apply_counts: Record<string, number>
  apply_warnings: string[]
  apply_errors: string[]
  built_at?: string | null
  applied_at?: string | null
  updated_at?: string | null
}

export const manualTranslateApi = {
  listStages: (pid: number) =>
    api.get<ManualStageInfo[]>(`/projects/${pid}/manual-translate/stages`)
       .then(r => r.data),

  listUnits: (pid: number, stage: string) =>
    api.get<ManualUnitInfo[]>(`/projects/${pid}/manual-translate/units`, {
      params: { stage }
    }).then(r => r.data),

  buildPrompt: (pid: number, stage: string, unit_key?: string,
                force_rebuild = false) =>
    api.post<ManualBuiltPrompt>(`/projects/${pid}/manual-translate/build-prompt`, {
      stage, unit_key, force_rebuild
    }).then(r => r.data),

  applyResponse: (pid: number, stage: string, unit_key: string,
                   meta: Record<string, any>, raw_response: string) =>
    api.post<ManualApplyResult>(`/projects/${pid}/manual-translate/apply-response`, {
      stage, unit_key, meta, raw_response
    }).then(r => r.data),

  // v3.15: persistence
  getUnitState: (pid: number, stage: string, unit_key: string) =>
    api.get<ManualUnitState | null>(`/projects/${pid}/manual-translate/unit-state`, {
      params: { stage, unit_key }
    }).then(r => r.data),

  savePromptEdit: (pid: number, stage: string, unit_key: string, prompt: string) =>
    api.post(`/projects/${pid}/manual-translate/save-prompt-edit`, {
      stage, unit_key, prompt
    }).then(r => r.data),

  saveResponseDraft: (pid: number, stage: string, unit_key: string,
                       raw_response: string) =>
    api.post(`/projects/${pid}/manual-translate/save-response-draft`, {
      stage, unit_key, raw_response
    }).then(r => r.data),

  resetUnit: (pid: number, stage: string, unit_key?: string) =>
    api.post(`/projects/${pid}/manual-translate/reset`, {
      stage, unit_key
    }).then(r => r.data),
}

// ─── v4: Manual Translate Mega-Chunk ───────────────────────────────────────
//
// Workflow tối ưu: 5 stage, ~10-13 paste/phim (vs 60 của v3).
// 4 endpoint chính ở /manual-translate-mega/*, 4 endpoint phụ
// (unit-state, save-prompt-edit, save-response-draft, reset) dùng lại v3
// nhưng stage có hậu tố "_mega" để namespace tách biệt.

export interface ManualMegaStageInfo extends ManualStageInfo {
  expected_units: number
}

const M = (stage: string) => stage.endsWith('_mega') ? stage : stage + '_mega'

export const manualTranslateMegaApi = {
  // ─── 4 endpoint v4 chính ──────────────────────────────────────
  listStages: (pid: number) =>
    api.get<ManualMegaStageInfo[]>(`/projects/${pid}/manual-translate-mega/stages`)
       .then(r => r.data),

  listUnits: (pid: number, stage: string) =>
    api.get<ManualUnitInfo[]>(`/projects/${pid}/manual-translate-mega/units`, {
      params: { stage }
    }).then(r => r.data),

  buildPrompt: async (pid: number, stage: string, unit_key?: string,
                       _force_rebuild = false,
                       options?: Record<string, any>): Promise<ManualBuiltPrompt> => {
    const r = await api.post<{
      stage: string; unit_key: string; label: string;
      prompt: string; meta: Record<string, any>;
      char_count: number; estimated_tokens: number;
    }>(`/projects/${pid}/manual-translate-mega/build-prompt`, {
      stage, unit_key, options
    })
    // Backend v4 không trả status/raw_response/from_cache → bù từ getUnitState
    let extra: Partial<ManualBuiltPrompt> = {
      status: 'built',
      raw_response: '',
      apply_summary: null,
      applied_at: null,
      from_cache: false,
    }
    try {
      const state = await manualTranslateMegaApi.getUnitState(
        pid, r.data.stage, r.data.unit_key
      )
      if (state) {
        extra = {
          status: state.status,
          raw_response: state.raw_response || '',
          apply_summary: state.apply_summary,
          applied_at: state.applied_at,
          from_cache: !!state.raw_response,
        }
      }
    } catch { /* state có thể chưa tồn tại — OK */ }
    return { ...r.data, ...extra } as ManualBuiltPrompt
  },

  // v4.1: lấy schema options cho 1 stage (vd presets + advanced flags)
  getStageOptions: (pid: number, stage: string) =>
    api.get<{
      stage: string
      presets: Array<{ key: string; label: string; description: string }>
      default_preset?: string
      advanced: Array<{
        key: string
        label: string
        type: string
        default: any
      }>
    }>(`/projects/${pid}/manual-translate-mega/stage-options`, {
      params: { stage }
    }).then(r => r.data),

  applyResponse: async (pid: number, stage: string, unit_key: string,
                         meta: Record<string, any>, raw_response: string
                         ): Promise<ManualApplyResult> => {
    const r = await api.post<{
      stage: string; unit_key: string; ok: boolean; summary: string;
      counts: Record<string, number>; warnings: string[]; errors: string[];
    }>(`/projects/${pid}/manual-translate-mega/apply-response`, {
      stage, unit_key, meta, raw_response
    })
    return {
      ...r.data,
      status: r.data.ok ? 'applied' : 'failed',
      applied_at: r.data.ok ? new Date().toISOString() : null,
    }
  },

  // ─── 4 endpoint phụ — gọi v3 với stage có hậu tố "_mega" ───────
  getUnitState: (pid: number, stage: string, unit_key: string) =>
    api.get<ManualUnitState | null>(`/projects/${pid}/manual-translate/unit-state`, {
      params: { stage: M(stage), unit_key }
    }).then(r => r.data),

  savePromptEdit: (pid: number, stage: string, unit_key: string, prompt: string) =>
    api.post(`/projects/${pid}/manual-translate/save-prompt-edit`, {
      stage: M(stage), unit_key, prompt
    }).then(r => r.data),

  saveResponseDraft: (pid: number, stage: string, unit_key: string,
                       raw_response: string) =>
    api.post(`/projects/${pid}/manual-translate/save-response-draft`, {
      stage: M(stage), unit_key, raw_response
    }).then(r => r.data),

  resetUnit: (pid: number, stage: string, unit_key?: string) =>
    api.post(`/projects/${pid}/manual-translate/reset`, {
      stage: M(stage), unit_key
    }).then(r => r.data),

  // ─── v4.2: Reset Bible (xóa Bible + Characters + StoryArcs) ────
  resetBible: (pid: number) =>
    api.delete<{
      ok: boolean
      summary: string
      counts: Record<string, number>
    }>(`/projects/${pid}/manual-translate-mega/bible`)
       .then(r => r.data),

  // ─── v4.2: Mega target config ─────────────────────────────────
  getMegaTarget: (pid: number) =>
    api.get<{
      target: number
      default: number
      min: number
      max: number
    }>(`/projects/${pid}/manual-translate-mega/mega-target`)
       .then(r => r.data),

  setMegaTarget: (pid: number, target: number) =>
    api.put<{ ok: boolean; target: number }>(
      `/projects/${pid}/manual-translate-mega/mega-target`,
      { target }
    ).then(r => r.data),
}
