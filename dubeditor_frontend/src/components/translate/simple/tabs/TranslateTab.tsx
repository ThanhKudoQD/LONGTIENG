import React, { useMemo } from 'react'
import type { BatchInfo, TranslateState } from '../types'
import {
  SectionHead, ModeBar, PartCard, PromptResponsePair, InfoStrip,
} from '../shared/SharedUI'

interface Props {
  state: TranslateState
  onChangeActive: (batchIndex: number) => void
  onChangeMode: (mode: 'normal' | 'turbo') => void
  onResponseChange: (batchIndex: number, value: string) => void
  onSaveBatch: (batchIndex: number) => void
  onClearBatch: (batchIndex: number) => void
  onRunBatch: (batchIndex: number) => void
  onRunAllFromCurrent: () => void
  onRetranslate: (batchIndex: number) => void
  onOpenConfig: () => void
  onRebuild: () => void
}

export default function TranslateTab(props: Props) {
  const { state } = props
  const active = state.batches[state.active_batch_index]

  const completedCount = useMemo(
    () => state.batches.filter(b => b.status === 'done').length,
    [state.batches]
  )

  return (
    <div>
      <SectionHead
        title="Bước II · Dịch theo batch"
        subtitle="Mỗi batch nhận ACTIVE_BIBLE (subset nhân vật xuất hiện) + 15 dòng context trước → trả về [id, speaker, vi]."
        meta={
          <>
            <div><span className="text-zinc-500">Batch size:</span> {state.config.batch_size_target} dòng · gap ≥ {state.config.gap_threshold_seconds}s</div>
            <div><span className="text-zinc-500">Tiến độ:</span> {completedCount} / {state.batches.length}</div>
          </>
        }
      />

      {/* Action bar: Config + Rebuild */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <button onClick={props.onOpenConfig} className="btn">
          ⚙ Cấu hình batch
        </button>
        <button
          onClick={() => {
            if (confirm(`Rebuild lại batches với config hiện tại (size ${state.config.batch_size_target})?\n\nSẽ xóa response của các batch chưa apply. Bản dịch đã vào subtitle giữ nguyên.`)) {
              props.onRebuild()
            }
          }}
          className="btn"
          title="Chia lại batches theo batch_size hiện tại"
        >
          ↻ Rebuild batches
        </button>
        <span className="text-[12px] text-zinc-500">
          Hiện có <b className="text-zinc-700 dark:text-zinc-300">{state.batches.length}</b> batches ·
          size mục tiêu <b className="text-zinc-700 dark:text-zinc-300">{state.config.batch_size_target}</b> dòng
        </span>
      </div>

      {/* Info strip */}
      <InfoStrip
        stats={[
          { label: 'Đã dịch', value: state.total_translated.toLocaleString(), tone: 'ok' },
          { label: 'Còn lại', value: state.total_pending.toLocaleString() },
          {
            label: 'UNKNOWN ratio',
            value: `${(active?.unknown_ratio ?? 0).toFixed(1)}%`,
            tone: (active?.unknown_ratio ?? 0) > 15 ? 'warn' : 'default'
          },
          {
            label: 'Chế độ',
            value: state.config.concurrency_mode === 'turbo'
              ? `Turbo · ${state.config.turbo_concurrency}x`
              : 'Normal',
            tone: 'accent'
          },
          { label: 'Cost so far', value: `$${state.cost_so_far_usd.toFixed(2)}` },
        ]}
      />

      {/* Concurrency mode */}
      <ModeBar
        label="Chế độ chạy"
        value={state.config.concurrency_mode}
        onChange={(v) => props.onChangeMode(v as 'normal' | 'turbo')}
        options={[
          { value: 'normal', label: 'Normal · tuần tự' },
          { value: 'turbo', label: `Turbo · ${state.config.turbo_concurrency}x song song` },
        ]}
        hint={
          state.config.concurrency_mode === 'turbo'
            ? <>Dùng context Chinese thay vì context đã dịch. Nhanh ~5x, chất lượng giảm nhẹ.</>
            : <>Tuần tự từng batch. Context dùng bản dịch của batch trước → continuity tốt hơn.</>
        }
      />

      <div className="grid grid-cols-[280px_1fr] gap-4">
        {/* Sidebar — batch list */}
        <div className="surface-card rounded-lg overflow-hidden h-fit">
          <div className="flex items-center justify-between px-3 py-2.5 border-b border-zinc-200/70 dark:border-zinc-800 bg-zinc-50/80 dark:bg-zinc-900/50">
            <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-600 dark:text-zinc-400">
              Batches
            </span>
            <span className="text-[11.5px] font-mono font-semibold text-blue-700 dark:text-blue-400">
              {completedCount} / {state.batches.length}
            </span>
          </div>
          <div className="max-h-[calc(100vh-380px)] overflow-y-auto">
            {state.batches.map((b) => (
              <BatchListItem
                key={b.index}
                batch={b}
                active={b.index === state.active_batch_index}
                onClick={() => props.onChangeActive(b.index)}
              />
            ))}
          </div>
        </div>

        {/* Active batch detail */}
        <div>
          {active && (
            <PartCard
              title={<>Batch <span className="text-blue-700 dark:text-blue-400">{active.index + 1}</span> · lines {active.start_line} → {active.end_line}</>}
              range={`${active.line_count} dòng · ACTIVE_BIBLE: ${active.characters_in_batch} nhân vật · ~${Math.round((active.est_tokens_cached + active.est_tokens_variable) / 1000)}k tok`}
              status={active.status}
              headerExtra={
                active.status !== 'running' && (
                  <button
                    onClick={(e) => { e.stopPropagation(); props.onRunBatch(active.index) }}
                    className="text-[11.5px] px-2.5 py-1 rounded border border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-950/40 transition-colors font-medium"
                  >
                    ⚡ Auto
                  </button>
                )
              }
            >
              <PromptResponsePair
                prompt={active.prompt}
                response={active.response}
                onResponseChange={(v) => props.onResponseChange(active.index, v)}
                onSave={() => props.onSaveBatch(active.index)}
                onClear={() => props.onClearBatch(active.index)}
                cachedTokens={active.est_tokens_cached}
                variableTokens={active.est_tokens_variable}
                responseTokens={
                  active.status === 'running'
                    ? 'streaming...'
                    : active.response
                      ? Math.round(active.response.length / 4)
                      : 'empty'
                }
              />

              {/* Kết quả dịch đã parse */}
              <BatchResultView response={active.response} />
            </PartCard>
          )}

          <div className="flex items-center gap-2 mt-3 pt-3 border-t border-zinc-200 dark:border-zinc-800">
            <button onClick={() => props.onRunBatch(state.active_batch_index)} className="btn-primary">
              ⚡ Run Batch này
            </button>
            <button onClick={props.onRunAllFromCurrent} className="btn">
              ▶ Run All từ batch hiện tại
            </button>
            <button onClick={() => props.onRetranslate(state.active_batch_index)} className="btn text-zinc-500">
              ↻ Dịch lại
            </button>
            <div className="flex-1" />
            <button onClick={props.onOpenConfig} className="btn">
              ⚙ Cấu hình batch
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Batch list item ─────────────────────────────────────────────────────────

function BatchListItem({
  batch, active, onClick,
}: {
  batch: BatchInfo
  active: boolean
  onClick: () => void
}) {
  const dotColor: Record<string, string> = {
    idle: 'bg-zinc-300 dark:bg-zinc-600',
    running: 'bg-blue-500 animate-pulse',
    done: 'bg-emerald-500',
    error: 'bg-red-500',
  }
  return (
    <button
      onClick={onClick}
      className={`w-full flex items-center gap-3 px-3 py-2 border-b border-zinc-100 dark:border-zinc-800/60 transition-colors text-left ${
        active
          ? 'bg-blue-50/70 dark:bg-blue-950/30 border-l-[3px] border-l-blue-600 pl-[9px]'
          : 'hover:bg-zinc-50 dark:hover:bg-zinc-800/40'
      }`}
    >
      <span className={`font-mono text-[11px] w-7 ${
        active ? 'text-blue-700 dark:text-blue-400 font-bold' : 'text-zinc-500 dark:text-zinc-500'
      }`}>
        {String(batch.index + 1).padStart(2, '0')}
      </span>
      <div className="flex-1 min-w-0">
        <div className="font-mono text-[11.5px] text-zinc-800 dark:text-zinc-200">
          {batch.start_line} → {batch.end_line}
        </div>
        <div className="text-[11px] text-zinc-500 dark:text-zinc-500 mt-0.5">
          {batch.line_count} dòng · {batch.characters_in_batch} nhân vật
        </div>
      </div>
      <span className={`w-2 h-2 rounded-full ${dotColor[batch.status]}`} />
    </button>
  )
}


// ─── BatchResultView: parse JSON response → bảng kết quả dịch ────────────────

function BatchResultView({ response }: { response: string | null }) {
  const parsed = React.useMemo(() => {
    if (!response || !response.trim()) return null
    try {
      // Strip markdown wrapper nếu có
      let txt = response.trim()
      const m = txt.match(/^```(?:json)?\s*\n?([\s\S]*?)\n?```$/i)
      if (m) txt = m[1].trim()
      let data = JSON.parse(txt)

      // Nếu là dict → tìm array bên trong (gpt-5-nano trả {"subtitle":[...]})
      if (!Array.isArray(data) && data && typeof data === 'object') {
        const keys = ['subtitle', 'subtitles', 'translations', 'lines', 'result', 'data', 'items', 'output']
        let found = null
        for (const k of keys) {
          if (Array.isArray(data[k])) { found = data[k]; break }
        }
        if (!found) {
          // fallback: array đầu tiên trong object
          for (const v of Object.values(data)) {
            if (Array.isArray(v) && v.length) { found = v; break }
          }
        }
        data = found
      }
      if (!Array.isArray(data)) return null

      // Mỗi entry: [id, speaker, vi] HOẶC {id, speaker, vi}
      return data.map((e: any) => {
        if (Array.isArray(e) && e.length >= 3) {
          return { id: e[0], speaker: String(e[1]), vi: String(e[2]) }
        }
        if (e && typeof e === 'object') {
          const id = e.id ?? e.index
          const speaker = e.speaker ?? e.spk ?? ''
          const vi = e.vi ?? e.text ?? e.vietnamese ?? ''
          if (id != null) return { id, speaker: String(speaker), vi: String(vi) }
        }
        return null
      }).filter(Boolean) as { id: any; speaker: string; vi: string }[]
    } catch {
      return null
    }
  }, [response])

  if (!response || !response.trim()) return null

  if (parsed === null) {
    return (
      <div className="mt-3 surface-card p-3 border-l-4 border-amber-400">
        <span className="text-[12px] text-amber-700 dark:text-amber-300">
          ⚠ Response chưa phải JSON hợp lệ — không parse được để xem kết quả.
        </span>
      </div>
    )
  }

  return (
    <div className="mt-3 surface-card overflow-hidden">
      <div className="px-3 py-2 bg-zinc-50 dark:bg-zinc-900/60 border-b border-zinc-200/70 dark:border-zinc-800 flex items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-zinc-600 dark:text-zinc-400">
          Kết quả dịch
        </span>
        <span className="text-[11px] text-zinc-500 font-mono">{parsed.length} dòng</span>
      </div>
      <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
        <table className="w-full text-[12.5px]">
          <thead className="bg-zinc-50 dark:bg-zinc-900 text-zinc-500 text-[11px] uppercase sticky top-0">
            <tr>
              <th className="text-left px-3 py-1.5 font-medium w-14">ID</th>
              <th className="text-left px-3 py-1.5 font-medium w-28">Speaker</th>
              <th className="text-left px-3 py-1.5 font-medium">Tiếng Việt</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
            {parsed.map((row, i) => {
              const special = ['UNKNOWN', 'CROWD', 'NARRATOR', 'OFF_SCREEN', 'PHONE']
              const isSpecial = special.includes(row.speaker)
              return (
                <tr key={i} className="hover:bg-zinc-50 dark:hover:bg-zinc-900/40">
                  <td className="px-3 py-1.5 font-mono text-zinc-400 text-[11px]">{row.id}</td>
                  <td className="px-3 py-1.5">
                    <span className={`inline-block px-1.5 py-0.5 rounded text-[11px] font-mono ${
                      isSpecial
                        ? 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600 dark:text-zinc-400'
                        : 'bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                    }`}>
                      {row.speaker}
                    </span>
                  </td>
                  <td className="px-3 py-1.5 text-zinc-900 dark:text-zinc-100">{row.vi}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
