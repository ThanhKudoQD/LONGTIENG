import React, { useState } from 'react'

// ─── Shared UI primitives cho Simple Translator ──────────────────────────────
//
// Typography note (v2):
// - Bỏ font-serif (system serif xấu, không đồng nhất giữa các máy)
// - Dùng font-sans (kế thừa từ body) cho mọi text UI
// - Dùng font-mono cho data/code/prompt/timestamps
// - Title dùng font-semibold/bold + size lớn, không italic
// - Tăng contrast: zinc-500 → zinc-600 cho secondary text
// - Padding rộng hơn cho cards (p-4 thay vì p-3)

// ─── PromptResponsePair ─────────────────────────────────────────────────────

export interface PromptResponsePairProps {
  prompt: string
  response: string | null
  onResponseChange: (value: string) => void
  onSave: () => void
  onClear?: () => void
  promptTokens?: number
  responseTokens?: number | string
  cachedTokens?: number
  variableTokens?: number
  readOnly?: boolean
  disabled?: boolean
  placeholder?: string
}

export function PromptResponsePair({
  prompt, response, onResponseChange, onSave, onClear,
  promptTokens, responseTokens, cachedTokens, variableTokens,
  disabled, placeholder,
}: PromptResponsePairProps) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    await navigator.clipboard.writeText(prompt)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const tokenLabel = cachedTokens != null && variableTokens != null
    ? `cached ${cachedTokens.toLocaleString()} · variable ${variableTokens.toLocaleString()}`
    : promptTokens != null
      ? `≈ ${promptTokens.toLocaleString()} tokens`
      : ''

  return (
    <div className="grid grid-cols-2 gap-3">
      {/* Prompt column */}
      <div className="surface-card rounded-lg overflow-hidden flex flex-col min-h-[240px]">
        <div className="flex items-center gap-2 px-3 py-2 bg-zinc-50 dark:bg-zinc-900/60 border-b border-zinc-200/70 dark:border-zinc-800">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-600 dark:text-zinc-400">
            Prompt
          </span>
          {tokenLabel && (
            <span className="text-[11px] text-zinc-500 dark:text-zinc-500 font-mono">
              {tokenLabel}
            </span>
          )}
          <div className="flex-1" />
          <button
            onClick={handleCopy}
            className="text-[12px] px-2.5 py-1 rounded border border-zinc-200 dark:border-zinc-700 text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-zinc-800 transition-colors font-medium"
          >
            {copied ? '✓ Đã copy' : '📋 Copy'}
          </button>
        </div>
        <textarea
          readOnly
          value={prompt}
          className="flex-1 bg-transparent outline-none p-3.5 font-mono text-[12px] leading-relaxed text-zinc-700 dark:text-zinc-300 resize-none"
        />
      </div>

      {/* Response column */}
      <div className="surface-card rounded-lg overflow-hidden flex flex-col min-h-[240px]">
        <div className="flex items-center gap-2 px-3 py-2 bg-zinc-50 dark:bg-zinc-900/60 border-b border-zinc-200/70 dark:border-zinc-800">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-600 dark:text-zinc-400">
            Response
          </span>
          {responseTokens != null && (
            <span className="text-[11px] text-zinc-500 dark:text-zinc-500 font-mono">
              {typeof responseTokens === 'number'
                ? `≈ ${responseTokens.toLocaleString()} tokens`
                : responseTokens}
            </span>
          )}
          <div className="flex-1" />
          {onClear && (
            <button
              onClick={onClear}
              className="text-[12px] px-2.5 py-1 rounded border border-zinc-200 dark:border-zinc-700 text-zinc-600 dark:text-zinc-400 hover:bg-red-50 hover:text-red-600 hover:border-red-300 dark:hover:bg-red-950/30 transition-colors"
            >
              Clear
            </button>
          )}
          <button
            onClick={onSave}
            disabled={disabled || !response}
            className="text-[12px] px-3 py-1 rounded bg-blue-600 text-white font-medium hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
          >
            💾 Lưu
          </button>
        </div>
        <textarea
          value={response ?? ''}
          onChange={(e) => onResponseChange(e.target.value)}
          placeholder={placeholder || 'Bấm Auto để gọi API, hoặc paste response từ ChatGPT/Claude/Gemini vào đây...'}
          className="flex-1 bg-transparent outline-none p-3.5 font-mono text-[12px] leading-relaxed text-zinc-800 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 resize-none"
        />
      </div>
    </div>
  )
}

