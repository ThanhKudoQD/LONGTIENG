/**
 * ProgressLog — 2 tabs:
 *   - Events: progress events (stage transitions)
 *   - LLM Calls: từng call API kèm prompt + response (collapsible)
 */
import React, { useEffect, useRef, useState } from 'react'
import type { ProgressMessage, LLMCallMessage } from '../../api'

const STAGE_LABEL: Record<string, string> = {
  'start':            'Bắt đầu',
  'normalize':        '0. Chuẩn hóa',
  'normalize_scan':   '0. Scan dòng khả nghi',
  'normalize_save':   '0. Save kết quả',
  'normalize_done':   '0. Chuẩn hóa ✓',
  'bible':            '1. Bible',
  'bible_1a':         '1A. Cast',
  'bible_save':       '1. Save Bible',
  'bible_done':       '1. Bible ✓',
  'scenes':           '2. Scenes',
  'scenes_save':      '2. Save Scenes',
  'scenes_done':      '2. Scenes ✓',
  'speaker':          '3. Speaker',
  'speaker_save':     '3. Save Speakers',
  'speaker_done':     '3. Speaker ✓',
  'translate':        '4. Translate',
  'translate_save':   '4. Save Translations',
  'translate_done':   '4. Translate ✓',
  'polish':           '5. Polish',
  'polish_save':      '5. Save Polish',
  'polish_done':      '5. Polish ✓',
  'done':             '✓ Done',
  'error':            '✗ Error',
  'cancelled':        'Cancelled',
}

function stageColor(stage: string): string {
  if (stage === 'done') return 'bg-green-600'
  if (stage === 'error') return 'bg-red-600'
  if (stage === 'cancelled') return 'bg-amber-500'
  if (stage.endsWith('_done')) return 'bg-green-500'
  if (stage.startsWith('normalize')) return 'bg-emerald-500'
  if (stage.startsWith('bible')) return 'bg-purple-500'
  if (stage.startsWith('scenes') || stage.startsWith('chunks')) return 'bg-blue-500'
  if (stage.startsWith('speaker')) return 'bg-cyan-500'
  if (stage.startsWith('translate')) return 'bg-indigo-500'
  if (stage.startsWith('polish')) return 'bg-pink-500'
  return 'bg-zinc-400'
}

type SubTab = 'events' | 'llm'

