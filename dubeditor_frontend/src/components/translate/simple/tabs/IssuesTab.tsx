import React, { useState } from 'react'
import type { SubtitleIssue, IssuesStats, IssueStatus, ErrorType } from '../types'
import { SectionHead, InfoStrip } from '../shared/SharedUI'

interface Props {
  issues: SubtitleIssue[]
  stats: IssuesStats
  onRefix: (issueId: number) => void
  onManualEdit: (issueId: number) => void
  onMarkResolved: (issueId: number) => void
  onExportCsv: () => void
}

const STATUS_LABELS: Record<IssueStatus, string> = {
  pending: 'Pending',
  fixed: 'Fixed',
  still_broken: 'Still broken',
  manual_resolved: 'Manual resolved',
}

const STATUS_TONES: Record<IssueStatus, string> = {
  pending: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  fixed: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
  still_broken: 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  manual_resolved: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
}

export default function IssuesTab(props: Props) {
  const { issues, stats } = props
  const [filterStatus, setFilterStatus] = useState<'all' | IssueStatus>('all')
  const [filterType, setFilterType] = useState<'all' | ErrorType>('all')
  const [filterAttempt, setFilterAttempt] = useState<'all' | number>('all')

  const filtered = issues.filter(iss => {
    if (filterStatus !== 'all' && iss.status !== filterStatus) return false
    if (filterType !== 'all' && !iss.error_types.includes(filterType)) return false
    if (filterAttempt !== 'all' && iss.fix_attempt !== filterAttempt) return false
    return true
  })

  return (
    <div>
      <SectionHead
        title="Bước V · Vấn đề tồn đọng"
        subtitle="Lịch sử các dòng đã từng lỗi và cách AI đã sửa. Theo dõi dòng còn 'still_broken' cần xử lý tay."
        meta={
          <div><span className="text-zinc-500">Tổng:</span> {stats.total} · fixed: {stats.fixed} · still_broken: {stats.still_broken}</div>
        }
      />

      {/* Stats */}
      <InfoStrip
        stats={[
          { label: 'Tổng issues', value: stats.total },
          { label: 'Đã fix', value: stats.fixed, tone: 'ok' },
          { label: 'Còn lỗi', value: stats.still_broken, tone: stats.still_broken > 0 ? 'err' : 'default' },
          { label: 'User resolved', value: stats.manual_resolved || '—' },
          { label: 'Cost repair', value: `$${stats.total_cost_usd.toFixed(2)}`, tone: 'accent' },
        ]}
      />

      {/* Filter bar */}
      <div className="surface-card rounded-lg px-4 py-2.5 mb-4 flex items-center gap-4 flex-wrap">
        <FilterDropdown
          label="Status"
          value={filterStatus}
          onChange={(v) => setFilterStatus(v as any)}
          options={[
            { value: 'all', label: `Tất cả (${issues.length})` },
            { value: 'pending', label: `Pending (${stats.pending})` },
            { value: 'fixed', label: `Fixed (${stats.fixed})` },
            { value: 'still_broken', label: `Still broken (${stats.still_broken})` },
            { value: 'manual_resolved', label: `Manual resolved (${stats.manual_resolved})` },
          ]}
        />
        <FilterDropdown
          label="Loại lỗi"
          value={filterType}
          onChange={(v) => setFilterType(v as any)}
          options={[
            { value: 'all', label: 'Tất cả' },
            { value: 'invalid_speaker', label: 'Speaker invalid' },
            { value: 'chinese_remained', label: 'Chinese remained' },
            { value: 'cps_exceeded', label: 'CPS exceeded' },
            { value: 'empty', label: 'Empty' },
          ]}
        />
        <FilterDropdown
          label="Attempt"
          value={String(filterAttempt)}
          onChange={(v) => setFilterAttempt(v === 'all' ? 'all' : Number(v))}
          options={[
            { value: 'all', label: 'Tất cả' },
            { value: '1', label: '1 lần' },
            { value: '2', label: '2 lần' },
          ]}
        />
        <div className="flex-1" />
        <button onClick={props.onExportCsv} className="btn text-zinc-500">
          📥 Export CSV
        </button>
      </div>

      {/* Issue rows */}
      <div className="space-y-2">
        {filtered.length === 0 ? (
          <div className="surface-card rounded-lg p-10 text-center text-zinc-500">
            <div className="text-[15px] font-semibold text-zinc-700 dark:text-zinc-300 mb-2">Không có issue</div>
            <div className="text-[12.5px]">Pipeline chưa có lỗi nào, hoặc filter đang ẩn hết.</div>
          </div>
        ) : (
          filtered.map(iss => (
            <IssueRow
              key={iss.id}
              issue={iss}
              onRefix={() => props.onRefix(iss.id)}
              onManualEdit={() => props.onManualEdit(iss.id)}
              onMarkResolved={() => props.onMarkResolved(iss.id)}
            />
          ))
        )}
      </div>
    </div>
  )
}

