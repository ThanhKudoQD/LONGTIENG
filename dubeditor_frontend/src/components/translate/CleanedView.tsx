/**
 * CleanedView — Tab "Chuẩn hóa" (Stage 0 dashboard)
 *
 * Workflow 3 bước:
 *  1. Quét heuristic (code, không AI) → preview dòng nghi ngờ
 *  2. Gửi AI phân tích → AI quyết định remove/clean/keep
 *  3. Xem kết quả + hoàn tác từng dòng
 */
import React, { useEffect, useState } from 'react'
import { translateApi } from '../../api'
import type { CleanedSubtitle, ScanResult, TranslateConfig } from '../../types'

const CONFIG_STORAGE_KEY = 'translate_config_v3'

type ResultFilter = 'all' | 'clean' | 'remove'

function formatTime(sec: number): string {
  const m = Math.floor(sec / 60)
  const s = Math.floor(sec % 60)
  const ms = Math.floor((sec - Math.floor(sec)) * 10)
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}.${ms}`
}

function loadStoredConfig(): Partial<TranslateConfig> | null {
  try {
    const raw = localStorage.getItem(CONFIG_STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {}
  return null
}

export default function CleanedView({ projectId }: { projectId: number }) {
  const [scan, setScan] = useState<ScanResult | null>(null)
  const [cleaned, setCleaned] = useState<CleanedSubtitle[]>([])
  const [loading, setLoading] = useState(true)
  const [scanning, setScanning] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [filter, setFilter] = useState<ResultFilter>('all')
  const [showSuspicious, setShowSuspicious] = useState(false)
  const [reverting, setReverting] = useState<Set<number>>(new Set())

  async function refresh() {
    setLoading(true)
    try {
      const [scanRes, cleanedRes] = await Promise.all([
        translateApi.scanSuspicious(projectId).catch(() => null),
        translateApi.listCleaned(projectId),
      ])
      setScan(scanRes)
      setCleaned(cleanedRes)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [projectId])

  async function handleScan() {
    setScanning(true)
    try {
      const res = await translateApi.scanSuspicious(projectId)
      setScan(res)
      setShowSuspicious(true)
    } catch (e: any) {
      alert('Quét lỗi: ' + (e?.response?.data?.detail || e?.message || 'unknown'))
    } finally {
      setScanning(false)
    }
  }

  async function handleAnalyzeAI() {
    const stored = loadStoredConfig() as any
    // Provider lưu trong storage (mặc định gemini)
    let provider = (stored?.provider || 'gemini') as 'gemini' | 'openai' | 'deepseek'
    // Tìm key theo provider hiện tại
    let apiKey = stored?.api_keys?.[provider] || ''
    // Fallback 1: format cũ (api_key string đơn)
    if (!apiKey) apiKey = stored?.api_key || ''
    // Fallback 2: nếu provider hiện tại không có key, dùng provider khác có key
    if (!apiKey && stored?.api_keys) {
      for (const p of ['gemini', 'openai', 'deepseek'] as const) {
        if (stored.api_keys[p]) {
          provider = p
          apiKey = stored.api_keys[p]
          break
        }
      }
    }

    if (!apiKey) {
      alert(
        `Chưa có API key.\n\n` +
        `Mở "Cấu hình" → chọn provider → paste key → bấm "💾 Lưu cấu hình".`
      )
      return
    }

    if (!confirm(`Gửi ${scan?.suspicious_count || 0} dòng nghi ngờ + context lên AI (1 call)?\n\nProvider: ${provider}\nƯớc tính chi phí Flash: ~$0.005`)) {
      return
    }

    setAnalyzing(true)
    try {
      const config: TranslateConfig = {
        api_key: apiKey,
        provider,
        model_heavy: stored?.model_heavy || 'gemini-2.5-pro',
        model_medium: stored?.model_medium || 'gemini-2.5-flash',
        model_light: stored?.model_light || 'gemini-2.5-flash',
        // v3.3: thinking toggles (null = giữ default backend)
        heavy_thinking: stored?.heavy_thinking ?? null,
        medium_thinking: stored?.medium_thinking ?? null,
        light_thinking: stored?.light_thinking ?? null,
        translate_thinking: stored?.translate_thinking ?? null,
        project_type: stored?.project_type || 'short_drama',
        cps_max: stored?.cps_max ?? null,
        concurrency: stored?.concurrency || 5,
        source_lang: 'zh',
        variant_mode: stored?.variant_mode || 'important_only',
        chunk_overlap: stored?.chunk_overlap ?? 30,
        cache_enabled: stored?.cache_enabled ?? true,
        chunks_parallel: stored?.chunks_parallel ?? false,
        speaker_parallel: stored?.speaker_parallel ?? true,
        speaker_context_window: stored?.speaker_context_window ?? 20,
        stage0_enabled: true,
        stage0_model: stored?.stage0_model || null,
        stage0_context_window: stored?.stage0_context_window ?? 2,
      }

      // Gọi sync — đợi xong, trả kết quả ngay
      const result = await translateApi.runNormalize(projectId, config)
      // Refresh danh sách cleaned trong tab này
      await refresh()
      // Báo cho parent (TranslatePage) + SubtitlesView refresh
      window.dispatchEvent(new CustomEvent('stage0-done', {
        detail: { projectId },
      }))
      // Báo kết quả
      alert(
        `✓ Phân tích xong\n\n` +
        `Tổng: ${result.total_lines} dòng\n` +
        `Nghi ngờ: ${result.suspicious_count}\n` +
        `Đã gửi AI: ${result.cluster_count} dòng (1 call)\n\n` +
        `🗑 Loại bỏ: ${result.removed_count} (đã xóa khỏi DB + reindex)\n` +
        `🔧 Sửa: ${result.cleaned_count} (đã ghi đè text gốc)\n` +
        `✓ Giữ: ${result.kept_count}\n\n` +
        `Chi phí: $${result.cost_usd.toFixed(4)}`
      )
    } catch (e: any) {
      alert('Phân tích lỗi: ' + (e?.response?.data?.detail || e?.message || 'unknown'))
    } finally {
      setAnalyzing(false)
    }
  }

  async function handleRevert(sub: CleanedSubtitle) {
    if (!confirm(`Hoàn tác dòng #${sub.index}?\n\nTrước: ${sub.original_raw}\nSau: ${sub.current_text || '(đã xóa)'}`)) {
      return
    }
    setReverting(prev => new Set(prev).add(sub.id))
    try {
      await translateApi.revertCleaned(projectId, sub.id)
      await refresh()
    } catch (e: any) {
      alert('Lỗi: ' + (e?.response?.data?.detail || e?.message || 'unknown'))
    } finally {
      setReverting(prev => {
        const next = new Set(prev)
        next.delete(sub.id)
        return next
      })
    }
  }

  const filteredCleaned = cleaned.filter(r => filter === 'all' ? true : r.action === filter)
  const cleanCount = cleaned.filter(r => r.action === 'clean').length
  const removeCount = cleaned.filter(r => r.action === 'remove').length

  if (loading) {
    return <div className="p-6 text-sm text-zinc-500">Đang tải...</div>
  }

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-4">
      {/* ─── BƯỚC 1: Quét ─── */}
      <StepCard step="1" title="Quét tự động (heuristic, không tốn API)"
                desc="Tìm dòng nghi ngờ: watermark, ký tự rác, filler, decoration, watermark studio...">
        <div className="flex items-center gap-3">
          <button
            onClick={handleScan}
            disabled={scanning}
            className="px-4 py-2 rounded-lg bg-zinc-900 dark:bg-zinc-100 text-white dark:text-zinc-900 text-[13px] font-medium hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-50"
          >
            {scanning ? 'Đang quét...' : (scan ? '🔄 Quét lại' : '🔍 Quét')}
          </button>

          {scan && (
            <div className="flex items-center gap-4 text-[12px]">
              <Stat label="Tổng" value={scan.total_lines} />
              <Stat label="Nghi ngờ" value={scan.suspicious_count}
                    accent={scan.suspicious_count > 0 ? 'amber' : 'gray'} />
              <Stat label="Sẽ gửi AI" value={scan.cluster_count} />
              {scan.total_lines > 0 && (
                <span className="text-zinc-400">
                  ({((scan.suspicious_count / scan.total_lines) * 100).toFixed(1)}%)
                </span>
              )}
            </div>
          )}
        </div>

        {scan && scan.suspicious_count > 0 && (
          <div className="mt-3">
            <button
              onClick={() => setShowSuspicious(!showSuspicious)}
              className="text-[12px] text-blue-600 dark:text-blue-400 hover:underline"
            >
              {showSuspicious ? '▲ Ẩn' : `▼ Xem ${scan.suspicious_count} dòng nghi ngờ`}
            </button>

            {showSuspicious && (
              <div className="mt-2 max-h-80 overflow-y-auto rounded-lg border border-zinc-200 dark:border-zinc-800 divide-y divide-zinc-100 dark:divide-zinc-900">
                {scan.suspicious_lines.map(s => (
                  <div key={s.index} className="flex items-start gap-3 p-2 text-[12px] hover:bg-zinc-50 dark:hover:bg-zinc-900/50">
                    <span className="font-mono text-zinc-400 w-12 flex-shrink-0">#{s.index}</span>
                    <span className="flex-1 min-w-0 font-medium text-zinc-700 dark:text-zinc-200 break-all">
                      {s.text || <span className="italic text-zinc-400">(rỗng)</span>}
                    </span>
                    <div className="flex-shrink-0 flex flex-wrap gap-1 justify-end max-w-[40%]">
                      {s.reasons.map((r, i) => (
                        <ReasonBadge key={i} reason={r} />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </StepCard>

      {/* ─── BƯỚC 2: AI ─── */}
      <StepCard
        step="2"
        title="Gửi AI phân tích"
        desc="AI đọc context xung quanh để quyết định: SỬA / LOẠI BỎ / GIỮ NGUYÊN. Tốn API."
        disabled={!scan || scan.suspicious_count === 0}
      >
        <div className="flex items-center gap-3">
          <button
            onClick={handleAnalyzeAI}
            disabled={analyzing || !scan || scan.suspicious_count === 0}
            className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-700 text-white text-[13px] font-medium disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {analyzing ? 'Đang phân tích...' : '🤖 Phân tích bằng AI'}
          </button>

          {scan && scan.suspicious_count > 0 && (
            <span className="text-[12px] text-zinc-500">
              1 call · gửi {scan.cluster_count} dòng (suspicious + ±N context) · ước tính ~${(scan.cluster_count * 0.0001).toFixed(4)} (Flash)
            </span>
          )}
        </div>

        {(!scan || scan.suspicious_count === 0) && (
          <div className="mt-2 text-[11px] text-zinc-400 italic">
            Chạy Bước 1 trước để có dòng nghi ngờ.
          </div>
        )}
      </StepCard>

      {/* ─── BƯỚC 3: Kết quả ─── */}
      <StepCard
        step="3"
        title="Kết quả AI"
        desc={cleaned.length > 0 ? `AI đã xử lý ${cleaned.length} dòng.` : 'Chưa có kết quả — chạy Bước 2 để bắt đầu.'}
      >
        {cleaned.length === 0 ? (
          <div className="text-[12px] text-zinc-400 italic">
            Sau khi Bước 2 chạy xong, danh sách dòng AI đã sửa / loại bỏ sẽ hiển thị ở đây.
          </div>
        ) : (
          <>
            <div className="flex items-center gap-1 text-[12px] mb-3">
              <FilterButton active={filter === 'all'} onClick={() => setFilter('all')}>
                Tất cả ({cleaned.length})
              </FilterButton>
              <FilterButton active={filter === 'clean'} onClick={() => setFilter('clean')}>
                🔧 Sửa ({cleanCount})
              </FilterButton>
              <FilterButton active={filter === 'remove'} onClick={() => setFilter('remove')}>
                🗑 Loại bỏ ({removeCount})
              </FilterButton>
            </div>

            <div className="space-y-2 max-h-[700px] overflow-y-auto pr-1">
              {filteredCleaned.map(sub => (
                <CleanedRow
                  key={sub.id}
                  sub={sub}
                  reverting={reverting.has(sub.id)}
                  onRevert={() => handleRevert(sub)}
                />
              ))}
            </div>
          </>
        )}
      </StepCard>
    </div>
  )
}

// ─── Sub components ──────────────────────────────────────────────────────

function StepCard({
  step, title, desc, disabled = false, children,
}: {
  step: string
  title: string
  desc: string
  disabled?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={`rounded-xl border bg-white dark:bg-zinc-950 ${
      disabled ? 'opacity-50 border-zinc-200 dark:border-zinc-800' : 'border-zinc-200 dark:border-zinc-800'
    }`}>
      <div className="p-4">
        <div className="flex items-start gap-3 mb-3">
          <div className="w-7 h-7 flex-shrink-0 rounded-full bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-200 text-[13px] font-semibold flex items-center justify-center">
            {step}
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-[14px] font-semibold text-zinc-800 dark:text-zinc-100">
              {title}
            </h3>
            <p className="text-[11px] text-zinc-500 mt-0.5 leading-relaxed">
              {desc}
            </p>
          </div>
        </div>
        <div className="pl-10">
          {children}
        </div>
      </div>
    </div>
  )
}

function Stat({
  label, value, accent = 'gray',
}: {
  label: string
  value: number
  accent?: 'gray' | 'amber' | 'emerald'
}) {
  const colors = {
    gray: 'text-zinc-700 dark:text-zinc-200',
    amber: 'text-amber-700 dark:text-amber-300',
    emerald: 'text-emerald-700 dark:text-emerald-300',
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="text-zinc-400">{label}:</span>
      <span className={`font-semibold ${colors[accent]}`}>{value}</span>
    </span>
  )
}

const REASON_LABEL: Record<string, string> = {
  empty: 'rỗng',
  too_long: 'quá dài',
  whitespace_gap: 'space lạ',
  decoration_chars: 'ký tự deco',
  long_dashes: 'dashes',
  punct_only: 'chỉ dấu câu',
  episode_marker: 'số tập',
  url_or_mention: 'URL/mention',
  duplicate_prev: 'trùng dòng trước',
  isolated_char: 'ký tự lẻ',
}

function ReasonBadge({ reason }: { reason: string }) {
  // Handle dynamic patterns
  let label = REASON_LABEL[reason] || reason
  if (reason.startsWith('watermark:')) label = 'watermark'
  else if (reason.startsWith('repeat_char:')) label = 'lặp ký tự'

  return (
    <span className="px-1.5 py-0.5 rounded text-[10px] bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300 whitespace-nowrap">
      {label}
    </span>
  )
}

function FilterButton({
  active, onClick, children,
}: {
  active: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 rounded-md font-medium transition-colors ${
        active
          ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900'
          : 'text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800'
      }`}
    >
      {children}
    </button>
  )
}

function CleanedRow({
  sub, reverting, onRevert,
}: {
  sub: CleanedSubtitle
  reverting: boolean
  onRevert: () => void
}) {
  const isRemove = sub.action === 'remove'
  return (
    <div className={`rounded-lg border p-3 ${
      isRemove
        ? 'border-rose-200 bg-rose-50/40 dark:border-rose-900/40 dark:bg-rose-950/20'
        : 'border-blue-200 bg-blue-50/40 dark:border-blue-900/40 dark:bg-blue-950/20'
    }`}>
      <div className="flex items-start gap-3">
        <div className="flex-shrink-0 flex flex-col items-center gap-1 pt-0.5">
          <div className="text-[11px] text-zinc-400 font-mono">#{sub.index}</div>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${
            isRemove
              ? 'bg-rose-200 text-rose-800 dark:bg-rose-800/40 dark:text-rose-200'
              : 'bg-blue-200 text-blue-800 dark:bg-blue-800/40 dark:text-blue-200'
          }`}>
            {isRemove ? '🗑 BỎ' : '🔧 SỬA'}
          </span>
        </div>

        <div className="flex-1 min-w-0 space-y-1.5">
          <div className="text-[10px] text-zinc-400 font-mono">
            {formatTime(sub.start_time)} → {formatTime(sub.end_time)}
          </div>

          {sub.original_raw && (
            <div className="text-[13px]">
              <span className="text-[10px] text-zinc-400 mr-2 uppercase tracking-wider">trước</span>
              <span className="text-zinc-500 line-through decoration-1">
                {sub.original_raw}
              </span>
            </div>
          )}
          <div className="text-[14px]">
            <span className="text-[10px] text-zinc-400 mr-2 uppercase tracking-wider">sau</span>
            {isRemove ? (
              <span className="italic text-rose-600 dark:text-rose-400">(đã loại bỏ — không gửi cho AI dịch)</span>
            ) : (
              <span className="font-medium text-zinc-800 dark:text-zinc-100">
                {sub.current_text}
              </span>
            )}
          </div>

          {sub.clean_reason && (
            <div className="text-[11px] text-zinc-500 italic flex items-start gap-1.5 pt-1">
              <span className="text-zinc-400">💬</span>
              <span>{sub.clean_reason}</span>
            </div>
          )}
        </div>

        <button
          onClick={onRevert}
          disabled={reverting}
          className="flex-shrink-0 text-[11px] px-2.5 py-1 rounded border border-zinc-300 dark:border-zinc-700 hover:bg-white dark:hover:bg-zinc-800 text-zinc-600 dark:text-zinc-400 disabled:opacity-50"
        >
          {reverting ? '...' : '↶ Hoàn tác'}
        </button>
      </div>
    </div>
  )
}