export default function ProgressLog({
  events, llmCalls = [],
}: {
  events: ProgressMessage[]
  llmCalls?: LLMCallMessage[]
}) {
  const [subTab, setSubTab] = useState<SubTab>('llm')

  // Tự động switch tab "LLM" nếu có call mới và đang ở tab events
  useEffect(() => {
    if (llmCalls.length > 0 && events.length === 0) {
      setSubTab('llm')
    }
  }, [llmCalls.length, events.length])

  if (events.length === 0 && llmCalls.length === 0) {
    return (
      <div className="p-8 text-center text-zinc-500">
        <div className="text-4xl mb-3">📜</div>
        <div className="text-sm">Chưa có log nào. Bắt đầu pipeline để xem realtime.</div>
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      {/* SubTabs */}
      <div className="flex items-center gap-1 px-3 py-1.5 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950">
        <SubTabButton
          active={subTab === 'llm'}
          onClick={() => setSubTab('llm')}
          count={llmCalls.length}
        >
          🤖 LLM Calls
        </SubTabButton>
        <SubTabButton
          active={subTab === 'events'}
          onClick={() => setSubTab('events')}
          count={events.length}
        >
          📋 Events
        </SubTabButton>
      </div>

      {subTab === 'events' && <EventsList events={events} />}
      {subTab === 'llm' && <LLMCallsList calls={llmCalls} />}
    </div>
  )
}

function SubTabButton({ active, onClick, count, children }: {
  active: boolean
  onClick: () => void
  count: number
  children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1.5 text-[12px] font-medium rounded transition-colors flex items-center gap-1.5 ${
        active
          ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
          : 'text-zinc-600 dark:text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800'
      }`}
    >
      {children}
      {count > 0 && (
        <span className="px-1.5 rounded text-[10px] font-semibold bg-zinc-200 dark:bg-zinc-700">
          {count}
        </span>
      )}
    </button>
  )
}

// ─── Events list ─────────────────────────────────────────────────────────────

function EventsList({ events }: { events: ProgressMessage[] }) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)

  useEffect(() => {
    if (autoScroll && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [events, autoScroll])

  return (
    <>
      <div className="px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 flex items-center gap-2">
        <span className="text-[11px] text-zinc-500">{events.length} events</span>
        <div className="flex-1" />
        <label className="flex items-center gap-1.5 text-[11px] text-zinc-600 dark:text-zinc-400 cursor-pointer">
          <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} />
          Auto-scroll
        </label>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-auto font-mono text-[11px] p-3 bg-zinc-950 text-zinc-300">
        {events.map((e, i) => {
          const label = STAGE_LABEL[e.stage] || e.stage
          const color = stageColor(e.stage)
          const isErr = e.stage === 'error'
          return (
            <div key={i} className={`flex items-start gap-2 py-0.5 hover:bg-white/5 px-1 -mx-1 rounded ${isErr ? 'text-red-400' : ''}`}>
              <span className="text-zinc-500 select-none">{String(i+1).padStart(3,'0')}</span>
              <span className={`inline-block px-1.5 py-0 rounded text-[10px] font-medium text-white whitespace-nowrap ${color}`}>{label}</span>
              <span className="text-zinc-400 tabular-nums w-12">{e.progress.toFixed(0)}%</span>
              <span className={`flex-1 ${isErr ? 'text-red-300' : 'text-zinc-200'}`}>{e.message}</span>
              {e.detail && Object.keys(e.detail).length > 0 && (
                <details className="text-zinc-500">
                  <summary className="cursor-pointer hover:text-zinc-300">detail</summary>
                  <pre className="mt-1 text-[10px] bg-black/30 p-2 rounded overflow-auto max-w-md">
                    {JSON.stringify(e.detail, null, 2)}
                  </pre>
                </details>
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}

// ─── LLM Calls list ──────────────────────────────────────────────────────────

function LLMCallsList({ calls }: { calls: LLMCallMessage[] }) {
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [autoScroll, setAutoScroll] = useState(true)
  const [filter, setFilter] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (autoScroll && scrollRef.current && expanded.size === 0) {
      // Chỉ auto-scroll khi không expand nào (tránh nhảy khi user đang đọc)
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [calls.length, autoScroll, expanded.size])

  const toggle = (idx: number) => {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(idx)) next.delete(idx)
      else next.add(idx)
      return next
    })
  }

  const filtered = filter
    ? calls.filter(c =>
        c.stage_tag.toLowerCase().includes(filter.toLowerCase()) ||
        c.model.toLowerCase().includes(filter.toLowerCase()) ||
        (c.prompt_preview || '').toLowerCase().includes(filter.toLowerCase()) ||
        (c.response_preview || '').toLowerCase().includes(filter.toLowerCase())
      )
    : calls

  // Stats
  const totalCost = calls.reduce((acc, c) => {
    if (!c.ok || !c.tokens_in) return acc
    // Rough estimate dùng giá Gemini Pro tier; chỉ để hiển thị
    const cost = (c.tokens_in * 1.25 + (c.tokens_out || 0) * 10) / 1e6
    return acc + cost
  }, 0)
  const totalTokensIn = calls.reduce((acc, c) => acc + (c.tokens_in || 0), 0)
  const totalTokensOut = calls.reduce((acc, c) => acc + (c.tokens_out || 0), 0)

  return (
    <>
      {/* Toolbar */}
      <div className="px-4 py-2 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-950 flex items-center gap-3 flex-wrap">
        <span className="text-[11px] text-zinc-500">
          {filtered.length}/{calls.length} calls
        </span>
        <span className="text-[11px] text-zinc-500">
          {totalTokensIn.toLocaleString()} in · {totalTokensOut.toLocaleString()} out
        </span>
        <span className="text-[11px] text-zinc-500">
          ~${totalCost.toFixed(4)} (Pro tier estimate)
        </span>
        <input
          type="text"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          placeholder="Filter stage/model/text..."
          className="input text-[11px] py-1 ml-auto w-48"
        />
        <button
          onClick={() => setExpanded(new Set(filtered.map((_, i) => i)))}
          className="text-[11px] text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
        >
          Expand all
        </button>
        <button
          onClick={() => setExpanded(new Set())}
          className="text-[11px] text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300"
        >
          Collapse
        </button>
        <label className="flex items-center gap-1.5 text-[11px] text-zinc-600 dark:text-zinc-400 cursor-pointer">
          <input type="checkbox" checked={autoScroll} onChange={e => setAutoScroll(e.target.checked)} />
          Auto-scroll
        </label>
      </div>

      {/* Calls */}
      <div ref={scrollRef} className="flex-1 overflow-auto bg-zinc-50 dark:bg-zinc-900 p-2 space-y-1.5">
        {filtered.map((call, i) => (
          <CallRow
            key={`${call.call_idx}-${i}`}
            call={call}
            isOpen={expanded.has(i)}
            onToggle={() => toggle(i)}
          />
        ))}
      </div>
    </>
  )
}

function CallRow({ call, isOpen, onToggle }: {
  call: LLMCallMessage
  isOpen: boolean
  onToggle: () => void
}) {
  // Color theo stage_tag prefix
  const tagColor = stageTagColor(call.stage_tag)
  const statusBg = call.ok ? 'bg-white dark:bg-zinc-950' : 'bg-red-50 dark:bg-red-900/20'
  const statusBorder = call.ok
    ? 'border-zinc-200 dark:border-zinc-800'
    : 'border-red-300 dark:border-red-800'

  return (
    <div className={`rounded-lg border ${statusBorder} ${statusBg} overflow-hidden`}>
      {/* Header — collapsible */}
      <button
        onClick={onToggle}
        className="w-full px-3 py-2 flex items-center gap-2 hover:bg-zinc-50 dark:hover:bg-zinc-800/50 transition-colors text-left"
      >
        <span className="font-mono text-[10px] text-zinc-400 select-none w-8">
          #{call.call_idx}
        </span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${tagColor}`}>
          {call.stage_tag || '?'}
        </span>
        <span className="font-mono text-[11px] text-zinc-500 truncate max-w-[180px]">
          {call.model}
        </span>
        {call.attempt > 1 && (
          <span className="px-1.5 rounded text-[9px] font-bold bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
            try {call.attempt}
          </span>
        )}
        {call.ok ? (
          <>
            <span className="text-[10px] text-zinc-500 tabular-nums">
              {call.timing_ms}ms
            </span>
            <span className="text-[10px] text-zinc-500 tabular-nums">
              {call.tokens_in}→{call.tokens_out}
              {(call.cached_tokens ?? 0) > 0 && (
                <span className="text-green-600 dark:text-green-400 ml-1">
                  (cached {call.cached_tokens})
                </span>
              )}
            </span>
          </>
        ) : (
          <span className="text-[11px] text-red-600 dark:text-red-400 truncate flex-1">
            ✗ {call.error}
          </span>
        )}
        <div className="flex-1" />
        <span className="text-zinc-400 text-[12px] select-none">
          {isOpen ? '▾' : '▸'}
        </span>
      </button>

      {/* Body */}
      {isOpen && (
        <div className="px-3 pb-3 pt-1 border-t border-zinc-100 dark:border-zinc-800 space-y-2">
          {/* Meta */}
          <div className="flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-zinc-500">
            <span>Provider: <strong className="text-zinc-700 dark:text-zinc-300">{call.provider}</strong></span>
            <span>Temp: <strong className="text-zinc-700 dark:text-zinc-300">{call.temperature}</strong></span>
            <span>JSON mode: <strong className="text-zinc-700 dark:text-zinc-300">{call.json_mode ? 'yes' : 'no'}</strong></span>
            <span>Prompt: <strong className="text-zinc-700 dark:text-zinc-300">{call.prompt_length.toLocaleString()} chars</strong></span>
            {call.ok && (
              <span>Response: <strong className="text-zinc-700 dark:text-zinc-300">{call.response_length?.toLocaleString()} chars</strong></span>
            )}
            {call.ok && call.finish_reason && (
              <span>Finish: <strong className="text-zinc-700 dark:text-zinc-300">{call.finish_reason}</strong></span>
            )}
          </div>

          {/* Prompt */}
          <details open>
            <summary className="cursor-pointer text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 mb-1">
              📤 Prompt ({call.prompt_length.toLocaleString()} chars)
            </summary>
            <CopyableBlock text={call.prompt_preview} />
          </details>

          {/* Response */}
          {call.ok && call.response_preview && (
            <details open>
              <summary className="cursor-pointer text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200 mb-1">
                📥 Response ({call.response_length?.toLocaleString()} chars)
              </summary>
              <CopyableBlock text={call.response_preview} />
            </details>
          )}

          {/* Error */}
          {!call.ok && (
            <div className="text-[11px] text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/20 rounded p-2 font-mono whitespace-pre-wrap">
              {call.error}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function CopyableBlock({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {}
  }
  return (
    <div className="relative group">
      <button
        onClick={handleCopy}
        className="absolute top-1 right-1 px-1.5 py-0.5 text-[10px] rounded bg-zinc-200 dark:bg-zinc-700 hover:bg-zinc-300 dark:hover:bg-zinc-600 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        {copied ? '✓ Copied' : '📋 Copy'}
      </button>
      <pre className="text-[11px] font-mono bg-zinc-100 dark:bg-zinc-900 p-2 rounded overflow-auto max-h-96 whitespace-pre-wrap break-words">
        {text}
      </pre>
    </div>
  )
}

function stageTagColor(tag: string): string {
  if (!tag) return 'bg-zinc-200 text-zinc-700'
  if (tag.startsWith('1a') || tag.startsWith('1b') || tag.startsWith('1c') || tag.includes('bible'))
    return 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300'
  if (tag.startsWith('2') || tag.includes('scene'))
    return 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
  if (tag.startsWith('3') || tag.includes('speaker'))
    return 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300'
  if (tag.startsWith('4') || tag.includes('translate'))
    return 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300'
  if (tag.startsWith('5') || tag.includes('polish') || tag.includes('condense'))
    return 'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300'
  return 'bg-zinc-200 text-zinc-700 dark:bg-zinc-700 dark:text-zinc-300'
}