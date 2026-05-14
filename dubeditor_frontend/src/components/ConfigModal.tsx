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
  api_key: string
  provider: 'gemini' | 'openai' | 'deepseek'
  model_heavy: string
  model_medium: string
  model_light: string
  concurrency: number
  // v3 fields (optional)
  variant_mode?: 'off' | 'important_only' | 'always'
  chunk_overlap?: number
  cache_enabled?: boolean
  // Legacy compat
  model_pass1?: string
  model_pass3?: string
  model_retranslate?: string
}

const DEFAULT_CONFIG: TranslateConfig = {
  api_key: '',
  provider: 'gemini',
  model_heavy: 'gemini-2.5-pro',
  model_medium: 'gemini-2.5-flash',
  model_light: 'gemini-2.5-flash',
  concurrency: 5,
  variant_mode: 'important_only',
  chunk_overlap: 30,
  cache_enabled: true,
}

export function loadConfig(): TranslateConfig {
  try {
    // Ưu tiên v3
    let raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) {
      // Fallback v2
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
 * Trả về API key.
 */
export function getApiKey(config: TranslateConfig, _model?: string): string {
  return config.api_key || ''
}
