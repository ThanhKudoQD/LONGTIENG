/**
 * IssueQueue — hàng đợi vấn đề từ Stage 5 Polish.
 *
 * Filter theo type / confidence. Mỗi issue có 2 action: Apply / Dismiss.
 */
import React, { useState } from 'react'
import { translateApi } from '../../api'
import type { PolishIssue } from '../../types'
import { ISSUE_TYPE_LABELS } from '../../types'

export default function IssueQueue({
  projectId, issues, onUpdate,
}: {
  projectId: number
  issues: PolishIssue[]
  onUpdate: () => void
}) {
  const [filterType, setFilterType] = useState<string | null>(null)
  const [filterConf, setFilterConf] = useState<string | null>(null)

  if (issues.length === 0) {
    return (
      <div className="p-8 text-center text-zinc-500">
        <div className="text-4xl mb-3">✅</div>
        <div className="text-sm">Không có vấn đề. Bản dịch sạch!</div>
      </div>
    )
  }

  let filtered = issues
  if (filterType) filtered = filtered.filter(i => i.issue_type === filterType)
  if (filterConf) {
    filtered = filtered.filter(i => {
      const c = (i.confidence || '').toLowerCase()
      if (filterConf === 'high') return c === 'h' || c === 'high'
      if (filterConf === 'mid') return c === 'm' || c === 'mid'
      if (filterConf === 'low') return c === 'l' || c === 'low'
      return true
    })
  }

  const typeCounts = issues.reduce<Record<string, number>>((acc, i) => {
    acc[i.issue_type] = (acc[i.issue_type] || 0) + 1
    return acc
  }, {})

  return (
    <div className="p-4 max-w-5xl mx-auto">
      {/* Filters */}
      <div className="bg-white dark:bg-zinc-950 rounded-lg border border-zinc-200 dark:border-zinc-800 p-3 mb-4 sticky top-0 z-10">
        <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-2">
          Filter ({filtered.length}/{issues.length})
        </div>

        <div className="flex flex-wrap gap-1 mb-2">
          <FilterChip active={filterType === null} onClick={() => setFilterType(null)}>
            Tất cả ({issues.length})
          </FilterChip>
          {Object.entries(typeCounts).map(([type, count]) => (
            <FilterChip
              key={type}
              active={filterType === type}
              onClick={() => setFilterType(filterType === type ? null : type)}
            >
              {ISSUE_TYPE_LABELS[type] || type} ({count})
            </FilterChip>
          ))}
        </div>

        <div className="flex gap-1">
          <FilterChip active={filterConf === null} onClick={() => setFilterConf(null)}>Mọi confidence</FilterChip>
          <FilterChip
            active={filterConf === 'high'}
            onClick={() => setFilterConf(filterConf === 'high' ? null : 'high')}
            color="green"
          >High</FilterChip>
          <FilterChip
            active={filterConf === 'mid'}
            onClick={() => setFilterConf(filterConf === 'mid' ? null : 'mid')}
            color="blue"
          >Mid</FilterChip>
          <FilterChip
            active={filterConf === 'low'}
            onClick={() => setFilterConf(filterConf === 'low' ? null : 'low')}
            color="amber"
          >Low</FilterChip>
        </div>
      </div>

      {/* List */}
      <div className="space-y-2">
        {filtered.map(iss => (
          <IssueCard
            key={iss.id}
            issue={iss}
            onApply={async () => {
              await translateApi.applyIssue(projectId, iss.id)
              onUpdate()
            }}
            onDismiss={async () => {
              await translateApi.dismissIssue(projectId, iss.id)
              onUpdate()
            }}
          />
        ))}
      </div>
    </div>
  )
}

function FilterChip({ active, onClick, children, color = 'blue' }: {
  active: boolean; onClick: () => void; children: React.ReactNode; color?: string
}) {
  const colorClasses: Record<string, string> = {
    blue: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
    green: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
    amber: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
  }
  return (
    <button
      onClick={onClick}
      className={`px-2 py-1 rounded text-[11px] font-medium transition-colors ${
        active
          ? colorClasses[color] || colorClasses.blue
          : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400 hover:bg-zinc-200 dark:hover:bg-zinc-700'
      }`}
    >
      {children}
    </button>
  )
}

function IssueCard({ issue, onApply, onDismiss }: {
  issue: PolishIssue
  onApply: () => void
  onDismiss: () => void
}) {
  const [busy, setBusy] = useState(false)

  const typeColor =
    issue.issue_type === 'untranslated' ? 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300' :
    issue.issue_type === 'empty' ? 'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300' :
    issue.issue_type === 'chinese_remains' ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300' :
    'bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300'

  const conf = (issue.confidence || '').toLowerCase()
  const confDot =
    (conf === 'h' || conf === 'high') ? 'bg-green-500' :
    (conf === 'm' || conf === 'mid') ? 'bg-blue-500' :
    'bg-amber-500'

  async function handleApply() {
    setBusy(true); try { await onApply() } finally { setBusy(false) }
  }
  async function handleDismiss() {
    setBusy(true); try { await onDismiss() } finally { setBusy(false) }
  }

  return (
    <div className="bg-white dark:bg-zinc-950 rounded-lg border border-zinc-200 dark:border-zinc-800 p-4">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="font-mono text-[11px] text-zinc-400">Dòng #{issue.line_index}</span>
        <span className={`px-2 py-0.5 rounded text-[10px] font-medium ${typeColor}`}>
          {ISSUE_TYPE_LABELS[issue.issue_type] || issue.issue_type}
        </span>
        <span className="flex items-center gap-1 text-[10px] text-zinc-500">
          <span className={`w-1.5 h-1.5 rounded-full ${confDot}`} />
          {issue.confidence}
        </span>
      </div>

      <div className="text-[13px] text-zinc-800 dark:text-zinc-100 mb-2">
        {issue.description}
      </div>

      {/* Current vs suggested */}
      <div className="space-y-1 mb-3">
        <div className="text-[11px] text-zinc-500 uppercase tracking-widest">Hiện tại:</div>
        <div className="text-[13px] px-3 py-2 rounded bg-red-50 dark:bg-red-900/20 text-red-900 dark:text-red-200 line-through">
          {issue.current_text || '(empty)'}
        </div>

        {issue.suggested_text && (
          <>
            <div className="text-[11px] text-zinc-500 uppercase tracking-widest mt-2">Đề xuất:</div>
            <div className="text-[13px] px-3 py-2 rounded bg-green-50 dark:bg-green-900/20 text-green-900 dark:text-green-200">
              {issue.suggested_text}
            </div>
          </>
        )}
      </div>

      {issue.evidence && (
        <div className="text-[11px] text-zinc-500 italic mb-3 border-l-2 border-zinc-200 dark:border-zinc-700 pl-2">
          💡 {issue.evidence}
        </div>
      )}

      <div className="flex gap-2">
        {issue.suggested_text && (
          <button
            onClick={handleApply}
            disabled={busy}
            className="btn-primary text-[12px]"
          >
            ✓ Áp dụng đề xuất
          </button>
        )}
        <button
          onClick={handleDismiss}
          disabled={busy}
          className="btn text-[12px] text-zinc-500"
        >
          ✗ Bỏ qua
        </button>
      </div>
    </div>
  )
}
