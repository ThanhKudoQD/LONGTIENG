/**
 * simpleApi.ts — API client cho pipeline Simple v4.
 *
 * Tất cả endpoint dưới prefix /api/projects/{pid}/simple/
 *
 * Long-running tasks (Auto, Run-all, Run-from) trả 202 ngay,
 * tiến độ thật được push qua WebSocket /ws/{pid} với event kind='simple'.
 * Xem `useSimpleWebSocket.ts` để nhận events.
 */
import axios from 'axios'
import type {
  BibleState, BibleMode, TranslateState, ConcurrencyMode,
  FilterStats, SubtitleError, ReviewState, ReviewSubMode,
  SubtitleIssue, IssuesStats, SimpleConfig,
} from './types'

const api = axios.create({
  baseURL: '/dub/api',
  timeout: 360_000,   // 6 phút — đủ cho sync endpoint chậm + LLM trả về.
                       // Long-running tasks vẫn dùng WS/polling, nhưng 1 số endpoint
                       // (rebuild, scan, sync) có thể chạy lâu với SRT lớn.
})

// ─── Response shape ──────────────────────────────────────────────────────────

export interface FilterScanResult {
  stats: FilterStats
  errors: SubtitleError[]
  auto_fixed_count: number
}

export interface IssuesListResult {
  stats: IssuesStats
  issues: SubtitleIssue[]
}

export interface OkResult {
  ok: boolean
  message?: string
  task_id?: string
}

// ─── Bible (Bước I) ──────────────────────────────────────────────────────────

export const bibleApi = {
  getState: (pid: number) =>
    api.get<BibleState>(`/projects/${pid}/simple/bible`).then(r => r.data),

  changeMode: (pid: number, mode: BibleMode, multi_parts_count?: number) =>
    api.post<BibleState>(`/projects/${pid}/simple/bible/mode`, {
      mode, multi_parts_count,
    }).then(r => r.data),

  savePart: (pid: number, idx: number, response: string) =>
    api.post<BibleState>(`/projects/${pid}/simple/bible/${idx}/save`, {
      response,
    }).then(r => r.data),

  autoPart: (pid: number, idx: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/bible/${idx}/auto`).then(r => r.data),

  saveMerge: (pid: number, response: string) =>
    api.post<BibleState>(`/projects/${pid}/simple/bible/merge/save`, {
      response,
    }).then(r => r.data),

  autoMerge: (pid: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/bible/merge/auto`).then(r => r.data),

  runAll: (pid: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/bible/run-all`).then(r => r.data),

  reset: (pid: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/bible/reset`).then(r => r.data),
}

// ─── Batches (Bước II) ───────────────────────────────────────────────────────

export const batchesApi = {
  getState: (pid: number) =>
    api.get<TranslateState>(`/projects/${pid}/simple/batches`).then(r => r.data),

  updateConfig: (pid: number, body: Partial<TranslateState['config']> & { rebuild?: boolean }) =>
    api.post<TranslateState>(`/projects/${pid}/simple/batches/config`, body).then(r => r.data),

  rebuild: (pid: number) =>
    api.post<TranslateState>(`/projects/${pid}/simple/batches/rebuild`).then(r => r.data),

  saveBatch: (pid: number, idx: number, response: string) =>
    api.post<TranslateState>(`/projects/${pid}/simple/batches/${idx}/save`, {
      response,
    }).then(r => r.data),

  resetBatch: (pid: number, idx: number) =>
    api.post<TranslateState>(`/projects/${pid}/simple/batches/${idx}/reset`).then(r => r.data),

  autoBatch: (pid: number, idx: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/batches/${idx}/auto`).then(r => r.data),

  runFrom: (pid: number, idx: number, only_idle = true) =>
    api.post<OkResult>(`/projects/${pid}/simple/batches/run-from/${idx}`, {
      only_idle,
    }).then(r => r.data),

  /** Sync simple_text_vi → text (legacy) cho Editor cũ đọc được. Backfill 1 lần. */
  syncToEditor: (pid: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/batches/sync-to-editor`).then(r => r.data),
}

// ─── Filter (Bước III) ───────────────────────────────────────────────────────

export const filterApi = {
  getStats: (pid: number) =>
    api.get<FilterScanResult>(`/projects/${pid}/simple/filter/stats`).then(r => r.data),

  scan: (pid: number) =>
    api.post<FilterScanResult>(`/projects/${pid}/simple/filter/scan`).then(r => r.data),

  autoFix: (pid: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/filter/auto-fix`).then(r => r.data),

  pushReview: (pid: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/filter/push-review`).then(r => r.data),
}

// ─── Review (Bước IV) ────────────────────────────────────────────────────────

export const reviewApi = {
  getState: (pid: number) =>
    api.get<ReviewState>(`/projects/${pid}/simple/review`).then(r => r.data),

  changeSubMode: (pid: number, sub_mode: ReviewSubMode) =>
    api.post<ReviewState>(`/projects/${pid}/simple/review/sub-mode`, { sub_mode })
       .then(r => r.data),

  rebuild: (pid: number) =>
    api.post<ReviewState>(`/projects/${pid}/simple/review/rebuild`).then(r => r.data),

  saveGroup: (pid: number, idx: number, response: string) =>
    api.post<ReviewState>(`/projects/${pid}/simple/review/${idx}/save`, {
      response,
    }).then(r => r.data),

  autoGroup: (pid: number, idx: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/review/${idx}/auto`).then(r => r.data),

  runAll: (pid: number) =>
    api.post<OkResult>(`/projects/${pid}/simple/review/run-all`).then(r => r.data),
}

// ─── Issues (Tab V) ──────────────────────────────────────────────────────────

export const issuesApi = {
  list: (pid: number, params?: { status?: string; error_type?: string; attempt?: number }) =>
    api.get<IssuesListResult>(`/projects/${pid}/simple/issues`, { params })
       .then(r => r.data),

  refix: (pid: number, issueId: number) =>
    api.post<IssuesListResult>(`/projects/${pid}/simple/issues/${issueId}/refix`)
       .then(r => r.data),

  manualEdit: (pid: number, issueId: number, text: string, speaker?: string) =>
    api.post<IssuesListResult>(`/projects/${pid}/simple/issues/${issueId}/manual-edit`, {
      text, speaker,
    }).then(r => r.data),

  resolve: (pid: number, issueId: number) =>
    api.post<IssuesListResult>(`/projects/${pid}/simple/issues/${issueId}/resolve`)
       .then(r => r.data),

  exportCsvUrl: (pid: number): string =>
    `/dub/api/projects/${pid}/simple/issues/export.csv`,
}

// ─── Config (per-project, DB-backed) ─────────────────────────────────────────

export const configApi = {
  get: (pid: number) =>
    api.get<SimpleConfig>(`/projects/${pid}/simple/config`).then(r => r.data),

  save: (pid: number, config: SimpleConfig) =>
    api.post<OkResult>(`/projects/${pid}/simple/config`, config).then(r => r.data),
}

export default api