// ─── StatusBadge ────────────────────────────────────────────────────────────

export function StatusBadge({
  status, label,
}: {
  status: 'idle' | 'running' | 'done' | 'error' | 'warning'
  label?: string
}) {
  const styles: Record<string, string> = {
    idle:    'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400',
    running: 'bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
    done:    'bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300',
    error:   'bg-red-50 text-red-700 dark:bg-red-900/30 dark:text-red-300',
    warning: 'bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  }
  const labels: Record<string, string> = {
    idle: '— Chưa chạy',
    running: '⏵ Đang chạy',
    done: '✓ Xong',
    error: '✕ Lỗi',
    warning: '⚠ Cảnh báo',
  }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium uppercase tracking-wider ${styles[status]}`}>
      {status === 'running' && (
        <span className="w-1.5 h-1.5 mr-1.5 rounded-full bg-current animate-pulse" />
      )}
      {label || labels[status]}
    </span>
  )
}

// ─── PartCard ───────────────────────────────────────────────────────────────

export interface PartCardProps {
  title: React.ReactNode
  range: React.ReactNode
  status: 'idle' | 'running' | 'done' | 'error' | 'warning'
  statusLabel?: string
  accent?: boolean
  collapsible?: boolean
  defaultCollapsed?: boolean
  headerExtra?: React.ReactNode
  children?: React.ReactNode
}

export function PartCard({
  title, range, status, statusLabel, accent,
  collapsible, defaultCollapsed = false, headerExtra, children,
}: PartCardProps) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed)

  return (
    <div className={`surface-card rounded-lg overflow-hidden mb-3 transition-all ${
      accent
        ? 'border-blue-300 dark:border-blue-700/60 shadow-[0_0_0_1px_rgba(59,130,246,0.12)]'
        : ''
    }`}>
      <div
        className={`flex items-center gap-3 px-4 py-3 border-b border-zinc-200/70 dark:border-zinc-800 ${
          accent
            ? 'bg-gradient-to-r from-blue-50/80 to-zinc-50 dark:from-blue-950/30 dark:to-zinc-900/40'
            : 'bg-zinc-50/80 dark:bg-zinc-900/40'
        } ${collapsible ? 'cursor-pointer hover:bg-zinc-100/60 dark:hover:bg-zinc-800/50' : ''}`}
        onClick={collapsible ? () => setCollapsed(!collapsed) : undefined}
      >
        <div className="flex items-baseline gap-3 min-w-0">
          <span className="text-[13.5px] font-semibold text-zinc-900 dark:text-zinc-100 whitespace-nowrap">
            {title}
          </span>
          <span className="text-[11.5px] text-zinc-500 dark:text-zinc-400 font-mono truncate">
            {range}
          </span>
        </div>
        <div className="flex-1" />
        {headerExtra}
        <StatusBadge status={status} label={statusLabel} />
        {collapsible && (
          <span className="text-zinc-400 text-xs ml-1">{collapsed ? '▸' : '▾'}</span>
        )}
      </div>
      {children && !collapsed && (
        <div className="p-4">{children}</div>
      )}
    </div>
  )
}

// ─── ModeBar ────────────────────────────────────────────────────────────────

export interface ModeBarProps {
  label: string
  options: { value: string; label: string }[]
  value: string
  onChange: (v: string) => void
  hint?: React.ReactNode
}

export function ModeBar({ label, options, value, onChange, hint }: ModeBarProps) {
  return (
    <div className="surface-card rounded-lg px-4 py-3 mb-4 flex items-center gap-4 flex-wrap">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-600 dark:text-zinc-400">
        {label}
      </span>
      <div className="inline-flex bg-zinc-100 dark:bg-zinc-800/80 rounded-md p-0.5 gap-0.5">
        {options.map(opt => (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            className={`px-3 py-1.5 text-[12.5px] font-medium rounded transition-colors ${
              value === opt.value
                ? 'bg-white dark:bg-zinc-700 text-zinc-900 dark:text-zinc-100 shadow-sm'
                : 'text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-200'
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
      {hint && (
        <span className="text-[12px] text-zinc-600 dark:text-zinc-400 ml-1 leading-snug">
          {hint}
        </span>
      )}
    </div>
  )
}

// ─── SectionHead ────────────────────────────────────────────────────────────

export function SectionHead({
  title, subtitle, meta,
}: {
  title: string
  subtitle?: string
  meta?: React.ReactNode
}) {
  return (
    <div className="flex items-end justify-between mb-5 pb-3 border-b border-zinc-200 dark:border-zinc-800">
      <div>
        <h1 className="text-[22px] font-bold tracking-tight text-zinc-900 dark:text-zinc-100 leading-tight">
          {title}
        </h1>
        {subtitle && (
          <p className="text-[12.5px] text-zinc-600 dark:text-zinc-400 mt-1.5 max-w-2xl leading-relaxed">
            {subtitle}
          </p>
        )}
      </div>
      {meta && (
        <div className="text-right font-mono text-[11px] text-zinc-600 dark:text-zinc-400 leading-relaxed">
          {meta}
        </div>
      )}
    </div>
  )
}

// ─── InfoStrip ──────────────────────────────────────────────────────────────

export interface InfoStat {
  label: string
  value: React.ReactNode
  tone?: 'default' | 'ok' | 'warn' | 'err' | 'accent'
}

export function InfoStrip({ stats }: { stats: InfoStat[] }) {
  const toneClass: Record<string, string> = {
    default: 'text-zinc-900 dark:text-zinc-100',
    ok:      'text-emerald-600 dark:text-emerald-400',
    warn:    'text-amber-600 dark:text-amber-400',
    err:     'text-red-600 dark:text-red-400',
    accent:  'text-blue-600 dark:text-blue-400',
  }
  return (
    <div className="surface-card rounded-lg px-4 py-3.5 mb-4 flex gap-7 flex-wrap">
      {stats.map((s, i) => (
        <div key={i} className="flex flex-col gap-1 min-w-[80px]">
          <span className="text-[10.5px] font-semibold uppercase tracking-wider text-zinc-500 dark:text-zinc-500">
            {s.label}
          </span>
          <span className={`text-[20px] font-bold leading-none ${toneClass[s.tone || 'default']}`}>
            {s.value}
          </span>
        </div>
      ))}
    </div>
  )
}

// ─── Tab badge ──────────────────────────────────────────────────────────────

export function TabBadge({
  children, tone = 'default', pulse,
}: {
  children: React.ReactNode
  tone?: 'default' | 'ok' | 'warn' | 'err' | 'info'
  pulse?: boolean
}) {
  const styles: Record<string, string> = {
    default: 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400',
    ok:      'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
    warn:    'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
    err:     'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
    info:    'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  }
  return (
    <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-[11px] font-mono font-medium tracking-wide ${styles[tone]} ${pulse ? 'animate-pulse' : ''}`}>
      {children}
    </span>
  )
}

// ─── TabNumber (số chỉ pipeline step) ──────────────────────────────────────
// Bỏ La Mã italic — dùng số Arabic trong khung tròn rõ ràng

export function TabNumber({ n, active }: { n: number; active: boolean }) {
  return (
    <span className={`inline-flex items-center justify-center w-5 h-5 rounded-full text-[11px] font-bold ${
      active
        ? 'bg-blue-600 text-white'
        : 'bg-zinc-200 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'
    }`}>
      {n}
    </span>
  )
}
