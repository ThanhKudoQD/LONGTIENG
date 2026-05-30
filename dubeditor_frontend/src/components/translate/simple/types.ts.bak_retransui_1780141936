// ─── Simple Translator Types ─────────────────────────────────────────────────
// Types riêng cho pipeline dịch đơn giản (4 bước):
//   I.  Bible           (single or multi-part + merge)
//   II. Translate batch (100 dòng/batch, ACTIVE_BIBLE subset)
//   III.Filter errors   (8 code checks, no AI)
//   IV. Review/Repair   (AI sửa lỗi theo group)
//   +  Issues           (lịch sử lỗi & cách fix)

export type SimpleTab = 'flow' | 'bible' | 'bible-view' | 'translate' | 'subtitles' | 'review'

export type RunStatus = 'idle' | 'running' | 'done' | 'error'

// ─── CONFIG ──────────────────────────────────────────────────────────────────
// Cấu hình pipeline đơn giản — gọn hơn ConfigPanel cũ vì chỉ có 4 task AI.

export type Provider = 'gemini' | 'openai' | 'deepseek'

export interface ProviderApiKeys {
  gemini: string
  openai: string
  deepseek: string
}

// 4 task AI có thể chọn model riêng:
//   bible:     Trích Bible (heavy task)
//   translate: Dịch batch (heavy task — main)
//   repair:    Review/Repair (medium task)
//   qa:        Review/QA (medium task)
export type TaskKey = 'bible' | 'translate' | 'qa'

export interface SimpleConfig {
  // API keys cho 3 providers, lưu local
  api_keys: ProviderApiKeys

  // 4 task — mỗi task chọn model + thinking độc lập
  tasks: Record<TaskKey, {
    provider: Provider
    model: string
    thinking: boolean        // có dùng reasoning/thinking không
  }>

  // Batch config (Bước 2)
  batch_size_target: number          // default 100
  batch_size_max: number             // default 120
  gap_threshold_seconds: number      // default 3
  previous_context_lines: number     // default 15
  concurrency_mode: ConcurrencyMode  // normal / turbo
  turbo_concurrency: number          // default 5

  // Filter config (Bước 3)
  cps_max: number                    // default 22
  cps_max_chars_fallback: number     // default 50 — nếu không tính được CPS
  unknown_ratio_warn_percent: number // default 15

  // Review config (Bước 4)
  group_max_distance_lines: number   // default 50 — gom lỗi vào cụm ≤50 dòng
  group_max_errors: number           // default 30 — tối đa errors/group
  prompt_max_groups: number          // default 3 — tối đa groups/prompt
  max_retries: number                // default 2

  // Context adaptive cho repair (theo error type)
  context_speaker_errors: number     // default 8
  context_chinese_leak: number       // default 3
  context_cps_exceeded: number       // default 3
  context_empty: number              // default 5
  context_default: number            // default 5
  review_batch_size: number          // default 80 — AI review batch
  review_context_lines: number       // default 8
}

// ─── BIBLE ───────────────────────────────────────────────────────────────────

export type BibleMode = 'single' | 'multi'

export interface BiblePart {
  index: number                // 0-based
  total: number                // tổng số parts
  start_line: number
  end_line: number
  est_tokens: number
  prompt: string               // prompt build sẵn, copy được
  response: string | null      // response (auto fill hoặc user paste)
  status: RunStatus
  saved_at: string | null
  characters_count?: number    // hiển thị "32 nhân vật"
  error_msg?: string
}

export interface BibleMerge {
  prompt: string
  response: string | null
  status: RunStatus
  saved_at: string | null
  error_msg?: string
}

export interface BibleState {
  mode: BibleMode
  parts: BiblePart[]           // mode=single thì array có 1 phần tử
  merge: BibleMerge | null     // mode=single thì null
  master_bible_json: any | null     // Bible JSON cuối cùng (sau merge hoặc single)
  master_characters_count: number   // dùng cho badge tab
  master_glossary_count: number
}

// ─── TRANSLATE BATCH ─────────────────────────────────────────────────────────

