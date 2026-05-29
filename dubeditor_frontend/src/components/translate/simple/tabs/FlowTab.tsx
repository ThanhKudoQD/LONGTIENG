/**
 * FlowTab — Auto Flow: chạy Bible → Dịch → Review tự động.
 *   - Chọn bước chạy (checkbox)
 *   - Bấm Chạy → background, log realtime (polling)
 *   - Smart skip phần đã xong, retry 1 lần mỗi batch lỗi
 */
import React, { useState, useEffect, useCallback, useRef } from 'react'
import api from '../../../../api'
import { configApi } from '../simpleApi'
import type { SimpleConfig } from '../types'

interface LogEntry { ts: string; level: string; msg: string }
interface FlowStatus { phase: string; running: boolean; detail?: string }
interface FlowState { status: FlowStatus; logs: LogEntry[] }

interface Props {
  projectId: number
  runningTasks: Set<string>
  onStarted: () => void
  onOpenConfig: () => void
  onFlowDone: () => void
}

export default function FlowTab({ projectId, runningTasks, onStarted, onOpenConfig, onFlowDone }: Props) {
  const [state, setState] = useState<FlowState | null>(null)
  const [config, setConfig] = useState<SimpleConfig | null>(null)
  const [doBible, setDoBible] = useState(true)
  const [doTranslate, setDoTranslate] = useState(true)
  const [doReview, setDoReview] = useState(true)
  const [starting, setStarting] = useState(false)

  const load = useCallback(() => {
    api.get(`/projects/${projectId}/simple/flow`)
      .then(r => setState(r.data))
      .catch(() => {})
  }, [projectId])

  const loadConfig = useCallback(() => {
    configApi.get(projectId).then(setConfig).catch(() => {})
  }, [projectId])

  useEffect(() => { load(); loadConfig() }, [load, loadConfig])

  // Detect khi flow CHUYỂN TỪ running → stopped → báo parent refetch state các tab khác
  const prevRunningRef = useRef(false)
  useEffect(() => {
    const isRunning = state?.status.running ?? false
    if (prevRunningRef.current && !isRunning) {
      // Vừa kết thúc (done hoặc error)
      onFlowDone()
    }
    prevRunningRef.current = isRunning
  }, [state?.status.running, onFlowDone])

  // Nếu BE đã trả state → tin state.status.running (vì phản ánh phase done/error).
  // Chỉ fallback runningTasks khi state chưa kịp load lần đầu (state=null).
  const running = state ? state.status.running : runningTasks.has('flow.run')

  // Poll khi đang chạy
  useEffect(() => {
    if (!running) return
    const t = setInterval(load, 2000)
    return () => clearInterval(t)
  }, [running, load])

  const run = async () => {
    setStarting(true)
    try {
      await api.post(`/projects/${projectId}/simple/flow/run`, {
        do_bible: doBible,
        do_translate: doTranslate,
        do_review: doReview,
      })
      onStarted()
      setTimeout(load, 500)
    } catch (err: any) {
      alert('Lỗi: ' + (err?.response?.data?.detail || err?.message))
    } finally {
      setStarting(false)
    }
  }

  const phaseLabel: Record<string, string> = {
    idle: 'Chưa chạy', start: 'Khởi động', bible: 'Đang làm Bible',
    translate: 'Đang dịch', review: 'Đang review', done: 'Hoàn tất', error: 'Có lỗi',
  }
  const phase = state?.status.phase || 'idle'

  return (
    <div className="space-y-5 max-w-4xl">
      <div>
        <h2 className="text-[17px] font-semibold text-zinc-900 dark:text-zinc-100">⚡ Auto Flow</h2>
        <p className="text-[13px] text-zinc-500 mt-1">
          Chạy tự động tuần tự: Movie Bible → Dịch batch → AI Review. Bỏ qua phần đã xong,
          tự retry 1 lần khi 1 batch lỗi.
        </p>
      </div>

      {/* Tóm tắt cấu hình hiện tại */}
      <div className="surface-card p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="text-[12px] uppercase tracking-wider text-zinc-500 font-medium">Cấu hình đang dùng</div>
          <button onClick={onOpenConfig} className="btn text-[12px]">⚙ Đổi cấu hình</button>
        </div>
        {!config ? (
          <div className="text-[12px] text-zinc-400">Đang tải...</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 text-[12.5px]">
            <ConfigSummaryCard
              step="1 · Bible" model={config.tasks.bible?.model}
              provider={config.tasks.bible?.provider} thinking={config.tasks.bible?.thinking}
              extra={null}
            />
            <ConfigSummaryCard
              step="2 · Dịch" model={config.tasks.translate?.model}
              provider={config.tasks.translate?.provider} thinking={config.tasks.translate?.thinking}
              extra={`${config.batch_size_target} dòng/batch`}
            />
            <ConfigSummaryCard
              step="3 · Review" model={config.tasks.qa?.model}
              provider={config.tasks.qa?.provider} thinking={config.tasks.qa?.thinking}
              extra={`${config.review_batch_size} dòng/batch`}
            />
          </div>
        )}
      </div>

      {/* Cấu hình bước */}
      <div className="surface-card p-4 space-y-3">
        <div className="text-[12px] uppercase tracking-wider text-zinc-500 font-medium">Chọn bước chạy</div>
        <div className="space-y-2">
          <StepCheck label="1 · Movie Bible" desc="Trích xuất nhân vật, quan hệ, thuật ngữ (bỏ qua nếu đã có)"
            checked={doBible} onChange={setDoBible} />
          <StepCheck label="2 · Dịch batch" desc="Dịch các batch chưa dịch (bỏ qua batch đã xong)"
            checked={doTranslate} onChange={setDoTranslate} />
          <StepCheck label="3 · AI Review" desc="Rà soát bản dịch, sinh đề xuất sửa (không tự apply)"
            checked={doReview} onChange={setDoReview} />
        </div>

        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={run}
            disabled={running || starting || (!doBible && !doTranslate && !doReview)}
            className="btn btn-primary"
          >
            {running ? '⏳ Đang chạy...' : starting ? 'Khởi động...' : '⚡ Chạy Auto Flow'}
          </button>
          <button onClick={load} className="btn text-[12px]">↻ Cập nhật log</button>
          <span className={`text-[13px] font-medium ${
            phase === 'done' ? 'text-emerald-600' : phase === 'error' ? 'text-red-600' :
            running ? 'text-blue-600' : 'text-zinc-500'
          }`}>
            {phaseLabel[phase] || phase}
            {state?.status.detail && running && ` · ${state.status.detail}`}
            {running && <span className="inline-block ml-2 w-2 h-2 rounded-full bg-blue-500 animate-pulse" />}
          </span>
        </div>
      </div>

      {/* Log */}
      <div className="surface-card overflow-hidden">
        <div className="px-3 py-2 bg-zinc-50 dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800 text-[11px] uppercase tracking-wider text-zinc-500 font-medium">
          Nhật ký chạy
        </div>
        <div className="max-h-[400px] overflow-y-auto p-3 space-y-1 font-mono text-[12px]">
          {!state || state.logs.length === 0 ? (
            <div className="text-zinc-400 text-center py-6">Chưa có log. Bấm "⚡ Chạy Auto Flow" để bắt đầu.</div>
          ) : (
            state.logs.map((l, i) => (
              <div key={i} className={`flex gap-2 ${
                l.level === 'error' ? 'text-red-600' :
                l.level === 'warn' ? 'text-amber-600' :
                l.level === 'ok' ? 'text-emerald-600' : 'text-zinc-600 dark:text-zinc-400'
              }`}>
                <span className="text-zinc-400 shrink-0">{fmtTime(l.ts)}</span>
                <span>{iconFor(l.level)} {l.msg}</span>
              </div>
            ))
          )}
        </div>
      </div>

      <p className="text-[11px] text-zinc-500">
        💡 Flow chạy nền — bạn có thể chuyển tab khác xem tiến độ. Sau khi xong, vào tab
        Review để duyệt đề xuất, hoặc tab Phụ đề để xem bản dịch.
      </p>
    </div>
  )
}

