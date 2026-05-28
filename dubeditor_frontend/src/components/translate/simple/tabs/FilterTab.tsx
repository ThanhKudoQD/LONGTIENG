import React, { useState } from 'react'
import type { FilterStats, SubtitleError, ErrorType, ErrorSeverity } from '../types'
import { SectionHead } from '../shared/SharedUI'

interface Props {
  stats: FilterStats
  errors: SubtitleError[]
  onScan: () => void
  onAutoFixAll: () => void
  onPushToReview: () => void
}

const ERROR_TYPE_LABELS: Record<ErrorType, string> = {
  json_parse: 'JSON parse',
  missing_id: 'Thiếu id',
  extra_id: 'Id thừa',
  invalid_speaker: 'Speaker sai',
  chinese_remained: 'Còn chữ Trung',
  cps_exceeded: 'CPS vượt',
  empty: 'Dòng rỗng',
  unnatural_pronoun: 'Xưng hô sai',
}

const ERROR_TYPE_TONES: Record<ErrorType, 'err' | 'warn'> = {
  json_parse: 'err',
  missing_id: 'warn',
  extra_id: 'warn',
  invalid_speaker: 'err',
  chinese_remained: 'err',
  cps_exceeded: 'warn',
  empty: 'err',
  unnatural_pronoun: 'err',
}

export default function FilterTab(props: Props) {
  const { stats, errors } = props
  const [filterType, setFilterType] = useState<'all' | ErrorType>('all')
  const [filterSeverity, setFilterSeverity] = useState<'all' | ErrorSeverity>('all')
  const [filterBatch, setFilterBatch] = useState<'all' | number>('all')

  const filteredErrors = errors.filter(e => {
    if (filterType !== 'all' && !e.error_types.includes(filterType)) return false
    if (filterSeverity !== 'all' && e.severity !== filterSeverity) return false
    if (filterBatch !== 'all' && e.batch_index !== filterBatch) return false
    return true
  })

  const batchOptions = Array.from(new Set(errors.map(e => e.batch_index))).sort((a, b) => a - b)

  const lastScanLabel = stats.last_scan_at
    ? formatRelativeTime(stats.last_scan_at)
    : 'Chưa quét'

  return (
    <div>
      <SectionHead
        title="Bước III · Lọc lỗi"
        subtitle="Code thuần, không gọi AI. Quét 8 loại lỗi sau khi mỗi batch dịch xong. Auto-fix lỗi format trước khi flag."
        meta={
          <>
            <div><span className="text-zinc-500">Lần quét gần nhất:</span> {lastScanLabel}</div>
            <div><span className="text-zinc-500">Lỗi tìm thấy:</span> {stats.total_errors} · Auto-fixed: {stats.auto_fixed}</div>
          </>
        }
      />

      {/* 8 stat cards */}
      <div className="grid grid-cols-4 lg:grid-cols-8 gap-2 mb-4">
        {[
          { label: 'JSON parse', value: stats.json_parse, tone: stats.json_parse > 0 ? 'err' : 'ok' },
          { label: 'Thiếu id', value: stats.missing_id, tone: stats.missing_id > 0 ? 'warn' : 'ok' },
          { label: 'Id thừa', value: stats.extra_id, tone: stats.extra_id > 0 ? 'warn' : 'ok' },
          { label: 'Speaker sai', value: stats.invalid_speaker, tone: stats.invalid_speaker > 0 ? 'err' : 'ok' },
          { label: 'Còn TQ', value: stats.chinese_remained, tone: stats.chinese_remained > 0 ? 'err' : 'ok' },
          { label: 'CPS vượt', value: stats.cps_exceeded, tone: stats.cps_exceeded > 0 ? 'warn' : 'ok' },
          { label: 'Dòng rỗng', value: stats.empty, tone: stats.empty > 0 ? 'warn' : 'ok' },
          { label: 'UNKNOWN', value: `${stats.unknown_ratio_percent.toFixed(1)}%`, tone: stats.unknown_ratio_percent > 15 ? 'warn' : 'ok' },
        ].map((s, i) => (
          <StatCard key={i} label={s.label} value={s.value} tone={s.tone as any} />
        ))}
      </div>

      {/* Action bar */}
      <div className="flex items-center gap-2 mb-5">
        <button onClick={props.onScan} className="btn-primary">
          ⚡ Quét lại toàn bộ
        </button>
        <button onClick={props.onAutoFixAll} className="btn">
          ↺ Auto-fix tất cả
        </button>
        <button onClick={props.onPushToReview} className="btn text-zinc-500">
          📤 Đẩy {stats.total_errors} lỗi sang Review →
        </button>
      </div>

      {/* Filter bar */}
      <div className="surface-card rounded-lg px-4 py-2.5 mb-4 flex items-center gap-4 flex-wrap">
        <FilterDropdown
          label="Loại"
          value={filterType}
          onChange={(v) => setFilterType(v as any)}
          options={[
            { value: 'all', label: `Tất cả (${errors.length})` },
            ...Object.entries(ERROR_TYPE_LABELS).map(([k, v]) => ({
              value: k,
              label: `${v} (${errors.filter(e => e.error_types.includes(k as ErrorType)).length})`,
            })).filter(o => !o.label.includes('(0)')),
          ]}
        />
        <FilterDropdown
          label="Severity"
          value={filterSeverity}
          onChange={(v) => setFilterSeverity(v as any)}
          options={[
            { value: 'all', label: 'Tất cả' },
            { value: 'critical', label: 'Critical' },
            { value: 'error', label: 'Error' },
            { value: 'warning', label: 'Warning' },
          ]}
        />
        <FilterDropdown
          label="Batch"
          value={String(filterBatch)}
          onChange={(v) => setFilterBatch(v === 'all' ? 'all' : Number(v))}
          options={[
            { value: 'all', label: 'Tất cả' },
            ...batchOptions.map(b => ({ value: String(b), label: `Batch ${b + 1}` })),
          ]}
        />
        <div className="flex-1" />
        <span className="text-[12px] text-zinc-600 dark:text-zinc-400">
          {filteredErrors.length} / {errors.length} hiển thị
        </span>
      </div>

      {/* Issue rows */}
      <div className="space-y-2">
        {filteredErrors.length === 0 ? (
          <div className="surface-card rounded-lg p-10 text-center text-zinc-500 dark:text-zinc-500">
            <div className="text-[15px] font-semibold text-zinc-700 dark:text-zinc-300 mb-2">Không có lỗi</div>
            <div className="text-[12.5px]">Bấm "Quét lại toàn bộ" để chạy code-based validation.</div>
          </div>
        ) : (
          filteredErrors.map(err => <ErrorRow key={err.id} err={err} />)
        )}
      </div>
    </div>
  )
}

