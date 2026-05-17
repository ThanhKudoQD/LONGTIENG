/**
 * ConfigModal — backward-compatibility shim.
 *
 * Bản v3 đã chuyển cấu hình sang ConfigPanel trong TranslatePage.
 * File này chỉ giữ lại helpers `loadConfig` + `getApiKey` cho các
 * component cũ (SubtitleList retranslate inline).
 *
 * Storage key thống nhất: 'translate_config_v3'
 * Có fallback đọc 'translate_config_v2' cho user cũ.
 */
const STORAGE_KEY = 'translate_config_v3'
const LEGACY_KEY = 'translate_config_v2'

export interface TranslateConfig {
  // v3.5: api_keys dạng object theo provider (ConfigPanel mới ghi)
  api_keys?: {
    gemini: string
    openai: string
    deepseek: string
  }
  // Legacy: api_key dạng string đơn (data cũ trước migration)
  api_key?: string
  provider: 'gemini' | 'openai' | 'deepseek'
  model_heavy: string
  model_medium: string
  model_light: string
  concurrency: number
  // v3 fields (optional)
  variant_mode?: 'off' | 'important_only' | 'always'
  chunk_overlap?: number
  cache_enabled?: boolean
  heavy_thinking?: boolean | null
  medium_thinking?: boolean | null
  light_thinking?: boolean | null
  translate_thinking?: boolean | null
  // v3.5: per-stage
  model_stage0?: string
  model_stage1?: string
  model_stage2?: string
  model_stage3?: string
  model_stage4?: string
  model_stage5?: string
  model_retranslate?: string
  thinking_stage0?: boolean | null
  thinking_stage1?: boolean | null
  thinking_stage2?: boolean | null
  thinking_stage3?: boolean | null
  thinking_stage4?: boolean | null
  thinking_stage5?: boolean | null
  thinking_retranslate?: boolean | null
  // v3.6: số dòng context cho retranslate
  retranslate_context_window?: number
  // Legacy compat
  model_pass1?: string
  model_pass3?: string
  model_retranslate_legacy?: string
}

const DEFAULT_CONFIG: TranslateConfig = {
  api_keys: { gemini: '', openai: '', deepseek: '' },
  provider: 'gemini',
  model_heavy: 'gemini-2.5-pro',
  model_medium: 'gemini-2.5-flash',
  model_light: 'gemini-2.5-flash',
  concurrency: 5,
  variant_mode: 'important_only',
  chunk_overlap: 30,
  cache_enabled: true,
  heavy_thinking: null,
  medium_thinking: null,
  light_thinking: null,
  translate_thinking: null,
}

export function loadConfig(): TranslateConfig {
  try {
    let raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      raw = localStorage.getItem(LEGACY_KEY)
    }
    if (raw) {
      const parsed = JSON.parse(raw)
      return { ...DEFAULT_CONFIG, ...parsed }
    }
  } catch {}
  return DEFAULT_CONFIG
}

export function saveConfig(c: Partial<TranslateConfig>) {
  try {
    const cur = loadConfig()
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...cur, ...c }))
  } catch {}
}

/**
 * Trả về API key cho provider hiện tại của config.
 *
 * v3.5 ConfigPanel ghi format mới: api_keys object theo provider.
 * Data cũ có thể vẫn ở format string đơn (api_key).
 * Hàm này đọc CẢ 2 format → tránh báo "thiếu API key" sai sau migration.
 */
export function getApiKey(config: TranslateConfig, _model?: string): string {
  // Format mới (v3 ConfigPanel)
  if (config.api_keys && config.provider) {
    const k = config.api_keys[config.provider]
    if (k) return k
  }
  // Format cũ (legacy)
  if (config.api_key) return config.api_key
  return ''
}

/**
 * v3.5: Trả model dùng cho retranslate (dịch lại 1 dòng trong editor).
 * Ưu tiên: model_retranslate (user chọn riêng) → model_heavy → default.
 */
export function getRetranslateModel(config: TranslateConfig): string {
  if (config.model_retranslate && config.model_retranslate.trim()) {
    return config.model_retranslate.trim()
  }
  if (config.model_heavy && config.model_heavy.trim()) {
    return config.model_heavy.trim()
  }
  return 'gemini-2.5-pro'
}

/**
 * v3.5: Trả thinking flag cho retranslate.
 */
export function getRetranslateThinking(config: TranslateConfig): boolean {
  if (config.thinking_retranslate !== null && config.thinking_retranslate !== undefined) {
    return !!config.thinking_retranslate
  }
  // Fallback: dùng translate_thinking nếu có, default false (nhanh)
  if (config.translate_thinking !== null && config.translate_thinking !== undefined) {
    return !!config.translate_thinking
  }
  return false
}

/**
 * v3.6: Trả số dòng context trước/sau cho retranslate.
 * Cap 1-5, default 2.
 */
export function getRetranslateContextWindow(config: TranslateConfig): number {
  const v = config.retranslate_context_window
  if (typeof v === 'number' && v >= 1 && v <= 5) return Math.floor(v)
  return 2
}
