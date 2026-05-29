import React, { useState } from 'react'
import type { BibleState } from '../types'
import {
  SectionHead, ModeBar, PartCard, PromptResponsePair,
} from '../shared/SharedUI'

interface Props {
  state: BibleState
  onChangeMode: (mode: 'single' | 'multi', multi_parts_count?: number) => void
  onResponseChange: (partIndex: number | 'merge', value: string) => void
  onSavePart: (partIndex: number | 'merge') => void
  onClearPart: (partIndex: number | 'merge') => void
  onRunPart: (partIndex: number | 'merge') => void
  onRunAll: () => void
  onCopyAllPrompts: () => void
  onReset: () => void
  totalSrtLines: number
  totalSrtTokens: number
}

export default function BibleTab(props: Props) {
  const { state, totalSrtLines, totalSrtTokens } = props
  // Suggest mặc định: max(2, round(lines/1000))
  const defaultPartsCount = Math.max(2, Math.round(totalSrtLines / 1000))
  // Nếu đã ở multi mode dùng số parts hiện tại; nếu single thì dùng suggest
  const [multiPartsCount, setMultiPartsCount] = useState<number>(
    state.mode === 'multi' ? state.parts.length : defaultPartsCount
  )

  const completedParts = state.parts.filter(p => p.status === 'done').length
  const allPartsDone = state.parts.every(p => p.status === 'done')
  const canRunMerge = state.mode === 'multi' && allPartsDone
  // Đã có ít nhất 1 part done → KHÓA đổi mode/số part để tránh mất Bible đã chạy
  const hasDonePart = completedParts > 0

  const tryChangeMode = (target: 'single' | 'multi', partsCount?: number) => {
    if (hasDonePart) {
      alert(
        `Bible đã có ${completedParts} part đã chạy xong.\n\n` +
        `Đổi mode/số phần sẽ XÓA hết Bible đã có.\n` +
        `Bấm "↻ Reset Bible" tường minh trước nếu thực sự muốn đổi.`
      )
      return
    }
    props.onChangeMode(target, partsCount)
  }

  const handleResetBible = () => {
    if (!confirm(
      `RESET toàn bộ Bible?\n\n` +
      `Sẽ xóa ${state.parts.length} part hiện tại (kể cả ${completedParts} part đã done).\n` +
      `Sau khi reset, bạn có thể đổi mode tùy ý và chạy lại Bible.\n\n` +
      `Tiếp tục?`
    )) return
    props.onReset()
  }

  return (
    <div>
      <SectionHead
        title="Bước I · Movie Bible"
        subtitle="Trích xuất nhân vật, quan hệ, thuật ngữ, phong cách thoại. Dùng làm bộ nhớ chung cho toàn bộ pipeline dịch."
        meta={
          <>
            <div><span className="text-zinc-500">SRT:</span> {totalSrtLines.toLocaleString()} dòng · ~{Math.round(totalSrtTokens / 1000)}k tok</div>
            <div><span className="text-zinc-500">Bible cuối:</span> ~3.2k tok</div>
          </>
        }
      />

      {/* Mode toggle */}
      <ModeBar
        label="Chế độ"
        value={state.mode}
        onChange={(v) => {
          const newMode = v as 'single' | 'multi'
          if (newMode === 'multi') {
            tryChangeMode('multi', multiPartsCount)
          } else {
            tryChangeMode('single')
          }
        }}
        options={[
          { value: 'single', label: 'Single · 1 prompt' },
          { value: 'multi', label: `Multi · ${state.parts.length || multiPartsCount} phần` },
        ]}
        hint={
          state.mode === 'multi'
            ? <>SRT lớn — khuyên dùng <b className="text-blue-700 dark:text-blue-400 font-semibold">Multi</b>. Các parts chạy song song → merge thành Master.</>
            : <>Toàn bộ SRT gửi trong 1 prompt. Phù hợp phim dưới 2000 dòng hoặc dùng Gemini/Claude.</>
        }
      />

      {/* Cảnh báo khóa khi đã có part done */}
      {hasDonePart && (
        <div className="surface-card p-3 mt-2 mb-2 bg-amber-50 dark:bg-amber-900/20 border-amber-200 dark:border-amber-800 flex items-center gap-3 flex-wrap">
          <span className="text-[12px] text-amber-800 dark:text-amber-200">
            🔒 Đã có <b>{completedParts}</b> part Bible chạy xong. Khóa đổi mode/số phần để tránh mất.
          </span>
          <button
            onClick={handleResetBible}
            className="ml-auto px-3 py-1 text-[12px] rounded-md bg-red-600 text-white hover:bg-red-700"
          >
            ↻ Reset Bible (xóa hết)
          </button>
        </div>
      )}

      {/* Multi mode: chọn số parts */}
      {state.mode === 'multi' && (
        <div className="surface-card p-3 mt-2 mb-4 flex items-center gap-3 flex-wrap">
          <span className="text-[12px] uppercase tracking-wider text-zinc-500 font-medium">
            Số phần
          </span>
          <input
            type="number"
            min={2}
            max={20}
            value={multiPartsCount}
            onChange={e => setMultiPartsCount(Math.max(2, Math.min(20, parseInt(e.target.value) || 2)))}
            className="w-20 px-2 py-1 text-[13px] border border-zinc-200 dark:border-zinc-700 rounded-md bg-white dark:bg-zinc-900"
          />
          <span className="text-[11px] text-zinc-500">
            (~{Math.round(totalSrtLines / multiPartsCount)} dòng/phần · gợi ý: {defaultPartsCount})
          </span>
          <button
            onClick={() => {
              if (multiPartsCount !== state.parts.length) {
                if (hasDonePart) {
                  tryChangeMode('multi', multiPartsCount)  // sẽ alert
                  return
                }
                if (confirm(`Đổi sang ${multiPartsCount} parts? Tất cả prompts hiện tại sẽ bị xóa và build lại.`)) {
                  props.onChangeMode('multi', multiPartsCount)
                }
              }
            }}
            disabled={multiPartsCount === state.parts.length}
            className={`btn ${multiPartsCount === state.parts.length ? 'opacity-50 cursor-not-allowed' : ''}`}
          >
            ↻ Áp dụng
          </button>
          {multiPartsCount !== state.parts.length && (
            <span className="text-[11px] text-amber-700 dark:text-amber-300">
              Hiện đang {state.parts.length} parts → bấm áp dụng để rebuild {multiPartsCount}
            </span>
          )}
        </div>
      )}

      {/* Parts */}
      {state.parts.map((part) => {
        const isCollapsed = part.status === 'done'
        return (
          <PartCard
            key={part.index}
            title={
              state.mode === 'multi'
                ? <>Part <span className="text-blue-700 dark:text-blue-400">{part.index + 1}</span> / {part.total}</>
                : <>Bible · Single prompt</>
            }
            range={`lines ${part.start_line.toLocaleString()} → ${part.end_line.toLocaleString()} · ~${Math.round(part.est_tokens / 1000)}k tok`}
            status={part.status}
            statusLabel={
              part.status === 'done'
                ? `✓ Đã lưu${part.characters_count ? ` · ${part.characters_count} nhân vật` : ''}`
                : undefined
            }
            collapsible
            defaultCollapsed={isCollapsed}
            headerExtra={
              part.status !== 'running' && (
                <button
                  onClick={(e) => { e.stopPropagation(); props.onRunPart(part.index) }}
                  className="text-[11.5px] px-2.5 py-1 rounded border border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300 hover:bg-blue-50 dark:hover:bg-blue-950/40 transition-colors font-medium"
                >
                  ⚡ Auto
                </button>
              )
            }
          >
            <PromptResponsePair
              prompt={part.prompt}
              response={part.response}
              onResponseChange={(v) => props.onResponseChange(part.index, v)}
              onSave={() => props.onSavePart(part.index)}
              onClear={() => props.onClearPart(part.index)}
              promptTokens={part.est_tokens}
              responseTokens={part.response ? Math.round(part.response.length / 4) : 'empty'}
              placeholder="Bấm Auto để gọi API, hoặc paste response JSON từ ChatGPT/Claude/Gemini vào đây..."
            />
          </PartCard>
        )
      })}

      {/* Merge card — only show if multi mode */}
      {state.mode === 'multi' && state.merge && (
        <>
          <div className="my-6 border-t border-dashed border-zinc-300 dark:border-zinc-700" />
          <PartCard
            title={<>⟡ Merge · {state.parts.length} partial → 1 master</>}
            range="resolve aliases, dedupe characters, gộp speech style"
            status={state.merge.status}
            statusLabel={
              !canRunMerge ? `— Chờ ${state.parts.length - completedParts} part còn lại` : undefined
            }
            accent
            collapsible
            defaultCollapsed={state.merge.status !== 'running'}
            headerExtra={
              canRunMerge && state.merge.status === 'idle' && (
                <button
                  onClick={(e) => { e.stopPropagation(); props.onRunPart('merge') }}
                  className="text-[11.5px] px-3 py-1 rounded bg-blue-600 text-white hover:bg-blue-500 transition-colors font-medium"
                >
                  ⚡ Auto Merge
                </button>
              )
            }
          >
            {canRunMerge ? (
              <PromptResponsePair
                prompt={state.merge.prompt}
                response={state.merge.response}
                onResponseChange={(v) => props.onResponseChange('merge', v)}
                onSave={() => props.onSavePart('merge')}
                onClear={() => props.onClearPart('merge')}
                placeholder="Bấm Auto Merge để gọi API hợp nhất, hoặc paste response..."
              />
            ) : (
              <div className="text-center py-10 text-zinc-500 dark:text-zinc-500 text-[13px]">
                Hoàn thành tất cả các parts trước khi merge.
              </div>
            )}
          </PartCard>
        </>
      )}

      {/* Action bar bottom */}
      <div className="flex items-center gap-2 mt-5 pt-4 border-t border-zinc-200 dark:border-zinc-800">
        <button onClick={props.onRunAll} className="btn-primary">
          ⚡ Run All Auto
        </button>
        <button onClick={props.onCopyAllPrompts} className="btn">
          📋 Copy All Prompts
        </button>
        <button onClick={props.onReset} className="btn text-zinc-500">
          ↻ Reset Bible
        </button>
        <div className="flex-1" />
        <span className="font-mono text-[11.5px] text-zinc-600 dark:text-zinc-400">
          <span className="text-zinc-500">Cost ước tính:</span> $0.18 Gemini Pro · $0.04 DeepSeek
        </span>
      </div>
    </div>
  )
}