// ─── IssueRow ────────────────────────────────────────────────────────────────

function IssueRow({
  issue,
  onRefix, onManualEdit, onMarkResolved,
}: {
  issue: SubtitleIssue
  onRefix: () => void
  onManualEdit: () => void
  onMarkResolved: () => void
}) {
  const isStillBroken = issue.status === 'still_broken'
  return (
    <div className={`surface-card rounded-lg p-3.5 transition-colors ${
      isStillBroken ? 'border-red-300 dark:border-red-800/60' : 'hover:border-zinc-300 dark:hover:border-zinc-700'
    }`}>
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="font-mono text-[13px] font-bold text-blue-700 dark:text-blue-400">
          #{issue.subtitle_index}
        </span>
        <span className={`font-mono text-[10.5px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded ${STATUS_TONES[issue.status]}`}>
          {issue.status === 'fixed' && '✓ '}
          {issue.status === 'still_broken' && '⚠ '}
          {STATUS_LABELS[issue.status]}
        </span>
        {issue.error_types.map(t => (
          <span
            key={t}
            className="font-mono text-[10.5px] font-medium uppercase tracking-wider px-1.5 py-0.5 rounded bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400"
          >
            {t}
          </span>
        ))}
        <div className="flex-1" />
        <span className="font-mono text-[11px] uppercase tracking-wider text-zinc-500 dark:text-zinc-500">
          Attempt {issue.fix_attempt}{issue.status === 'still_broken' ? '/2 · cần xử lý tay' : ''} · Batch {issue.batch_index + 1}
        </span>
      </div>

      <div className="grid grid-cols-[90px_1fr] gap-y-1.5 gap-x-3 items-baseline text-[12.5px]">
        <span className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-500">ZH</span>
        <span className="font-mono text-zinc-800 dark:text-zinc-200">{issue.zh}</span>

        <span className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-500">Trước</span>
        <span className="text-red-600 dark:text-red-400 line-through decoration-red-400/60">
          {issue.speaker_before && <span className="text-zinc-500 dark:text-zinc-400 mr-1 no-underline font-medium">{issue.speaker_before} —</span>}
          {issue.text_before ? `"${issue.text_before}"` : '(rỗng)'}
        </span>

        {issue.text_after && issue.status === 'fixed' && (
          <>
            <span className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-500">Sau</span>
            <span className="text-emerald-600 dark:text-emerald-400">
              {issue.speaker_after && <span className="text-zinc-500 dark:text-zinc-400 mr-1 font-medium">{issue.speaker_after} —</span>}
              "{issue.text_after}"
            </span>
          </>
        )}

        {issue.attempts.length > 0 && issue.status === 'still_broken' && (
          <>
            {issue.attempts.map((a, i) => (
              <React.Fragment key={i}>
                <span className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-500">
                  Attempt {a.attempt}
                </span>
                <span className="text-zinc-600 dark:text-zinc-400">
                  "{a.text}"
                  {a.cps_value && <span className="text-amber-600 dark:text-amber-400 ml-2 font-medium">CPS {a.cps_value.toFixed(1)}</span>}
                  {!a.passed && <span className="text-red-500 ml-2 font-medium">— không đạt</span>}
                </span>
              </React.Fragment>
            ))}
          </>
        )}
      </div>

      {/* Action buttons for still_broken */}
      {isStillBroken && (
        <div className="flex items-center gap-2 mt-3 pt-3 border-t border-zinc-200/70 dark:border-zinc-800">
          <button onClick={onRefix} className="btn text-zinc-500 !py-1 !text-[11.5px]">
            ↻ Re-fix
          </button>
          <button onClick={onManualEdit} className="btn text-zinc-500 !py-1 !text-[11.5px]">
            ✏ Sửa tay
          </button>
          <button onClick={onMarkResolved} className="btn text-zinc-500 !py-1 !text-[11.5px]">
            ✓ Mark resolved
          </button>
        </div>
      )}
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