// ─── StatCard ────────────────────────────────────────────────────────────────

function StatCard({
  label, value, tone,
}: {
  label: string
  value: React.ReactNode
  tone: 'ok' | 'warn' | 'err' | 'default'
}) {
  const toneClass = {
    ok: 'text-emerald-600 dark:text-emerald-400',
    warn: 'text-amber-600 dark:text-amber-400',
    err: 'text-red-600 dark:text-red-400',
    default: 'text-zinc-900 dark:text-zinc-100',
  }[tone]
  return (
    <div className="surface-card rounded-lg px-3 py-2.5">
      <div className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-500 mb-1">
        {label}
      </div>
      <div className={`text-[22px] font-bold leading-none ${toneClass}`}>
        {value}
      </div>
    </div>
  )
}

// ─── FilterDropdown ──────────────────────────────────────────────────────────

function FilterDropdown({
  label, value, onChange, options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string }[]
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-600 dark:text-zinc-400">
        {label}
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="input text-[12px] py-1 px-2"
      >
        {options.map(o => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  )
}

// ─── ErrorRow ────────────────────────────────────────────────────────────────

function ErrorRow({ err }: { err: SubtitleError }) {
  return (
    <div className="surface-card rounded-lg p-3.5 hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors">
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="font-mono text-[13px] font-bold text-blue-700 dark:text-blue-400">
          #{err.subtitle_index}
        </span>
        {err.error_types.map(type => (
          <span
            key={type}
            className={`font-mono text-[10.5px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded ${
              ERROR_TYPE_TONES[type] === 'err'
                ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300'
                : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
            }`}
          >
            {ERROR_TYPE_LABELS[type]}
          </span>
        ))}
        <div className="flex-1" />
        <span className="font-mono text-[11px] uppercase tracking-wider text-zinc-500 dark:text-zinc-500">
          Batch {err.batch_index + 1} · pending
        </span>
      </div>
      <div className="grid grid-cols-[90px_1fr] gap-y-1.5 gap-x-3 items-baseline text-[12.5px]">
        <span className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-500">ZH</span>
        <span className="font-mono text-zinc-800 dark:text-zinc-200">{err.zh}</span>

        <span className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-500">VI hiện tại</span>
        <span className="text-red-600 dark:text-red-400">
          {err.current_speaker && <span className="text-zinc-500 dark:text-zinc-400 mr-1 font-medium">{err.current_speaker} —</span>}
          {err.current_vi ? `"${err.current_vi}"` : '(rỗng)'}
        </span>

        {err.cps_value && (
          <>
            <span className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-500">CPS</span>
            <span className="text-amber-600 dark:text-amber-400 font-medium">{err.cps_value.toFixed(1)} (max 22)</span>
          </>
        )}
      </div>
    </div>
  )
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return 'vừa xong'
  if (minutes < 60) return `${minutes} phút trước`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} giờ trước`
  return `${Math.floor(hours / 24)} ngày trước`
}