function StepCheck({ label, desc, checked, onChange }: {
  label: string; desc: string; checked: boolean; onChange: (v: boolean) => void
}) {
  return (
    <label className="flex items-start gap-3 p-2 rounded-md hover:bg-zinc-50 dark:hover:bg-zinc-900/40 cursor-pointer">
      <input type="checkbox" checked={checked} onChange={e => onChange(e.target.checked)} className="mt-0.5" />
      <div>
        <div className="text-[13px] font-medium text-zinc-800 dark:text-zinc-200">{label}</div>
        <div className="text-[11px] text-zinc-500">{desc}</div>
      </div>
    </label>
  )
}

function ConfigSummaryCard({ step, model, provider, thinking, extra }: {
  step: string
  model?: string
  provider?: string
  thinking?: boolean
  extra: string | null
}) {
  return (
    <div className="border border-zinc-200 dark:border-zinc-700 rounded-md p-2.5 bg-zinc-50/50 dark:bg-zinc-900/40">
      <div className="text-[11px] font-medium text-zinc-500 mb-1">{step}</div>
      {model ? (
        <>
          <div className="font-medium text-zinc-800 dark:text-zinc-200 text-[12.5px]">{model}</div>
          <div className="text-[11px] text-zinc-500 mt-0.5">
            {provider}{thinking && ' · thinking'}
          </div>
          {extra && <div className="text-[11px] text-zinc-500 mt-0.5">{extra}</div>}
        </>
      ) : (
        <div className="text-[12px] text-amber-600">Chưa cấu hình</div>
      )}
    </div>
  )
}

function fmtTime(ts: string): string {
  try {
    const d = new Date(ts)
    return d.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch { return '' }
}

function iconFor(level: string): string {
  return level === 'error' ? '✕' : level === 'warn' ? '⚠' : level === 'ok' ? '✓' : '·'
}
