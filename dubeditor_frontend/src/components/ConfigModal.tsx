/**
 * ConfigModal — backward-compatibility shim.
 *
 * Bản v2 đã chuyển cấu hình sang ConfigPanel trong TranslatePage.
 * File này chỉ giữ lại helpers `loadConfig` + `getApiKey` cho các
 * component cũ (SubtitleList retranslate inline).
 *
 * Storage key thống nhất: 'translate_config_v2'
 */
const STORAGE_KEY = 'translate_config_v2'

export interface TranslateConfig {
  api_key: string
  provider: 'gemini' | 'openai' | 'deepseek'
  // v2 fields
  model_heavy: string
  model_medium: string
  model_light: string
  concurrency: number
  // Legacy compat (vẫn đọc được từ object):
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
}

export function loadConfig(): TranslateConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
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
 * Trả về API key. v2 không phân biệt key theo model — luôn dùng cùng key.
 * Argument `model` giữ chỉ vì backward-compat với SubtitleList cũ.
 */
export function getApiKey(config: TranslateConfig, _model?: string): string {
  return config.api_key || ''
}