export type ConcurrencyMode = 'normal' | 'turbo'

export interface BatchInfo {
  index: number                // 0-based
  total: number
  start_line: number
  end_line: number
  line_count: number
  characters_in_batch: number  // số nhân vật xuất hiện trong batch
  est_tokens_cached: number    // cached prefix
  est_tokens_variable: number  // variable layer
  prompt: string               // prompt build sẵn
  response: string | null
  status: RunStatus
  saved_at: string | null
  error_msg?: string
  unknown_ratio?: number       // % dòng có speaker UNKNOWN
}

export interface TranslateState {
  config: {
    batch_size_target: number   // default 100
    batch_size_max: number      // default 120
    gap_threshold_seconds: number   // default 3
    concurrency_mode: ConcurrencyMode
    turbo_concurrency: number   // default 5
    previous_context_lines: number  // default 15
  }
  batches: BatchInfo[]
  active_batch_index: number   // batch đang xem
  total_translated: number
  total_pending: number
  cost_so_far_usd: number
}

// ─── FILTER ERRORS (Bước 3) ──────────────────────────────────────────────────

export type ErrorType =
  | 'json_parse'
  | 'missing_id'
  | 'extra_id'
  | 'invalid_speaker'
  | 'chinese_remained'
  | 'cps_exceeded'
  | 'empty'
  | 'unnatural_pronoun'

export type ErrorSeverity = 'critical' | 'error' | 'warning'

export interface SubtitleError {
  id: number                   // = subtitle.id
  subtitle_index: number
  batch_index: number
  error_types: ErrorType[]
  severity: ErrorSeverity
  zh: string                   // text_zh
  current_speaker: string | null
  current_vi: string | null
  cps_value?: number
  auto_fixable: boolean
  needs_ai: boolean
  detected_at: string
}

export interface FilterStats {
  json_parse: number
  missing_id: number
  extra_id: number
  invalid_speaker: number
  chinese_remained: number
  cps_exceeded: number
  empty: number
  unknown_ratio_percent: number
  total_errors: number
  auto_fixed: number
  last_scan_at: string | null
}

// ─── REVIEW (Bước 4) ─────────────────────────────────────────────────────────

export type ReviewSubMode = 'repair' | 'qa'

export interface ContextLine {
  id: number
  speaker: string
  vi: string
}

export interface ReviewGroup {
  id: number
  group_index: number
  range_start: number
  range_end: number
  prompt: string
  response: string | null
  status: RunStatus
  error_msg: string | null
  est_tokens: number
}

export interface ReviewState {
  config: { review_batch_size: number; review_context_lines: number }
  groups: ReviewGroup[]
  suggestions: any[]
  pending_count: number
  applied_count: number
}

// ─── ISSUES (Tab V — lịch sử) ────────────────────────────────────────────────

export type IssueStatus = 'pending' | 'fixed' | 'still_broken' | 'manual_resolved'

export interface SubtitleIssue {
  id: number
  subtitle_id: number
  subtitle_index: number
  error_types: ErrorType[]
  severity: ErrorSeverity
  zh: string
  text_before: string | null
  speaker_before: string | null
  text_after: string | null
  speaker_after: string | null
  attempts: {
    attempt: number
    text: string
    speaker: string
    cps_value?: number
    passed: boolean
    timestamp: string
  }[]
  fix_attempt: number          // số lần thử
  status: IssueStatus
  needs_human_review: boolean
  batch_index: number
  detected_at: string
  resolved_at?: string | null
}

export interface IssuesStats {
  total: number
  pending: number
  fixed: number
  still_broken: number
  manual_resolved: number
  total_cost_usd: number
}

// ─── Model catalog ───────────────────────────────────────────────────────────
// Dùng trong ConfigPanel để render dropdown chọn model

export interface ModelOption {
  id: string
  label: string
  price_in_per_1m_usd: number   // input token price per 1M
  price_out_per_1m_usd: number  // output token price per 1M
  context_window: number        // tokens
  desc: string
  tier: 'top' | 'balanced' | 'fast'
}
