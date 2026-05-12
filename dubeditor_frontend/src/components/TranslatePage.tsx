/**
 * TranslatePage.tsx
 * Full-page dịch thuật — 3 bước tuần tự:
 *   Step 0 — Làm sạch phụ đề (scan local + AI clean tùy chọn)
 *   Step 1 — Phân tích phim: Pass 1 → Bible
 *   Step 2 — Dịch: Pass 3 → chunk list + chi tiết từng chunk
 */
import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react'
import api from '../api'
import useStore from '../store'
import type { Subtitle, Bible, BibleCharacter } from '../types'
import { loadConfig, getApiKey } from './ConfigModal'
import ConfigModal from './ConfigModal'

// ─── Types ────────────────────────────────────────────────────────────────────

type StepId = 0 | 1 | 2 | 3 | 4

interface Pass0Issue {
  index: number
  text: string
  reason: string
}

interface Pass0State {
  scanned: boolean
  issues: Pass0Issue[]
  running: boolean
  // Schema mới khớp backend: action="clean"|"delete", cleaned (text mới khi clean), reason (lý do AI)
  report: Array<{
    index: number
    action: 'clean' | 'delete'
    original: string
    cleaned: string   // text sau khi clean, rỗng nếu action=delete
    reason: string    // lý do AI quyết định
  }>
  cleaned: boolean
}

interface Pass1SubResult {
  prompt: string
  response: string
  tokens_in: number
  tokens_out: number
  timing_ms: number
}

interface Pass1State {
  running: boolean
  done: boolean
  elapsedMs: number
  tokensIn: number
  tokensOut: number
  timingMs: number
  bible: Bible | null
  error: string
  // Chi tiết từng sub-pass — để FE hiển thị tab API call
  pass1a: Pass1SubResult | null
  pass1b: Pass1SubResult | null
  // Tiến trình 2 bước
  stage: 'idle' | 'pass1a' | 'pass1b' | 'merging' | 'done'
  stageMessage: string
  // Stats từng bước (để hiện ngay khi 1A xong, không đợi 1B)
  pass1aStats: { nhan_vat: number; time_ms: number } | null
  pass1bStats: { scene_count: number; time_ms: number } | null
}

interface Pass2SpeakerState {
  running:     boolean
  done:        boolean
  total:       number   // tổng số dòng phụ đề
  updated:     number   // số dòng AI cập nhật character_id
  unknown:     number   // số dòng AI báo "?"
  tokensIn:    number
  tokensOut:   number
  timingMs:    number
  sceneCount:  number   // số scene đã xử lý
  doneScenes:  number   // số scene đã xong (live update từ SSE)
  totalScenes: number
  error:       string
  stageMessage: string
}

interface ChunkState {
  index: number
  startLine: number
  endLine: number
  lineCount: number
  status: 'wait' | 'run' | 'done' | 'err'
  tomTat: string
  response: string   // raw response từ AI
  prompt: string     // prompt đã gửi (nếu BE trả về)
  tokensIn: number
  tokensOut: number
  timingMs: number
  error: string
  entries: Array<{ index: number; original: string; translated: string; speaker?: string }>
  // QC snapshot từ DB — restore khi user chuyển chunk khác rồi quay lại
  qcVanDe?: any[] | null
  qcTongKet?: any | null
  qcTokensIn?: number
  qcTokensOut?: number
  qcTimingMs?: number
  qcModel?: string
  qcRunAt?: string
}

interface Pass3State {
  running: boolean        // true khi đang chạy full-run (tất cả chunks)
  runningChunks: Set<number>  // track từng chunk đang chạy độc lập
  done: boolean
  chunks: ChunkState[]
  totalTokensIn: number
  totalTokensOut: number
  totalTimingMs: number
  error: string
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function fmt(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  const s = (ms / 1000).toFixed(1)
  return `${s}s`
}

function fmtTokens(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return String(n)
}

// Pass 0: scan local — detect dòng rác không cần gọi AI
function scanAbnormal(subs: Subtitle[]): Pass0Issue[] {
  // ⚠ LOGIC NÀY PHẢI KHỚP với detect_abnormal_entries() ở backend
  // (srt_translator/backend/translator.py:1383). Khi sửa, sửa cả 2 nơi.
  const isCJK = (c: string) => {
    const code = c.codePointAt(0) || 0
    return code >= 0x4E00 && code <= 0x9FFF
  }

  const issues: Pass0Issue[] = []
  for (const s of subs) {
    const t = (s.original_text || s.text || '').trim()
    if (!t) continue

    const reasons: string[] = []

    // 1. Text quá dài: >25 ký tự CJK hoặc >50 ký tự tổng
    const cjkLen = [...t].filter(isCJK).length
    if (cjkLen > 25 || t.length > 50) {
      reasons.push('Quá dài')
    }

    // 2. Có chuỗi Latin ≥3 ký tự liên tiếp
    if (/[A-Za-z]{3,}/.test(t)) {
      reasons.push('Có Latin (có thể logo)')
    }

    // 3. Có xuống dòng thật
    if (/\n/.test(t)) {
      reasons.push('Multi-line')
    }

    // 4. Có 2+ cụm CJK ≥3 ký tự cách nhau bằng dấu cách (multi-region OCR)
    const parts = t.split(/\s+/).filter(p => [...p].filter(isCJK).length >= 3)
    if (parts.length >= 2) {
      reasons.push('Multi-region OCR')
    }

    // 5. Lặp 1 ký tự ≥5 lần liên tiếp (OCR glitch)
    if (/(.)\1{4,}/.test(t)) {
      reasons.push('Lặp ký tự bất thường')
    }

    // 6. Ký tự nhạc thuần túy ♪♫
    if (/^[\u266a-\u266f\s]+$/.test(t)) {
      reasons.push('Ký tự nhạc')
    }

    // 7. Tag âm thanh [Music], [Applause]
    if (/^\[.{1,20}\]$/.test(t)) {
      reasons.push('Tag âm thanh')
    }

    // 8. Mix Latin/số dài giữa CJK
    if (cjkLen >= 1 && /[A-Za-z0-9]{4,}/.test(t)) {
      reasons.push('Lẫn chuỗi Latin/số')
    }

    if (reasons.length > 0) {
      issues.push({ index: s.index, text: t, reason: reasons.join(' · ') })
    }
  }
  return issues
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function StepHeader({
  steps, current, onSelect,
}: {
  steps: Array<{ id: StepId; label: string; sublabel: string; icon: string }>
  current: StepId
  onSelect: (s: StepId) => void
}) {
  return (
    <div className="flex items-stretch border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex-shrink-0">
      {steps.map((step, i) => {
        const isCur = step.id === current
        return (
          <React.Fragment key={step.id}>
            <button onClick={() => onSelect(step.id)}
              className={`flex items-center gap-3 px-6 py-3 transition-all border-b-2 ${
                isCur
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-950/20'
                  : 'border-transparent hover:bg-zinc-50 dark:hover:bg-zinc-800'
              }`}>
              <span className="text-xl leading-none">{step.icon}</span>
              <div className="text-left">
                <div className={`text-[12px] font-bold ${isCur ? 'text-blue-600 dark:text-blue-400' : 'text-zinc-600 dark:text-zinc-300'}`}>
                  {step.label}
                </div>
                <div className="text-[10px] text-zinc-400">{step.sublabel}</div>
              </div>
            </button>
            {i < steps.length - 1 && (
              <div className="w-px self-stretch my-2 bg-zinc-200 dark:bg-zinc-700" />
            )}
          </React.Fragment>
        )
      })}
    </div>
  )
}

// ─── Step 0: Làm sạch ─────────────────────────────────────────────────────────

function Step0Panel({
  subs, state, onScan, onClean, onSkip,
}: {
  subs: Subtitle[]
  state: Pass0State
  onScan: () => void
  onClean: () => void
  onSkip: () => void
}) {
  return (
    <div className="flex flex-col gap-4 p-6 max-w-3xl mx-auto w-full">
      <div>
        <div className="text-[15px] font-bold text-zinc-800 dark:text-zinc-100 mb-1">
          Làm sạch phụ đề
        </div>
        <div className="text-[12px] text-zinc-400">
          Tìm và loại bỏ các dòng rác trước khi dịch — cải thiện chất lượng output.
        </div>
      </div>

      {/* Scan result */}
      {!state.scanned ? (
        <div className="flex items-center gap-3 p-4 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/60">
          <span className="text-zinc-400 text-[13px]">{subs.length} dòng phụ đề · Chưa quét</span>
          <button onClick={onScan} className="btn-primary ml-auto">
            🔍 Quét ngay (không tốn API)
          </button>
        </div>
      ) : (
        <div className={`flex items-center gap-3 px-4 py-3 rounded-xl border ${
          state.issues.length === 0
            ? 'border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/20'
            : 'border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/20'
        }`}>
          <span className="text-lg">{state.issues.length === 0 ? '✅' : '⚠️'}</span>
          <span className="text-[13px] font-medium">
            {state.issues.length === 0
              ? `${subs.length} dòng · Không tìm thấy dòng rác`
              : `${subs.length} dòng · Tìm thấy ${state.issues.length} dòng nghi ngờ`}
          </span>
          <button onClick={onScan} className="btn ml-auto text-[11px]">Quét lại</button>
        </div>
      )}

      {/* Issues list */}
      {state.scanned && state.issues.length > 0 && !state.cleaned && (
        <div className="flex flex-col gap-2">
          <div className="panel-label">Dòng nghi ngờ</div>
          <div className="flex flex-col divide-y divide-zinc-100 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl overflow-hidden">
            {state.issues.map(issue => (
              <div key={issue.index} className="flex items-start gap-3 px-4 py-2.5">
                <span className="text-[10px] font-mono text-zinc-400 w-8 flex-shrink-0 pt-0.5">
                  #{issue.index}
                </span>
                <div className="flex-1 min-w-0">
                  <div className="text-[12px] font-mono text-zinc-700 dark:text-zinc-200 truncate">
                    {issue.text}
                  </div>
                  <div className="text-[10px] text-amber-500 mt-0.5">{issue.reason}</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Report sau khi clean */}
      {state.cleaned && state.report.length > 0 && (() => {
        const deletedCount = state.report.filter(r => r.action === 'delete').length
        const cleanedCount = state.report.filter(r => r.action === 'clean').length
        return (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-3">
              <div className="panel-label">Kết quả làm sạch — {state.report.length} dòng</div>
              <div className="flex items-center gap-2 text-[11px] text-zinc-500">
                {cleanedCount > 0 && (
                  <span className="px-2 py-0.5 rounded-full bg-emerald-50 dark:bg-emerald-950/30 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
                    ✏️ Sửa {cleanedCount}
                  </span>
                )}
                {deletedCount > 0 && (
                  <span className="px-2 py-0.5 rounded-full bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 border border-red-200 dark:border-red-800">
                    🗑️ Xóa {deletedCount}
                  </span>
                )}
              </div>
            </div>
            <div className="flex flex-col divide-y divide-zinc-100 dark:divide-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-xl overflow-hidden max-h-80 overflow-y-auto">
              {state.report.map((r, i) => {
                const isDelete = r.action === 'delete'
                return (
                  <div key={i} className="flex items-start gap-3 px-4 py-3 hover:bg-zinc-50 dark:hover:bg-zinc-800/30">
                    <span className="text-[10px] font-mono text-zinc-400 w-10 flex-shrink-0 pt-1">
                      #{r.index}
                    </span>
                    <div className="flex-1 min-w-0 flex flex-col gap-1.5">
                      {/* Header: badge action + lý do */}
                      <div className="flex items-center gap-2 flex-wrap">
                        {isDelete ? (
                          <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-red-100 dark:bg-red-950/40 text-red-700 dark:text-red-400 uppercase tracking-wider">
                            🗑️ Xóa
                          </span>
                        ) : (
                          <span className="px-1.5 py-0.5 text-[10px] font-bold rounded bg-emerald-100 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 uppercase tracking-wider">
                            ✏️ Sửa
                          </span>
                        )}
                        {r.reason && (
                          <span className="text-[10px] text-zinc-500 dark:text-zinc-400 italic">
                            {r.reason}
                          </span>
                        )}
                      </div>
                      {/* Body: before / after */}
                      <div className="flex flex-col gap-0.5">
                        <div className="text-[11px] font-mono text-zinc-400 line-through truncate" title={r.original}>
                          {r.original}
                        </div>
                        {isDelete ? (
                          <div className="text-[11px] text-red-500 font-mono italic">
                            → Đã xóa dòng này khỏi phụ đề
                          </div>
                        ) : (
                          <div className="text-[11px] text-emerald-600 dark:text-emerald-400 font-mono truncate" title={r.cleaned}>
                            → {r.cleaned}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
            {/* Thông báo về reindex nếu có xóa */}
            {deletedCount > 0 && (
              <div className="text-[11px] text-amber-600 dark:text-amber-400 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950/20 border border-amber-200 dark:border-amber-800">
                ⚠ Đã xóa {deletedCount} dòng → số thứ tự phụ đề đã được đánh lại từ đầu. Bible cũ (nếu có) đã bị xóa, cần chạy lại Pass 1.
              </div>
            )}
          </div>
        )
      })()}

      {/* Actions */}
      <div className="flex items-center gap-3 pt-2">
        <button onClick={onSkip} className="btn">
          Bỏ qua bước này →
        </button>
        {state.scanned && state.issues.length > 0 && !state.cleaned && (
          <button onClick={onClean} disabled={state.running}
            className="btn-primary disabled:opacity-60 gap-2">
            {state.running
              ? <><div className="w-3.5 h-3.5 rounded-full border-2 border-white border-t-transparent animate-spin" /> Đang làm sạch...</>
              : '✨ Làm sạch với AI'}
          </button>
        )}
        {(state.cleaned || state.issues.length === 0) && state.scanned && (
          <button onClick={onSkip} className="btn-primary">
            Tiếp theo → Phân tích phim
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Step 1: Pass 1 Bible ─────────────────────────────────────────────────────

const VAI_CLS: Record<string, string> = {
  nu_chinh:  'text-pink-500 bg-pink-50 dark:bg-pink-950/40 border-pink-200 dark:border-pink-800',
  nam_chinh: 'text-blue-500 bg-blue-50 dark:bg-blue-950/40 border-blue-200 dark:border-blue-800',
  phu:       'text-purple-500 bg-purple-50 dark:bg-purple-950/40 border-purple-200 dark:border-purple-800',
  phan_dien: 'text-red-500 bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-800',
}
const VAI_MAP: Record<string, string> = {
  nu_chinh: 'Nữ chính', nam_chinh: 'Nam chính', phu: 'Phụ', phan_dien: 'Phản diện',
}

function BibleSection({ bible }: { bible: Bible }) {
  const [bibleTab, setBibleTab] = useState<'chars' | 'story' | 'scenes' | 'terms' | 'raw'>('chars')
  const charCount  = bible.nhan_vat?.length || 0
  const sceneCount = bible.scene_map?.length || 0
  const termCount  = Object.keys(bible.thuat_ngu || {}).length

  return (
    <div className="flex flex-col gap-0 border border-zinc-200 dark:border-zinc-700 rounded-xl overflow-hidden">
      {/* Tab bar */}
      <div className="flex border-b border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/60">
        {([
          ['chars',  `👥 Nhân vật (${charCount})`],
          ['story',  '📖 Cốt truyện'],
          ['scenes', `🎬 Scene map (${sceneCount})`],
          ['terms',  `📝 Thuật ngữ (${termCount})`],
          ['raw',    '{ } JSON'],
        ] as const).map(([key, label]) => (
          <button key={key} onClick={() => setBibleTab(key)}
            className={`px-3 py-2 text-[11px] font-semibold border-b-2 transition-all -mb-px ${
              bibleTab === key
                ? 'border-blue-500 text-blue-600 dark:text-blue-400 bg-white dark:bg-zinc-900'
                : 'border-transparent text-zinc-400 hover:text-zinc-600'
            }`}>
            {label}
          </button>
        ))}
      </div>

      <div className="p-4 max-h-[50vh] overflow-y-auto">
        {/* Chars */}
        {bibleTab === 'chars' && (
          <div className="flex flex-col gap-2">
            {bible.the_loai && (
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 mb-2">
                <span className="text-[11px] font-bold text-amber-600 uppercase tracking-widest">
                  {bible.the_loai.boi_canh?.replace('_', ' ')}
                </span>
                {bible.the_loai.ghi_chu_dich && (
                  <span className="text-[11px] text-amber-600/70">— {bible.the_loai.ghi_chu_dich}</span>
                )}
              </div>
            )}
            {(bible.nhan_vat || []).map((c, i) => (
              <div key={i} className="flex items-start gap-3 px-3 py-2.5 rounded-lg bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-100 dark:border-zinc-700/50">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1">
                    <span className="text-[13px] font-bold">{c.vi}</span>
                    <span className="text-[11px] text-zinc-400 font-mono">{c.zh}</span>
                    <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded border ${VAI_CLS[c.vai] || 'text-zinc-500 bg-zinc-100 border-zinc-200'}`}>
                      {VAI_MAP[c.vai] || c.vai}
                    </span>
                  </div>
                  <div className="text-[11px] text-zinc-400">{c.than_phan}</div>
                  {c.tu_xung && (
                    <div className="text-[11px] text-zinc-500 mt-0.5">
                      Tự xưng: <span className="text-blue-500 font-semibold">{c.tu_xung}</span>
                    </div>
                  )}
                  {c.xung_ho && Object.keys(c.xung_ho).length > 0 && (
                    <div className="text-[10px] text-zinc-400 mt-1">
                      Gọi: {Object.entries(c.xung_ho).map(([k, v]) => `${k}→${v}`).join(' · ')}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Story */}
        {bibleTab === 'story' && (
          <div className="flex flex-col gap-3">
            <p className="text-[13px] text-zinc-600 dark:text-zinc-300 leading-relaxed">
              {bible.story_arc?.tom_tat_phim || 'Chưa có tóm tắt.'}
            </p>
            {(bible.quan_he_noi_bat || []).length > 0 && (
              <div>
                <div className="panel-label">Quan hệ nổi bật</div>
                <div className="flex flex-col gap-1">
                  {bible.quan_he_noi_bat!.map((r, i) => (
                    <div key={i} className="text-[12px] text-zinc-500 flex items-center gap-2">
                      <span className="text-zinc-300">·</span>{r}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Scenes */}
        {bibleTab === 'scenes' && (
          <div className="flex flex-col gap-2">
            {(bible.scene_map || []).map((scene, i) => (
              <div key={i} className="px-3 py-2.5 rounded-lg border border-zinc-100 dark:border-zinc-700/50 bg-zinc-50 dark:bg-zinc-800/60">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-mono text-zinc-400">#{i + 1}</span>
                  <span className="text-[10px] font-mono text-blue-500">
                    dòng {scene.tu_dong}–{scene.den_dong}
                  </span>
                  <span className="text-[10px] text-zinc-400 ml-auto">
                    {scene.den_dong - scene.tu_dong + 1} dòng
                  </span>
                </div>
                <div className="text-[12px] text-zinc-600 dark:text-zinc-300 leading-snug">
                  {scene.tom_tat}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Terms */}
        {bibleTab === 'terms' && (
          <div className="flex flex-col gap-1.5">
            {Object.entries(bible.thuat_ngu || {}).map(([zh, vi]) => (
              <div key={zh} className="flex items-center gap-3 px-3 py-1.5 rounded-lg bg-zinc-50 dark:bg-zinc-800/60 text-[12px]">
                <span className="text-zinc-400 font-mono flex-1">{zh}</span>
                <span className="text-zinc-300 dark:text-zinc-600">→</span>
                <span className="font-semibold text-zinc-700 dark:text-zinc-200">{vi}</span>
              </div>
            ))}
            {termCount === 0 && (
              <p className="text-zinc-400 text-[12px] text-center py-4">Không có thuật ngữ đặc thù</p>
            )}
          </div>
        )}

        {/* Raw JSON — với nút Copy & Download */}
        {bibleTab === 'raw' && (() => {
          const jsonStr = JSON.stringify(bible, null, 2)
          const sizeKB  = (new Blob([jsonStr]).size / 1024).toFixed(1)
          const lineCount = jsonStr.split('\n').length
          return (
            <div className="flex flex-col gap-2">
              {/* Toolbar */}
              <div className="flex items-center gap-2 px-2 py-1.5 bg-zinc-100 dark:bg-zinc-800/50 rounded-lg">
                <span className="text-[11px] text-zinc-500 font-mono">
                  {lineCount.toLocaleString()} dòng · {sizeKB} KB
                </span>
                <div className="flex-1" />
                <button
                  onClick={async () => {
                    try {
                      await navigator.clipboard.writeText(jsonStr)
                      const btn = document.activeElement as HTMLButtonElement
                      if (btn) {
                        const orig = btn.innerText
                        btn.innerText = '✓ Đã copy'
                        setTimeout(() => { btn.innerText = orig }, 1500)
                      }
                    } catch {
                      alert('Không copy được. Vui lòng dùng Download.')
                    }
                  }}
                  className="px-3 py-1 text-[11px] font-medium rounded bg-blue-500 hover:bg-blue-600 text-white transition-colors"
                >
                  📋 Copy JSON
                </button>
                <button
                  onClick={() => {
                    const blob = new Blob([jsonStr], { type: 'application/json' })
                    const url  = URL.createObjectURL(blob)
                    const a    = document.createElement('a')
                    a.href     = url
                    a.download = `bible_${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.json`
                    document.body.appendChild(a)
                    a.click()
                    document.body.removeChild(a)
                    URL.revokeObjectURL(url)
                  }}
                  className="px-3 py-1 text-[11px] font-medium rounded border border-zinc-300 dark:border-zinc-600 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-300 transition-colors"
                >
                  ⬇ Download
                </button>
              </div>
              {/* JSON content */}
              <pre className="text-[10px] font-mono text-zinc-600 dark:text-zinc-300 leading-relaxed whitespace-pre-wrap break-all bg-zinc-50 dark:bg-zinc-900/50 p-3 rounded-lg border border-zinc-200 dark:border-zinc-700 max-h-[60vh] overflow-y-auto select-all">
                {jsonStr}
              </pre>
            </div>
          )
        })()}
      </div>
    </div>
  )
}

function Step1ProgressItem({
  stepNo, label, icon, status, detail,
}: {
  stepNo: number
  label: string
  icon: string
  status: 'wait' | 'running' | 'done'
  detail: string
}) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-white dark:bg-zinc-900/50 border border-blue-100 dark:border-blue-900">
      {/* Status indicator */}
      <div className="flex-shrink-0 w-6 h-6 flex items-center justify-center">
        {status === 'wait' && (
          <div className="w-5 h-5 rounded-full border-2 border-zinc-200 dark:border-zinc-700 flex items-center justify-center">
            <span className="text-[10px] font-bold text-zinc-400">{stepNo}</span>
          </div>
        )}
        {status === 'running' && (
          <div className="w-5 h-5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
        )}
        {status === 'done' && (
          <div className="w-5 h-5 rounded-full bg-emerald-500 flex items-center justify-center">
            <span className="text-[11px] text-white font-bold">✓</span>
          </div>
        )}
      </div>

      {/* Label + detail */}
      <span className="text-base flex-shrink-0">{icon}</span>
      <div className="flex-1 min-w-0">
        <div className={`text-[12px] font-semibold ${
          status === 'done'    ? 'text-emerald-600 dark:text-emerald-400'
          : status === 'running' ? 'text-blue-600 dark:text-blue-400'
          : 'text-zinc-400'
        }`}>
          Bước {stepNo}/2: {label}
        </div>
        {detail && (
          <div className="text-[11px] text-zinc-500 dark:text-zinc-400 truncate">
            {detail}
          </div>
        )}
      </div>
    </div>
  )
}

// ─── DiarizePanel ────────────────────────────────────────────────────────────
// Step 1: Gán speaker bằng Diarization (Pyannote)
// Pipeline backend đã có: cut audio → diarize → tạo Character SPEAKER_00...
//                         → gán subtitle.character_id
// UI này tận dụng endpoint /projects/{id}/auto-assign/*

interface DiarizeJob {
  status:        'idle' | 'running' | 'done' | 'error' | 'cancelled'
  progress:      number
  total_lines:   number
  done_lines:    number
  speaker_count: number
  logs:          string[]
  error?:        string
}

const EMPTY_DIARIZE_JOB: DiarizeJob = {
  status: 'idle', progress: 0,
  total_lines: 0, done_lines: 0, speaker_count: 0, logs: [],
}

interface SrtRow {
  index:   number
  speaker: string
  text:    string
}

function DiarizePanel({
  projectId, hasVideo, onSkip, onDone,
}: {
  projectId: number
  hasVideo:  boolean
  onSkip:    () => void
  onDone:    () => void
}) {
  const [job,        setJob]        = useState<DiarizeJob>(EMPTY_DIARIZE_JOB)
  const [minSpk,     setMinSpk]     = useState(2)
  const [maxSpk,     setMaxSpk]     = useState(15)
  const [useDemucs,  setUseDemucs]  = useState(false)
  const [starting,   setStarting]   = useState(false)
  const [srtPreview, setSrtPreview] = useState<{
    rows:    SrtRow[]
    stats:   Record<string, number>
    content: string
  } | null>(null)
  const [previewLoading, setPreviewLoading] = useState(false)
  const logRef  = useRef<HTMLDivElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Auto-scroll log
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight
  }, [job.logs])

  // Fetch status
  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get(`/projects/${projectId}/auto-assign/status`)
      const d = res.data
      setJob({
        status:        d.status,
        progress:      d.progress       || 0,
        total_lines:   d.total_lines    || 0,
        done_lines:    d.done_lines     || 0,
        speaker_count: d.speaker_count  || 0,
        logs:          d.logs           || [],
        error:         d.error,
      })
      return d.status
    } catch (err: any) {
      if (err.response?.status === 404) return 'idle'
      return null
    }
  }, [projectId])

  // Polling khi running
  const startPolling = useCallback(() => {
    if (pollRef.current) return
    pollRef.current = setInterval(async () => {
      const status = await fetchStatus()
      if (status !== 'running') {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
        if (status === 'done') {
          // Tự load preview khi xong
          await loadPreview()
          onDone()
        }
      }
    }, 1500)
  }, [fetchStatus])

  // Load SRT preview (có speaker)
  const loadPreview = useCallback(async () => {
    setPreviewLoading(true)
    try {
      const res = await api.get(`/projects/${projectId}/translate/srt-with-speakers`)
      setSrtPreview({
        rows:    [],  // build sau từ content nếu cần
        stats:   res.data.stats || {},
        content: res.data.content || '',
      })
    } catch (err) {
      console.error('Load preview lỗi:', err)
    } finally {
      setPreviewLoading(false)
    }
  }, [projectId])

  // Init: check status
  useEffect(() => {
    fetchStatus().then(status => {
      if (status === 'running') startPolling()
      else if (status === 'done') loadPreview()  // Đã chạy xong → load preview
    })
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [])

  // Start
  const handleStart = async () => {
    if (!hasVideo) {
      alert('Project chưa có video. Upload video trong Editor trước.')
      return
    }
    setStarting(true)
    try {
      await api.post(`/projects/${projectId}/auto-assign/start`, {
        project_id:   projectId,
        batch_size:   50,
        min_speakers: minSpk,
        max_speakers: maxSpk,
        match_existing: true,
        use_demucs:   useDemucs,
      })
      setJob(j => ({ ...j, status: 'running', logs: [] }))
      startPolling()
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Không khởi động được Diarization')
    } finally {
      setStarting(false)
    }
  }

  // Cancel
  const handleCancel = async () => {
    try {
      await api.post(`/projects/${projectId}/auto-assign/cancel`)
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
      setJob(j => ({ ...j, status: 'cancelled' }))
    } catch (err) {}
  }

  // Reset
  const handleReset = async () => {
    if (!confirm('Reset Diarization? Sẽ xóa speaker đã gán và bắt đầu lại.')) return
    try {
      await api.delete(`/projects/${projectId}/auto-assign/reset`)
      setJob(EMPTY_DIARIZE_JOB)
      setSrtPreview(null)
    } catch (err) {}
  }

  // Copy SRT preview
  const handleCopy = async () => {
    if (!srtPreview) return
    try {
      await navigator.clipboard.writeText(srtPreview.content)
      alert('Đã copy SRT có speaker vào clipboard')
    } catch {
      alert('Copy thất bại. Dùng Download.')
    }
  }

  // Download SRT preview
  const handleDownload = () => {
    if (!srtPreview) return
    const blob = new Blob([srtPreview.content], { type: 'text/plain;charset=utf-8' })
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href     = url
    a.download = `srt_speakers_${projectId}_${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.txt`
    document.body.appendChild(a); a.click(); document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  return (
    <div className="flex flex-col gap-4 p-6 max-w-4xl mx-auto w-full">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[15px] font-bold text-zinc-800 dark:text-zinc-100 mb-1">
            Gán speaker — Diarization
          </div>
          <div className="text-[12px] text-zinc-400">
            Pyannote nhận diện giọng nói trong video · gán mỗi dòng phụ đề với SPEAKER_00, SPEAKER_01...
          </div>
        </div>
        {job.status === 'idle' && (
          <button onClick={onSkip} className="btn text-[12px]">
            Bỏ qua bước này →
          </button>
        )}
        {job.status === 'done' && (
          <div className="flex items-center gap-2">
            <button onClick={handleReset} className="btn text-[12px]">
              🔄 Chạy lại
            </button>
            <button onClick={onDone} className="btn-primary text-[12px]">
              Tiếp theo → Phân tích
            </button>
          </div>
        )}
      </div>

      {!hasVideo && (
        <div className="p-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 text-[12px] text-amber-700 dark:text-amber-400">
          ⚠ Project chưa có video. Hãy upload video trong Editor trước khi chạy Diarization.
        </div>
      )}

      {/* Cấu hình (chỉ hiện khi idle) */}
      {job.status === 'idle' && hasVideo && (
        <div className="flex flex-col gap-3 p-4 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50/50 dark:bg-zinc-900/30">
          <div className="text-[12px] font-semibold text-zinc-700 dark:text-zinc-300">
            Cấu hình Diarization
          </div>
          <div className="flex items-center gap-6 flex-wrap">
            <label className="flex items-center gap-2 text-[12px]">
              <span className="text-zinc-500">Tối thiểu speaker:</span>
              <input type="number" min={1} max={20} value={minSpk}
                onChange={e => setMinSpk(Math.max(1, +e.target.value))}
                className="w-16 px-2 py-1 rounded border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800" />
            </label>
            <label className="flex items-center gap-2 text-[12px]">
              <span className="text-zinc-500">Tối đa speaker:</span>
              <input type="number" min={2} max={30} value={maxSpk}
                onChange={e => setMaxSpk(Math.max(2, +e.target.value))}
                className="w-16 px-2 py-1 rounded border border-zinc-300 dark:border-zinc-600 bg-white dark:bg-zinc-800" />
            </label>
            <label className="flex items-center gap-2 text-[12px] cursor-pointer">
              <input type="checkbox" checked={useDemucs}
                onChange={e => setUseDemucs(e.target.checked)} />
              <span className="text-zinc-500">Demucs tách vocals trước (chậm hơn, chính xác hơn cho phim có nhạc nền)</span>
            </label>
          </div>
          <button onClick={handleStart} disabled={starting}
            className="btn-primary self-start gap-2">
            {starting ? '⏳ Đang khởi động...' : '🎙️ Bắt đầu Diarization'}
          </button>
        </div>
      )}

      {/* Running state */}
      {job.status === 'running' && (
        <div className="flex flex-col gap-3 p-4 rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/20">
          <div className="flex items-center gap-3">
            <div className="w-3.5 h-3.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
            <span className="text-[13px] font-semibold text-blue-700 dark:text-blue-300">
              Đang chạy... {job.progress}%
            </span>
            <span className="ml-auto text-[11px] text-blue-400">
              {job.done_lines}/{job.total_lines} dòng
            </span>
            <button onClick={handleCancel} className="btn text-[11px] text-red-500 border-red-200 dark:border-red-800">
              Hủy
            </button>
          </div>
          {/* Progress bar */}
          <div className="h-1.5 rounded-full bg-blue-100 dark:bg-blue-900 overflow-hidden">
            <div className="h-full bg-blue-500 rounded-full transition-all"
              style={{ width: `${job.progress}%` }} />
          </div>
          {/* Log */}
          <div ref={logRef}
            className="max-h-40 overflow-y-auto bg-white dark:bg-zinc-900/50 rounded p-2 text-[10px] font-mono text-zinc-600 dark:text-zinc-400 leading-relaxed">
            {job.logs.length === 0 && <div className="text-zinc-400 italic">Đang khởi động...</div>}
            {job.logs.map((line, i) => <div key={i}>{line}</div>)}
          </div>
          <p className="text-[11px] text-blue-500 dark:text-blue-400">
            Pipeline: Cắt audio → Demucs (nếu bật) → Pyannote diarize → Match SRT → Gán DB
          </p>
        </div>
      )}

      {/* Error */}
      {job.status === 'error' && (
        <div className="p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-[12px] text-red-500 font-mono">
          ❌ {job.error || 'Lỗi không xác định'}
          <button onClick={handleReset} className="btn text-[11px] ml-3">Thử lại</button>
        </div>
      )}

      {/* Cancelled */}
      {job.status === 'cancelled' && (
        <div className="p-3 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-[12px] text-zinc-500">
          Đã hủy.
          <button onClick={handleReset} className="btn text-[11px] ml-3">Chạy lại</button>
        </div>
      )}

      {/* Done - Stats + Preview SRT */}
      {job.status === 'done' && (
        <>
          <div className="flex items-center gap-4 px-4 py-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800 text-[12px]">
            <span className="text-emerald-600 font-semibold">✅ Diarization xong</span>
            <span className="text-zinc-400">·</span>
            <span className="text-zinc-700 dark:text-zinc-300">
              {job.speaker_count} speakers · {job.done_lines}/{job.total_lines} dòng đã gán
            </span>
          </div>

          {/* Preview SRT có speaker */}
          {srtPreview && (
            <div className="flex flex-col gap-2 border border-zinc-200 dark:border-zinc-700 rounded-xl overflow-hidden">
              {/* Toolbar */}
              <div className="flex items-center gap-2 px-3 py-2 bg-zinc-50 dark:bg-zinc-800/60 border-b border-zinc-200 dark:border-zinc-700">
                <div className="text-[12px] font-semibold text-zinc-700 dark:text-zinc-300">
                  SRT có speaker
                </div>
                <div className="flex items-center gap-1.5 ml-2">
                  {Object.entries(srtPreview.stats).map(([spk, count]) => (
                    <span key={spk}
                      className={`px-2 py-0.5 text-[10px] font-mono rounded-full ${
                        spk === '?'
                          ? 'bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400'
                          : 'bg-blue-100 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400'
                      }`}>
                      {spk}: {count}
                    </span>
                  ))}
                </div>
                <div className="flex-1" />
                <button onClick={handleCopy} className="btn text-[11px] gap-1">
                  📋 Copy
                </button>
                <button onClick={handleDownload} className="btn text-[11px] gap-1">
                  ⬇ Download .txt
                </button>
              </div>
              {/* Preview */}
              <pre className="text-[11px] font-mono text-zinc-700 dark:text-zinc-300 leading-relaxed p-3 bg-white dark:bg-zinc-900/50 max-h-[50vh] overflow-y-auto whitespace-pre-wrap">
                {previewLoading ? 'Đang tải...' : (srtPreview.content || '(rỗng)')}
              </pre>
            </div>
          )}
          {!srtPreview && !previewLoading && (
            <button onClick={loadPreview} className="btn self-start text-[12px]">
              📋 Hiển thị SRT có speaker
            </button>
          )}
        </>
      )}
    </div>
  )
}

// ─── Pass2SpeakerPanel ───────────────────────────────────────────────────────
// Step 3: AI gán speaker chính thức (quyết định cuối).
// AI dùng SPEAKER_XX từ Diarization làm gợi ý, nhưng quyết định dựa vào content.

function Pass2SpeakerPanel({
  state, modelLabel, hasBible, onRun, onSkip,
}: {
  state:      Pass2SpeakerState
  modelLabel: string
  hasBible:   boolean
  onRun:      () => void
  onSkip:     () => void
}) {
  const [elapsed, setElapsed] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (state.running) {
      setElapsed(0)
      timerRef.current = setInterval(() => setElapsed(e => e + 100), 100)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [state.running])

  const progressPct = state.totalScenes > 0
    ? Math.round((state.doneScenes / state.totalScenes) * 100)
    : 0

  return (
    <div className="flex flex-col gap-4 p-6 max-w-4xl mx-auto w-full">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[15px] font-bold text-zinc-800 dark:text-zinc-100 mb-1">
            Gán speaker — AI quyết định cuối (Pass 2)
          </div>
          <div className="text-[12px] text-zinc-400">
            AI đọc nội dung thoại + gợi ý từ Diarization → quyết định CUỐI ai nói câu nào.
            Sau bước này, mỗi dòng được gán speaker chính xác để Pass 3 dịch + xưng hô đúng.
          </div>
        </div>
        {state.done && (
          <button onClick={onSkip} className="btn-primary text-[12px]">
            Tiếp theo → Dịch thuật
          </button>
        )}
      </div>

      {!hasBible && (
        <div className="p-3 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800 text-[12px] text-amber-700 dark:text-amber-400">
          ⚠ Chưa có Bible. Hãy chạy Pass 1 (Phân tích) trước.
        </div>
      )}

      {/* Idle: nút run */}
      {!state.running && !state.done && hasBible && (
        <div className="flex flex-col gap-3 p-4 rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50/50 dark:bg-zinc-900/30">
          <div className="text-[12px] text-zinc-600 dark:text-zinc-300">
            Pass 2 sẽ chạy SONG SONG theo từng <strong>đoạn kịch bản</strong> (scene). Mỗi scene 1 API call,
            AI nhận:
          </div>
          <ul className="text-[11px] text-zinc-500 dark:text-zinc-400 pl-4 list-disc space-y-0.5">
            <li>Danh sách nhân vật trong scene (từ Bible)</li>
            <li>SRT của scene có sẵn SPEAKER_XX từ Diarization</li>
            <li>Speaker mapping summary (SPEAKER_XX ↔ tên nhân vật)</li>
          </ul>
          <div className="text-[12px] text-zinc-600 dark:text-zinc-300 mt-1">
            AI quyết định cuối → backend cập nhật <code className="text-[11px] bg-zinc-200 dark:bg-zinc-800 px-1 rounded">subtitle.character_id</code>
          </div>
          <button onClick={onRun}
            className="btn-primary self-start gap-2 mt-1">
            🎯 Bắt đầu gán speaker
          </button>
        </div>
      )}

      {/* Running */}
      {state.running && (
        <div className="flex flex-col gap-3 p-4 rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/20">
          <div className="flex items-center gap-3">
            <div className="w-3.5 h-3.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin flex-shrink-0" />
            <span className="text-[13px] font-semibold text-blue-700 dark:text-blue-300">
              Đang chạy: {state.doneScenes}/{state.totalScenes} scene ({progressPct}%)
            </span>
            <span className="ml-auto text-[12px] font-mono text-blue-400">
              ⏱ {(elapsed / 1000).toFixed(1)}s
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-blue-100 dark:bg-blue-900 overflow-hidden">
            <div className="h-full bg-blue-500 rounded-full transition-all"
              style={{ width: `${progressPct}%` }} />
          </div>
          <p className="text-[11px] text-blue-500 dark:text-blue-400">
            {state.stageMessage || `Pass 2 chạy song song theo scene (concurrency=3) · Model: ${modelLabel}`}
          </p>
        </div>
      )}

      {/* Error */}
      {state.error && (
        <div className="p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-[12px] text-red-500 font-mono whitespace-pre-wrap">
          ❌ {state.error}
        </div>
      )}

      {/* Done */}
      {state.done && (
        <div className="flex flex-col gap-3">
          <div className="flex items-center gap-4 px-4 py-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800 text-[12px]">
            <span className="text-emerald-600 font-semibold">✅ Pass 2 xong</span>
            <span className="text-zinc-400">·</span>
            <span className="text-zinc-700 dark:text-zinc-300">
              {state.total} dòng · {state.updated} cập nhật · {state.unknown} không xác định
            </span>
            <span className="text-zinc-400">·</span>
            <span className="font-mono text-blue-500">↑ {fmtTokens(state.tokensIn)} in</span>
            <span className="font-mono text-emerald-500">↓ {fmtTokens(state.tokensOut)} out</span>
            <span className="text-zinc-400">·</span>
            <span className="text-zinc-500">{fmt(state.timingMs)}</span>
          </div>
          <div className="text-[11px] text-zinc-500 dark:text-zinc-400 px-1">
            Mỗi subtitle giờ có speaker chính xác do AI quyết định. Pass 3 sẽ dùng speaker này để dịch + xưng hô đúng.
          </div>
        </div>
      )}
    </div>
  )
}

function Step1Panel({
  state, modelLabel, totalSubs, onRun, onRerun,
}: {
  state: Pass1State
  modelLabel: string
  totalSubs: number
  onRun: () => void
  onRerun: () => void
}) {
  const [elapsed, setElapsed] = useState(0)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  useEffect(() => {
    if (state.running) {
      setElapsed(0)
      timerRef.current = setInterval(() => setElapsed(e => e + 100), 100)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [state.running])

  return (
    <div className="flex flex-col gap-4 p-6 max-w-4xl mx-auto w-full">
      <div className="flex items-start justify-between">
        <div>
          <div className="text-[15px] font-bold text-zinc-800 dark:text-zinc-100 mb-1">
            Phân tích phim — Pass 1
          </div>
          <div className="text-[12px] text-zinc-400">
            Gửi toàn bộ {totalSubs} dòng phụ đề · AI xây Bible (nhân vật, xưng hô, scene_map)
          </div>
        </div>
        {!state.running && !state.done && (
          <button onClick={onRun} className="btn-primary gap-2 flex-shrink-0">
            🔍 Bắt đầu phân tích
          </button>
        )}
        {state.done && (
          <button onClick={onRerun} className="btn flex-shrink-0 text-purple-500 border-purple-200 dark:border-purple-800">
            🔄 Phân tích lại
          </button>
        )}
      </div>

      {/* Running state — 2 bước Pass 1A + Pass 1B */}
      {state.running && (
        <div className="flex flex-col gap-3 p-5 rounded-xl border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/20">
          <div className="flex items-center gap-3">
            <span className="text-[13px] font-semibold text-blue-700 dark:text-blue-300">
              Đang phân tích {totalSubs} dòng với {modelLabel}
            </span>
            <span className="ml-auto text-[12px] font-mono text-blue-400">
              ⏱ {(elapsed / 1000).toFixed(1)}s
            </span>
          </div>

          {/* 2 bước — mỗi bước có icon, label, sub-message, time */}
          <div className="flex flex-col gap-2 mt-1">
            {/* Bước 1A */}
            <Step1ProgressItem
              stepNo={1}
              label="Phân tích nhân vật & xưng hô"
              icon="🧑"
              status={
                state.stage === 'pass1a' ? 'running'
                : (state.pass1aStats || state.stage === 'pass1b' || state.stage === 'merging' || state.stage === 'done') ? 'done'
                : 'wait'
              }
              detail={
                state.pass1aStats
                  ? `${state.pass1aStats.nhan_vat} nhân vật · ${(state.pass1aStats.time_ms / 1000).toFixed(1)}s`
                  : (state.stage === 'pass1a' ? state.stageMessage : '')
              }
            />

            {/* Bước 1B */}
            <Step1ProgressItem
              stepNo={2}
              label="Phân tích cốt truyện & phân đoạn"
              icon="🎬"
              status={
                state.stage === 'pass1b' ? 'running'
                : (state.pass1bStats || state.stage === 'merging' || state.stage === 'done') ? 'done'
                : 'wait'
              }
              detail={
                state.pass1bStats
                  ? `${state.pass1bStats.scene_count} đoạn · ${(state.pass1bStats.time_ms / 1000).toFixed(1)}s`
                  : (state.stage === 'pass1b' ? state.stageMessage : '')
              }
            />
          </div>

          <p className="text-[11px] text-blue-500 dark:text-blue-400 mt-1">
            Pass 1 thường mất 60-120s tuỳ độ dài phim. Không đóng tab này.
          </p>
        </div>
      )}

      {/* Error */}
      {state.error && (
        <div className="p-3 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-[12px] text-red-500 font-mono">
          ❌ {state.error}
        </div>
      )}

      {/* Done — stats tổng + chi tiết 2 pass */}
      {state.done && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-4 px-4 py-3 rounded-lg bg-emerald-50 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800 text-[12px]">
            <span className="text-emerald-600 font-semibold">✅ Phân tích xong</span>
            <span className="text-zinc-400">·</span>
            <span className="font-mono text-blue-500">↑ {fmtTokens(state.tokensIn)} in</span>
            <span className="font-mono text-emerald-500">↓ {fmtTokens(state.tokensOut)} out</span>
            <span className="text-zinc-400">·</span>
            <span className="text-zinc-500">{fmt(state.timingMs)}</span>
            <span className="text-zinc-400 ml-auto">Model: <span className="font-mono">{modelLabel}</span></span>
          </div>
          {/* Chi tiết 2 pass */}
          {(state.pass1a || state.pass1b) && (
            <div className="flex items-center gap-2 text-[11px]">
              {state.pass1a && (
                <span className="px-2 py-1 rounded-md bg-blue-50 dark:bg-blue-950/20 border border-blue-100 dark:border-blue-900 text-blue-600 dark:text-blue-400">
                  🧑 Pass 1A: ↑{fmtTokens(state.pass1a.tokens_in)} ↓{fmtTokens(state.pass1a.tokens_out)} · {fmt(state.pass1a.timing_ms)}
                </span>
              )}
              {state.pass1b && (
                <span className="px-2 py-1 rounded-md bg-purple-50 dark:bg-purple-950/20 border border-purple-100 dark:border-purple-900 text-purple-600 dark:text-purple-400">
                  🎬 Pass 1B: ↑{fmtTokens(state.pass1b.tokens_in)} ↓{fmtTokens(state.pass1b.tokens_out)} · {fmt(state.pass1b.timing_ms)}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* Bible */}
      {state.bible && <BibleSection bible={state.bible} />}

      {/* API Call detail — Pass 1A & Pass 1B */}
      {state.done && (state.pass1a || state.pass1b) && (
        <Pass1ApiCallSection pass1a={state.pass1a} pass1b={state.pass1b} />
      )}

      {/* Empty state */}
      {!state.running && !state.done && !state.error && (
        <div className="flex items-center justify-center py-16 text-zinc-400 text-[13px]">
          Bấm "Bắt đầu phân tích" để AI đọc toàn bộ phim và xây dựng Bible.
        </div>
      )}
    </div>
  )
}

// ─── Pass1ApiCallSection ─────────────────────────────────────────────────────
// Hiển thị prompt + response của Pass 1A và Pass 1B để debug khi cần.
// Có nút Copy + Download cho từng phần.

function Pass1ApiCallSection({
  pass1a, pass1b,
}: {
  pass1a: Pass1SubResult | null
  pass1b: Pass1SubResult | null
}) {
  const [activeTab, setActiveTab] = useState<'1a' | '1b'>('1a')
  const [section,   setSection]   = useState<'prompt' | 'response'>('response')

  const current = activeTab === '1a' ? pass1a : pass1b
  if (!current) return null

  const content = section === 'prompt' ? current.prompt : current.response
  const sizeKB = (new Blob([content]).size / 1024).toFixed(1)
  const lineCount = content.split('\n').length

  return (
    <div className="flex flex-col gap-0 border border-zinc-200 dark:border-zinc-700 rounded-xl overflow-hidden mt-2">
      {/* Tab bar — chọn Pass 1A hay 1B */}
      <div className="flex border-b border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/60">
        {(['1a', '1b'] as const).map(key => {
          const sub = key === '1a' ? pass1a : pass1b
          if (!sub) return null
          const label = key === '1a' ? '🧑 Pass 1A — Nhân vật' : '🎬 Pass 1B — Scene map'
          return (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`px-4 py-2 text-[12px] font-semibold border-b-2 transition-all -mb-px ${
                activeTab === key
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400 bg-white dark:bg-zinc-900'
                  : 'border-transparent text-zinc-400 hover:text-zinc-600'
              }`}
            >
              {label}
            </button>
          )
        })}
        <div className="flex-1" />
        {/* Stats */}
        <div className="flex items-center gap-3 px-4 text-[11px] font-mono text-zinc-500">
          <span className="text-blue-500">↑ {fmtTokens(current.tokens_in)}</span>
          <span className="text-emerald-500">↓ {fmtTokens(current.tokens_out)}</span>
          <span className="text-zinc-400">{fmt(current.timing_ms)}</span>
        </div>
      </div>

      {/* Sub-tab Prompt/Response */}
      <div className="flex items-center gap-2 px-3 py-2 bg-zinc-50 dark:bg-zinc-800/30 border-b border-zinc-200 dark:border-zinc-700">
        {(['response', 'prompt'] as const).map(s => (
          <button
            key={s}
            onClick={() => setSection(s)}
            className={`px-3 py-1 text-[11px] font-medium rounded transition-colors ${
              section === s
                ? 'bg-blue-500 text-white'
                : 'text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 hover:bg-zinc-200 dark:hover:bg-zinc-700'
            }`}
          >
            {s === 'response' ? '📥 Response' : '📤 Prompt'}
          </button>
        ))}
        <span className="text-[11px] text-zinc-400 ml-2">
          {lineCount.toLocaleString()} dòng · {sizeKB} KB
        </span>
        <div className="flex-1" />
        <button
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(content)
              const btn = document.activeElement as HTMLButtonElement
              if (btn) {
                const orig = btn.innerText
                btn.innerText = '✓ Đã copy'
                setTimeout(() => { btn.innerText = orig }, 1500)
              }
            } catch {
              alert('Không copy được. Dùng Download.')
            }
          }}
          className="px-3 py-1 text-[11px] font-medium rounded bg-blue-500 hover:bg-blue-600 text-white transition-colors"
        >
          📋 Copy
        </button>
        <button
          onClick={() => {
            const blob = new Blob([content], { type: 'text/plain' })
            const url  = URL.createObjectURL(blob)
            const a    = document.createElement('a')
            a.href     = url
            a.download = `pass${activeTab}_${section}_${new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')}.txt`
            document.body.appendChild(a)
            a.click()
            document.body.removeChild(a)
            URL.revokeObjectURL(url)
          }}
          className="px-3 py-1 text-[11px] font-medium rounded border border-zinc-300 dark:border-zinc-600 hover:bg-zinc-200 dark:hover:bg-zinc-700 text-zinc-700 dark:text-zinc-300 transition-colors"
        >
          ⬇ Download
        </button>
      </div>

      {/* Content */}
      <pre className="text-[10px] font-mono text-zinc-600 dark:text-zinc-300 leading-relaxed whitespace-pre-wrap break-all bg-zinc-50 dark:bg-zinc-900/50 p-3 max-h-[50vh] overflow-y-auto select-all">
        {content || '(rỗng)'}
      </pre>
    </div>
  )
}

// ─── QCReviewPanel ────────────────────────────────────────────────────────────

interface QCEntry {
  index: number
  original: string
  translated: string
  speaker?: string
  fixed?: string
  issue?: string
  // Pass 4 v2 fields
  loai_loi?:                 string  // speaker|van_phong|xung_ho|ten_nhan_vat|thuat_ngu|cuong_do|literal
  speaker_hien_tai?:         string
  speaker_de_xuat?:          string
  speaker_de_xuat_char_id?:  number | null
  bang_chung?:               string
  do_tin_cay?:               'cao' | 'trung' | 'thap' | ''
}

const LOAI_LOI_LABEL: Record<string, string> = {
  speaker:      '👤 Speaker',
  van_phong:    '✍️ Văn phong',
  xung_ho:      '🗣 Xưng hô',
  ten_nhan_vat: '🏷 Tên',
  thuat_ngu:    '📖 Thuật ngữ',
  cuong_do:     '🌡 Cường độ',
  literal:      '📝 Literal',
}

const TIN_CAY_LABEL: Record<string, { label: string; cls: string }> = {
  cao:   { label: '🟢 cao',   cls: 'text-emerald-600 dark:text-emerald-400' },
  trung: { label: '🟡 trung', cls: 'text-amber-600 dark:text-amber-400' },
  thap:  { label: '🔴 thấp',  cls: 'text-zinc-400' },
}

function QCReviewPanel({
  chunk, projectId, bible, apiKey, model, onApplyFixes, onQCDone,
}: {
  chunk: ChunkState
  projectId: number
  bible: Bible | null
  apiKey: string
  model: string
  onApplyFixes: (chunkIndex: number, entries: ChunkState['entries']) => void
  onQCDone: (chunkIndex: number, info: { tokensIn: number; tokensOut: number; timingMs: number; model: string }) => void
}) {
  const [running,     setRunning]     = useState(false)
  const [result,      setResult]      = useState<QCEntry[]>([])
  const [appliedSet,  setAppliedSet]  = useState<Set<number>>(new Set())  // index dòng đã apply
  const [rawResponse, setRawResponse] = useState('')
  const [tongKet,     setTongKet]     = useState<any>(null)
  const [error,       setError]       = useState('')
  const [elapsed,     setElapsed]     = useState(0)
  // Progress feedback từ SSE
  const [qcStage,     setQcStage]     = useState<string>('')   // qc_start | qc_calling | qc_retrying | qc_responding | qc_done | qc_error
  const [qcMessage,   setQcMessage]   = useState<string>('')
  const [qcEta,       setQcEta]       = useState<number>(0)
  // restoredFromDb=true → kết quả đang hiển thị là từ DB snapshot (chunk chuyển trước đó),
  // FE hiển thị badge "📌 Đã lưu" thay vì coi như vừa chạy.
  const [restoredFromDb, setRestoredFromDb] = useState(false)
  const timerRef = React.useRef<ReturnType<typeof setInterval> | null>(null)
  const sseRef = React.useRef<EventSource | null>(null)

  // Restore QC snapshot từ DB khi user chuyển sang chunk (hoặc mount lần đầu).
  // chunk.qcVanDe là JSON array đã được loadProject() đọc từ /translate/chunks endpoint.
  useEffect(() => {
    // Reset state về clean trước
    setRunning(false); setError(''); setQcStage(''); setQcMessage(''); setQcEta(0)
    setAppliedSet(new Set())

    const savedVanDe = chunk.qcVanDe
    if (Array.isArray(savedVanDe) && savedVanDe.length > 0) {
      // Có snapshot QC trong DB → restore. Map các vấn đề lưu trong DB về dạng QCEntry,
      // ghép thêm các dòng không có vấn đề (lấy từ chunk.entries) để bảng đầy đủ.
      const issueByIdx: Record<number, any> = {}
      savedVanDe.forEach((v: any) => { issueByIdx[v.index] = v })

      const restored: QCEntry[] = chunk.entries.map(e => {
        const v = issueByIdx[e.index]
        if (!v) {
          return {
            index:                    e.index,
            original:                 e.original,
            translated:               e.translated,
            speaker:                  e.speaker || '',
            fixed:                    e.translated,
            issue:                    '',
            loai_loi:                 '',
            speaker_hien_tai:         e.speaker || '',
            speaker_de_xuat:          '',
            speaker_de_xuat_char_id:  null,
            bang_chung:               '',
            do_tin_cay:               '',
          }
        }
        return {
          index:                    v.index,
          original:                 v.original || e.original,
          translated:               v.translated || e.translated,
          speaker:                  v.speaker || e.speaker || '',
          fixed:                    v.fixed || e.translated,
          issue:                    v.issue || '',
          loai_loi:                 v.loai_loi || '',
          speaker_hien_tai:         v.speaker_hien_tai || '',
          speaker_de_xuat:          v.speaker_de_xuat || '',
          speaker_de_xuat_char_id:  v.speaker_de_xuat_char_id ?? null,
          bang_chung:               v.bang_chung || '',
          do_tin_cay:               v.do_tin_cay || '',
        }
      })
      setResult(restored)
      setTongKet(chunk.qcTongKet || null)
      setRawResponse('')  // không restore raw response để tiết kiệm DOM
      setRestoredFromDb(true)
    } else {
      // Chunk này chưa từng review → clear hết
      setResult([])
      setTongKet(null)
      setRawResponse('')
      setRestoredFromDb(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [chunk.index, chunk.qcVanDe])

  // Đọc config QC mỗi lần render (config có thể đã đổi ở ConfigModal mà không cần reload)
  const qcConfig = useMemo(() => {
    const c = loadConfig()
    return {
      autoApplyText:        c.qc_auto_apply_text ?? true,
      autoApplySpeaker:     c.qc_auto_apply_speaker ?? true,
      speakerMinConfidence: c.qc_speaker_min_confidence ?? 'cao',
    }
  }, [result.length])  // re-eval khi có kết quả mới

  useEffect(() => {
    if (running) {
      setElapsed(0)
      timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
    } else {
      if (timerRef.current) clearInterval(timerRef.current)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [running])

  // Apply 1 dòng (cả text và/hoặc speaker tùy issue) — gọi PATCH BE + cập nhật chunk state.
  // Trả về true nếu thực sự có thay đổi.
  const applyOneRow = (qc: QCEntry): boolean => {
    const origEntry = chunk.entries.find(e => e.index === qc.index)
    if (!origEntry) return false

    const patchBody: Record<string, any> = {}
    let changed = false

    // Text fix
    if (qc.fixed && qc.fixed !== origEntry.translated) {
      patchBody.text = qc.fixed
      changed = true
    }
    // Speaker fix
    if (qc.loai_loi === 'speaker' && qc.speaker_de_xuat_char_id != null) {
      patchBody.character_id = qc.speaker_de_xuat_char_id
      changed = true
    }

    if (!changed) return false

    // Cập nhật chunk state local
    const newEntries = chunk.entries.map(e => {
      if (e.index !== qc.index) return e
      const upd = { ...e }
      if (patchBody.text)      upd.translated = patchBody.text
      if (qc.speaker_de_xuat)  upd.speaker    = qc.speaker_de_xuat
      return upd
    })
    onApplyFixes(chunk.index, newEntries)

    // Lưu BE (fire-and-forget)
    api.patch(`/subtitles/by-index/${projectId}/${qc.index}`, patchBody).catch(() => {})

    return true
  }

  // Apply nhiều dòng theo cấu hình auto-apply.
  // Trả về Set các index đã apply.
  const applyFixesFromResult = (qcEntries: QCEntry[]): Set<number> => {
    const applied = new Set<number>()

    qcEntries.forEach(qc => {
      const isSpeakerFix = qc.loai_loi === 'speaker'
      const isHighConf   = qc.do_tin_cay === 'cao'
      const isOkConf     = isHighConf || (qcConfig.speakerMinConfidence === 'trung' && qc.do_tin_cay === 'trung')

      let shouldApplyText    = false
      let shouldApplySpeaker = false

      if (isSpeakerFix) {
        // Cho phép apply speaker (kèm text nếu có) khi:
        // - bật auto-apply speaker
        // - đạt ngưỡng tin cậy tối thiểu
        // - đã resolve được character_id
        if (qcConfig.autoApplySpeaker && isOkConf && qc.speaker_de_xuat_char_id != null) {
          shouldApplySpeaker = true
          shouldApplyText    = true   // text fix kèm theo nếu có
        }
      } else {
        // Các loại lỗi khác — apply text theo config
        if (qcConfig.autoApplyText) shouldApplyText = true
      }

      if (!shouldApplyText && !shouldApplySpeaker) return

      // Gọi applyOneRow chỉ với phần được phép
      const filteredQC: QCEntry = {
        ...qc,
        fixed: shouldApplyText ? qc.fixed : qc.translated,
        speaker_de_xuat_char_id: shouldApplySpeaker ? qc.speaker_de_xuat_char_id : null,
      }
      if (applyOneRow(filteredQC)) applied.add(qc.index)
    })

    return applied
  }

  // Cleanup SSE khi component unmount
  useEffect(() => {
    return () => {
      sseRef.current?.close()
      sseRef.current = null
    }
  }, [])

  const handleRunQC = async () => {
    if (!apiKey) { alert('Chưa có API key trong Cấu hình!'); return }
    if (chunk.entries.length === 0) { alert('Chunk chưa có bản dịch. Hãy dịch trước.'); return }
    setRunning(true); setError(''); setResult([]); setRawResponse(''); setTongKet(null); setAppliedSet(new Set())
    setRestoredFromDb(false)
    setQcStage('qc_starting'); setQcMessage('Đang kết nối...'); setQcEta(0)

    // Mở SSE để lắng nghe progress events từ BE.
    // BE publish vào kênh chung `progress` của project (cùng kênh với Pass 3).
    // Ta chỉ lọc event có stage bắt đầu bằng `qc_`.
    sseRef.current?.close()
    const es = new EventSource(`/dub/api/projects/${projectId}/translate/progress`)
    sseRef.current = es

    es.addEventListener('progress', (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data)
        const stage = d.stage || ''
        if (!stage.startsWith('qc_')) return  // bỏ qua event của Pass 3
        if (d.chunk_index != null && d.chunk_index !== chunk.index) return  // không phải chunk này

        setQcStage(stage)
        if (d.message) setQcMessage(d.message)
        if (typeof d.eta_seconds === 'number') setQcEta(d.eta_seconds)
      } catch {}
    })
    es.onerror = () => {
      // Lỗi SSE → không crash, chỉ là không có progress feedback
      // Request HTTP vẫn chạy
    }

    try {
      const res = await api.post(`/projects/${projectId}/translate/review-chunk`, {
        api_key:     apiKey,
        model,
        chunk_index: chunk.index,
        entries:     chunk.entries.map(e => ({
          index:      e.index,
          original:   e.original,
          translated: e.translated.includes('|')
            ? e.translated.split('|').slice(1).join('|').trim()
            : e.translated,
          speaker:    e.speaker || '',
        })),
      })
      const qcEntries: QCEntry[] = res.data.entries || []
      setResult(qcEntries)
      setRawResponse(res.data.raw_response || '')
      setTongKet(res.data.tong_ket || null)

      // Lưu token QC ra chunk state (để hiển thị ở chunk list + header)
      onQCDone(chunk.index, {
        tokensIn:  res.data.tokens_in  || 0,
        tokensOut: res.data.tokens_out || 0,
        timingMs:  res.data.timing_ms  || 0,
        model,
      })

      // Auto-apply theo config — chỉ áp dụng cho rows có vấn đề thật sự
      const issueEntries = qcEntries.filter(r => (r.loai_loi || '').length > 0 || (r.issue || '').trim().length > 0)
      if (issueEntries.length > 0) {
        const applied = applyFixesFromResult(issueEntries)
        setAppliedSet(applied)
      }
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Lỗi QC')
      setQcStage('qc_error')
    } finally {
      setRunning(false)
      // Đóng SSE sau 1 nhịp để event qc_done cuối còn kịp đến
      setTimeout(() => {
        sseRef.current?.close()
        sseRef.current = null
      }, 500)
    }
  }

  // Apply lại toàn bộ (nút "Áp dụng lại")
  const handleApplyAll = () => {
    const applied = applyFixesFromResult(result)
    setAppliedSet(prev => new Set([...prev, ...applied]))
  }

  // Apply 1 dòng thủ công (khi auto-apply tắt hoặc tin cậy không đủ)
  const handleApplyRow = (qc: QCEntry) => {
    if (applyOneRow(qc)) {
      setAppliedSet(prev => new Set([...prev, qc.index]))
    }
  }

  // Filter: chỉ giữ rows có vấn đề (loai_loi != '' hoặc issue != '')
  const issueRows = result.filter(r =>
    (r.loai_loi && r.loai_loi.length > 0) || (r.issue && r.issue.trim().length > 0)
  )

  const issueCount = issueRows.length
  const fixCount   = issueRows.filter(r => (r.fixed && r.fixed !== r.translated) || (r.loai_loi === 'speaker' && r.speaker_de_xuat_char_id != null)).length
  const appliedCount = appliedSet.size
  const phanLoai = tongKet?.phan_loai || {}

  return (
    <div className="flex flex-col gap-4 p-4 overflow-y-auto">
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <div className="text-[13px] font-bold text-zinc-700 dark:text-zinc-200">QC Review — Chunk {chunk.index + 1}</div>
          <div className="text-[11px] text-zinc-400 mt-0.5">
            Kiểm tra: speaker · văn phong · xưng hô · tên/thuật ngữ/cường độ
            {' · '}
            <span className={qcConfig.autoApplyText || qcConfig.autoApplySpeaker ? 'text-emerald-500' : 'text-amber-500'}>
              {qcConfig.autoApplyText && qcConfig.autoApplySpeaker ? 'Auto-apply: bật'
                : qcConfig.autoApplyText  ? 'Auto-apply: chỉ text'
                : qcConfig.autoApplySpeaker ? 'Auto-apply: chỉ speaker'
                : 'Auto-apply: tắt (duyệt thủ công)'}
            </span>
          </div>
        </div>
        {!running ? (
          <button onClick={handleRunQC} disabled={chunk.status !== 'done'}
            className="btn-primary flex-shrink-0 disabled:opacity-50">
            {result.length > 0 ? '🔄 Review lại' : '🔍 Chạy Review'}
          </button>
        ) : (
          <div className="flex items-center gap-2 text-[12px] text-blue-500 flex-shrink-0">
            <div className="w-3.5 h-3.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
            <span className="font-mono">
              ⏱ {elapsed}s
              {qcEta > 0 && elapsed < qcEta && <span className="text-zinc-400"> / ~{qcEta}s</span>}
            </span>
          </div>
        )}
      </div>

      {/* Progress feedback khi đang chạy QC */}
      {running && (
        <div className="rounded-lg border border-blue-200 dark:border-blue-800 bg-blue-50 dark:bg-blue-950/20 overflow-hidden">
          {/* Header chunk info */}
          <div className="px-3 py-2 border-b border-blue-200/60 dark:border-blue-800/60 bg-blue-100/40 dark:bg-blue-900/20 flex items-center gap-2 text-[11px]">
            <span className="font-semibold text-blue-700 dark:text-blue-300">
              QC Chunk {chunk.index + 1}
            </span>
            <span className="text-zinc-500">·</span>
            <span className="text-zinc-600 dark:text-zinc-400">{chunk.entries.length} dòng</span>
            <span className="text-zinc-500">·</span>
            <span className="text-zinc-600 dark:text-zinc-400 font-mono">{model}</span>
            <span className="ml-auto text-[10px] font-mono text-blue-600 dark:text-blue-400">
              {elapsed}s{qcEta > 0 && <span className="text-zinc-400"> / ~{qcEta}s</span>}
            </span>
          </div>

          {/* Stage indicator — 4 chấm tròn */}
          <div className="px-3 pt-2.5 flex items-center gap-1.5">
            {(['qc_start', 'qc_calling', 'qc_responding', 'qc_done'] as const).map((s, i) => {
              const ORDER = ['qc_starting', 'qc_start', 'qc_calling', 'qc_retrying', 'qc_responding', 'qc_done']
              const curIdx = ORDER.indexOf(qcStage)
              const stepIdx = ORDER.indexOf(s)
              const done   = curIdx >= stepIdx
              const active = qcStage === s || (s === 'qc_calling' && qcStage === 'qc_retrying')
              return (
                <React.Fragment key={s}>
                  <div className={`w-2 h-2 rounded-full flex-shrink-0 transition-colors ${
                    active ? 'bg-blue-500 animate-pulse' :
                    done   ? 'bg-blue-500' :
                             'bg-blue-200 dark:bg-blue-900'
                  }`} />
                  {i < 3 && (
                    <div className={`flex-1 h-0.5 rounded-full transition-colors ${
                      done && curIdx > stepIdx ? 'bg-blue-500' : 'bg-blue-200 dark:bg-blue-900'
                    }`} />
                  )}
                </React.Fragment>
              )
            })}
          </div>

          {/* Message + stage icon */}
          <div className="px-3 py-2 flex items-center gap-2 text-[12px]">
            <span className="text-base flex-shrink-0">
              {qcStage === 'qc_starting'   ? '⚡' :
               qcStage === 'qc_start'      ? '📋' :
               qcStage === 'qc_calling'    ? '📡' :
               qcStage === 'qc_retrying'   ? '🔁' :
               qcStage === 'qc_responding' ? '⚙️' :
               qcStage === 'qc_done'       ? '✅' : '🔍'}
            </span>
            <div className="flex-1 min-w-0">
              <div className="font-medium text-blue-700 dark:text-blue-300">
                {qcStage === 'qc_starting'   ? 'Bước 1/4 — Đang khởi tạo' :
                 qcStage === 'qc_start'      ? 'Bước 1/4 — Đang chuẩn bị prompt' :
                 qcStage === 'qc_calling'    ? 'Bước 2/4 — Đang gọi AI' :
                 qcStage === 'qc_retrying'   ? 'Bước 2/4 — Đang thử lại (lỗi tạm thời)' :
                 qcStage === 'qc_responding' ? 'Bước 3/4 — Đã nhận, đang phân tích' :
                 qcStage === 'qc_done'       ? 'Bước 4/4 — Hoàn tất' :
                                                'Đang xử lý...'}
              </div>
              <div className="text-[10px] text-zinc-500 dark:text-zinc-400 truncate mt-0.5">
                {qcMessage || '...'}
              </div>
              {qcStage === 'qc_retrying' && (
                <div className="text-[10px] text-amber-600 dark:text-amber-400 mt-1">
                  ⚠ Đang đợi do lỗi tạm thời (rate limit / overload) — hệ thống sẽ tự thử lại
                </div>
              )}
            </div>
            <div className="w-3.5 h-3.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin flex-shrink-0" />
          </div>

          {/* Progress bar — chỉ hiện khi có ETA */}
          {qcEta > 0 && (
            <div className="h-1 bg-blue-100 dark:bg-blue-900/40">
              <div
                className="h-full bg-blue-500 transition-all duration-1000 ease-linear"
                style={{ width: `${Math.min(100, (elapsed / qcEta) * 100)}%` }}
              />
            </div>
          )}
        </div>
      )}

      {chunk.status !== 'done' && (
        <div className="text-center text-zinc-400 text-[12px] py-8 border border-dashed border-zinc-200 dark:border-zinc-700 rounded-lg">
          Chunk cần được dịch trước khi QC Review
        </div>
      )}
      {error && (
        <div className="px-3 py-2.5 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-[12px] text-red-500">❌ {error}</div>
      )}

      {result.length > 0 && (
        <>
          <div className={`flex items-center gap-3 px-3 py-2.5 rounded-lg border text-[12px] ${
            issueCount > 0
              ? 'border-amber-200 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/20'
              : 'border-emerald-200 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/20'
          }`}>
            <span className="text-lg">{issueCount > 0 ? '⚠️' : '✅'}</span>
            <div className="flex-1">
              <span className={`font-semibold ${issueCount > 0 ? 'text-amber-700 dark:text-amber-400' : 'text-emerald-700 dark:text-emerald-400'}`}>
                {issueCount > 0 ? `${issueCount}/${result.length} dòng có vấn đề` : 'Không có vấn đề'}
              </span>
              {restoredFromDb && (
                <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-zinc-500"
                  title={`Kết quả review đã lưu trong DB${chunk.qcRunAt ? ` lúc ${new Date(chunk.qcRunAt).toLocaleString()}` : ''}${chunk.qcModel ? ` (model: ${chunk.qcModel})` : ''}`}>
                  📌 Đã lưu
                </span>
              )}
              {tongKet?.danh_gia_chung && <span className="text-zinc-400 ml-2">· {tongKet.danh_gia_chung}</span>}
              {appliedCount > 0 && (
                <span className="text-emerald-600 dark:text-emerald-400 ml-2">
                  · ✓ Đã áp dụng {appliedCount}/{fixCount}
                </span>
              )}
              {/* Phân loại lỗi */}
              {Object.keys(phanLoai).filter(k => phanLoai[k] > 0).length > 0 && (
                <div className="text-[10px] text-zinc-500 mt-1 flex gap-2 flex-wrap">
                  {Object.entries(phanLoai)
                    .filter(([, n]) => (n as number) > 0)
                    .map(([k, n]) => (
                      <span key={k} className="px-1.5 py-0.5 rounded bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700">
                        {LOAI_LOI_LABEL[k] || k}: {n as number}
                      </span>
                    ))}
                </div>
              )}
            </div>
            {fixCount > appliedCount && (
              <button onClick={handleApplyAll}
                className="btn text-[11px] text-emerald-600 border-emerald-300 dark:border-emerald-700 flex-shrink-0"
                title="Áp dụng các sửa đổi còn lại">
                ↻ Áp dụng còn lại
              </button>
            )}
          </div>

          {issueCount === 0 ? (
            <div className="text-center text-zinc-400 text-[12px] py-6 border border-dashed border-zinc-200 dark:border-zinc-700 rounded-lg">
              ✓ Tất cả {result.length} dòng đều ổn — không cần sửa gì
            </div>
          ) : (
            <div className="border border-zinc-200 dark:border-zinc-700 rounded-xl overflow-hidden">
              <table className="w-full border-collapse text-[11px]">
                <thead className="bg-zinc-50 dark:bg-zinc-800 sticky top-0">
                  <tr>
                    <th className="text-left px-2 py-2 text-zinc-400 font-semibold w-10">#</th>
                    <th className="text-left px-2 py-2 text-zinc-400 font-semibold w-20">Loại</th>
                    <th className="text-left px-2 py-2 text-zinc-400 font-semibold w-[22%]">Gốc</th>
                    <th className="text-left px-2 py-2 text-zinc-400 font-semibold w-[22%]">Hiện tại</th>
                    <th className="text-left px-2 py-2 text-zinc-400 font-semibold w-[22%]">Đề xuất</th>
                    <th className="text-left px-2 py-2 text-zinc-400 font-semibold">Bằng chứng</th>
                    <th className="text-left px-2 py-2 text-zinc-400 font-semibold w-16">Tin cậy</th>
                    <th className="text-left px-2 py-2 text-zinc-400 font-semibold w-20"></th>
                  </tr>
                </thead>
                <tbody>
                  {issueRows.map((row, i) => {
                    const isSpeaker = row.loai_loi === 'speaker'
                    const hasTextFix = !!(row.fixed && row.fixed !== row.translated)
                    const hasSpeakerFix = isSpeaker && row.speaker_de_xuat_char_id != null
                    const hasAnyFix = hasTextFix || hasSpeakerFix
                    const isApplied = appliedSet.has(row.index)
                    const tinCay = TIN_CAY_LABEL[row.do_tin_cay || ''] || { label: '—', cls: 'text-zinc-400' }
                    return (
                      <tr key={i} className={`border-t border-zinc-100 dark:border-zinc-800 align-top ${
                        isApplied ? 'bg-emerald-50/40 dark:bg-emerald-950/10' : 'bg-amber-50/40 dark:bg-amber-950/10'
                      }`}>
                        <td className="px-2 py-2 font-mono text-zinc-400">{row.index}</td>
                        <td className="px-2 py-2">
                          <span className="text-[10px] px-1.5 py-0.5 rounded bg-white dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700">
                            {LOAI_LOI_LABEL[row.loai_loi || ''] || row.loai_loi || '—'}
                          </span>
                        </td>
                        <td className="px-2 py-2 font-mono text-[10px] text-zinc-400 break-words">{row.original}</td>
                        <td className="px-2 py-2 text-zinc-600 dark:text-zinc-300 break-words">
                          <div>{row.translated}</div>
                          {row.speaker_hien_tai && (
                            <div className="text-[10px] text-zinc-400 mt-1">👤 {row.speaker_hien_tai}</div>
                          )}
                        </td>
                        <td className="px-2 py-2 break-words">
                          {hasTextFix && (
                            <div className="text-emerald-600 dark:text-emerald-400 font-medium">{row.fixed}</div>
                          )}
                          {hasSpeakerFix && (
                            <div className={`text-[10px] mt-1 ${row.speaker_de_xuat_char_id ? 'text-blue-500' : 'text-zinc-400'}`}>
                              👤 → {row.speaker_de_xuat}
                              {row.speaker_de_xuat_char_id == null && (
                                <span className="text-red-400 ml-1" title="Tên này không có trong danh sách nhân vật">⚠</span>
                              )}
                            </div>
                          )}
                          {!hasAnyFix && <span className="text-zinc-300 dark:text-zinc-600">—</span>}
                        </td>
                        <td className="px-2 py-2 text-zinc-500 dark:text-zinc-400 text-[10px] leading-snug break-words">
                          {row.bang_chung || row.issue || ''}
                        </td>
                        <td className={`px-2 py-2 text-[10px] font-mono ${tinCay.cls}`}>{tinCay.label}</td>
                        <td className="px-2 py-2">
                          {isApplied ? (
                            <span className="text-[10px] text-emerald-500 font-semibold">✓ Đã apply</span>
                          ) : hasAnyFix ? (
                            <button onClick={() => handleApplyRow(row)}
                              className="text-[10px] px-2 py-1 rounded border border-emerald-300 dark:border-emerald-700 text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-950/20"
                              title="Áp dụng sửa đổi này">
                              ✓ Apply
                            </button>
                          ) : null}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}

          {rawResponse && (
            <details className="text-[11px]">
              <summary className="cursor-pointer text-zinc-400 hover:text-zinc-600 select-none py-1">Raw response từ AI</summary>
              <pre className="mt-2 font-mono text-[10px] text-zinc-500 whitespace-pre-wrap break-words bg-zinc-50 dark:bg-zinc-800 rounded-lg p-3 border border-zinc-200 dark:border-zinc-700 max-h-[30vh] overflow-y-auto">{rawResponse}</pre>
            </details>
          )}
        </>
      )}
    </div>
  )
}

// ─── Step 2: Pass 3 chunks ────────────────────────────────────────────────────

// Timer component — đếm giây thực tế trong lúc chunk đang run
function RunTimer({ running }: { running: boolean }) {
  const [sec, setSec] = React.useState(0)
  React.useEffect(() => {
    if (!running) { setSec(0); return }
    const t = setInterval(() => setSec(s => s + 1), 1000)
    return () => clearInterval(t)
  }, [running])
  return <>{sec}s</>
}

// Timer per chunk
function ChunkTimer({ active }: { active: boolean }) {
  const [sec, setSec] = React.useState(0)
  React.useEffect(() => {
    if (!active) return
    setSec(0)
    const t = setInterval(() => setSec(s => s + 1), 1000)
    return () => clearInterval(t)
  }, [active])
  if (!active) return null
  return <span className="text-[10px] font-mono text-blue-400 ml-1">⏱ {sec}s</span>
}

const STATUS_CLS = {
  wait: 'text-zinc-400 bg-zinc-100 dark:bg-zinc-700/60 border-zinc-200 dark:border-zinc-600',
  run:  'text-blue-500 bg-blue-50 dark:bg-blue-950/40 border-blue-200 dark:border-blue-700',
  done: 'text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-700',
  err:  'text-red-500 bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-700',
}
const STATUS_DOT = {
  wait: 'bg-zinc-300 dark:bg-zinc-500',
  run:  'bg-blue-500 animate-pulse',
  done: 'bg-emerald-500',
  err:  'bg-red-500',
}
const STATUS_LABEL = { wait: 'Chờ', run: 'Đang dịch', done: 'Xong', err: 'Lỗi' }

function Step2Panel({
  state, pass1Bible, modelName, projectId, onStartRemaining, onStartAll, onStop, onRetryChunk, onDeleteChunk, onEditCell, onApplyQCFixes, onQCDone,
}: {
  state: Pass3State
  pass1Bible: Bible | null
  modelName: string
  projectId: number
  onStartRemaining: () => void
  onStartAll: () => void
  onStop: () => void
  onRetryChunk: (index: number) => void
  onDeleteChunk: (index: number) => void
  onEditCell: (chunkIndex: number, entryIndex: number, newText: string) => void
  onApplyQCFixes: (chunkIndex: number, entries: ChunkState['entries']) => void
  onQCDone: (chunkIndex: number, info: { tokensIn: number; tokensOut: number; timingMs: number; model: string }) => void
}) {
  const [selChunk, setSelChunk] = useState<number | null>(null)
  const [detailTab, setDetailTab] = useState<'table' | 'request' | 'response'>('table')
  const [editingCell, setEditingCell] = useState<{ entry: number; text: string } | null>(null)

  const chunks = state.chunks
  const sel = selChunk !== null ? chunks.find(c => c.index === selChunk) : null

  const doneCount  = chunks.filter(c => c.status === 'done').length
  const errCount   = chunks.filter(c => c.status === 'err').length
  const totalIn    = state.totalTokensIn
  const totalOut   = state.totalTokensOut

  // chunk đang bận = status 'run' hoặc đang trong runningChunks (chờ chunk_start về)
  const isChunkBusy = (idx: number) => {
    const ch = chunks.find(c => c.index === idx)
    return ch?.status === 'run' || state.runningChunks.has(idx)
  }
  // full-run đang chạy = state.running (do handleRunPass3/handleRunRemaining set)
  const anyFullRunning = state.running
  // có bất kỳ chunk nào đang chạy (kể cả single-retry)
  const anyChunkRunning = state.running || chunks.some(c => c.status === 'run') || state.runningChunks.size > 0

  // Auto-select first done chunk khi chunks load/thay đổi
  useEffect(() => {
    if (chunks.length === 0) return
    const first = chunks.find(c => c.status === 'done') || chunks[0]
    if (first) {
      setSelChunk(first.index)
      setDetailTab('table')  // luôn về Bảng dịch khi load
    }
  }, [chunks.length])

  // Auto-select running chunk
  useEffect(() => {
    const running = chunks.find(c => c.status === 'run')
    if (running) setSelChunk(running.index)
  }, [chunks.map(c => c.status).join()])

  return (
    <div className="flex flex-col flex-1 overflow-hidden min-h-0">
      {/* Banner trạng thái */}
      {anyChunkRunning && (
        <div className="flex items-center gap-3 px-4 py-2 bg-blue-50 dark:bg-blue-950/20 border-b border-blue-200 dark:border-blue-800 flex-shrink-0">
          <div className="w-3 h-3 rounded-full border-2 border-blue-500 border-t-transparent animate-spin flex-shrink-0" />
          <span className="text-[12px] text-blue-600 dark:text-blue-400 font-medium">
            Đang dịch song song {state.chunks.filter(ch => ch.status === 'run').length} chunks... Đừng đóng tab này.
          </span>
          <span className="ml-auto text-[11px] font-mono text-blue-400">
            {state.chunks.filter(ch => ch.status === 'done').length}/{state.chunks.length} xong
          </span>
        </div>
      )}
      {state.error && (
        <div className="px-4 py-2 bg-red-50 dark:bg-red-950/20 border-b border-red-200 dark:border-red-800 flex-shrink-0">
          <span className="text-[12px] text-red-500">❌ {state.error}</span>
        </div>
      )}
      <div className="flex flex-1 overflow-hidden min-h-0">
      {/* Left: chunk list */}
      <div className="w-64 flex-shrink-0 border-r border-zinc-200 dark:border-zinc-800 flex flex-col bg-zinc-50 dark:bg-zinc-900/50">
        {/* Header + run button */}
        <div className="border-b border-zinc-200 dark:border-zinc-800 flex-shrink-0 bg-white dark:bg-zinc-900">
          <div className="px-3 pt-2.5 pb-1.5">
            {/* Dòng 1: tên + đếm */}
            <div className="flex items-center justify-between gap-2 mb-1.5">
              <div className="min-w-0">
                <span className="text-[12px] font-bold text-zinc-700 dark:text-zinc-200">
                  {chunks.length > 0 ? `${chunks.length} chunks` : 'Chưa có chunk'}
                </span>
                {chunks.length > 0 && (
                  <span className="ml-2 text-[10px] text-zinc-400 font-mono">
                    {doneCount}/{chunks.length} xong
                    {errCount > 0 && <span className="text-red-400"> · {errCount} lỗi</span>}
                    {state.running && <span className="text-blue-400"> · ⏱ <RunTimer running={state.running} /></span>}
                  </span>
                )}
              </div>
            </div>
            {/* Dòng 2: nút hành động */}
            <div className="flex items-center gap-1.5">
              {!anyFullRunning && doneCount < chunks.length && chunks.length > 0 && (
                <button onClick={onStartRemaining}
                  className="btn-primary text-[11px] px-2.5 py-1 flex-1 min-w-0 truncate"
                  title={doneCount > 0
                    ? `Dịch ${chunks.length - doneCount} chunks còn lại`
                    : `Bắt đầu dịch toàn bộ ${chunks.length} chunks`}>
                  {doneCount > 0 ? `▶ Dịch tiếp (${chunks.length - doneCount})` : '▶ Dịch tất cả'}
                </button>
              )}
              {!anyFullRunning && doneCount > 0 && (
                <button onClick={onStartAll}
                  className="btn text-[11px] px-2 py-1 text-amber-600 border-amber-300 dark:border-amber-700 flex-shrink-0"
                  title="Dịch lại TẤT CẢ — ghi đè kết quả hiện tại (cần xác nhận)">
                  🔄 Tất cả
                </button>
              )}
              {!anyFullRunning && chunks.length === 0 && (
                <button disabled className="btn-primary text-[11px] px-2.5 py-1 opacity-50 cursor-not-allowed flex-1">
                  ▶ Dịch
                </button>
              )}
              {anyFullRunning && (
                <button onClick={onStop} className="btn text-[11px] px-2.5 py-1 text-red-400 border-red-200 dark:border-red-800 flex-1">
                  ⏹ Dừng
                </button>
              )}
            </div>
          </div>
          {/* Progress bar tổng */}
          {chunks.length > 0 && (
            <div className="h-1 bg-zinc-100 dark:bg-zinc-800">
              <div
                className={`h-full transition-all duration-500 ${errCount > 0 ? 'bg-amber-400' : doneCount === chunks.length ? 'bg-emerald-500' : 'bg-blue-500'}`}
                style={{ width: `${chunks.length > 0 ? Math.round((doneCount / chunks.length) * 100) : 0}%` }}
              />
            </div>
          )}
        </div>

        {/* Chunk items */}
        <div className="flex-1 overflow-y-auto">
          {chunks.length === 0 && !anyFullRunning && (
            <div className="p-4 text-[12px] text-zinc-400 text-center">
              {pass1Bible ? 'Bấm Dịch để bắt đầu' : 'Cần chạy Pass 1 trước'}
            </div>
          )}
          {chunks.map(chunk => (
            <button key={chunk.index}
              onClick={() => setSelChunk(chunk.index)}
              className={`w-full text-left px-3 py-2.5 border-b border-zinc-100 dark:border-zinc-800 transition-colors flex items-start gap-2 ${
                selChunk === chunk.index
                  ? 'bg-blue-50 dark:bg-blue-950/20'
                  : 'hover:bg-white dark:hover:bg-zinc-800/60'
              }`}>
              <div className={`w-2 h-2 rounded-full flex-shrink-0 mt-1.5 ${STATUS_DOT[chunk.status]}`} />
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-1">
                  <span className="text-[11px] font-bold text-zinc-700 dark:text-zinc-200">
                    Chunk {chunk.index + 1}
                  </span>
                  <span className={`text-[9px] font-semibold px-1.5 py-0.5 rounded border ${STATUS_CLS[chunk.status]}`}>
                    {STATUS_LABEL[chunk.status]}
                  </span>
                </div>
                <div className="text-[10px] text-zinc-400 font-mono mt-0.5">
                  dòng {chunk.startLine}–{chunk.endLine} · {chunk.lineCount} dòng
                </div>
                {chunk.tomTat && (
                  <div className="text-[10px] text-zinc-400 mt-1 leading-snug line-clamp-2">
                    {chunk.tomTat}
                  </div>
                )}
                {chunk.status === 'run' && <ChunkTimer active={true} />}
                {chunk.status === 'done' && chunk.timingMs > 0 && (
                  <div className="text-[9px] font-mono text-zinc-300 dark:text-zinc-600 mt-0.5">
                    ↑{fmtTokens(chunk.tokensIn)} ↓{fmtTokens(chunk.tokensOut)} · {fmt(chunk.timingMs)}
                  </div>
                )}
                {chunk.status === 'done' && (chunk.qcTokensIn || 0) > 0 && (
                  <div className="text-[9px] font-mono text-purple-300 dark:text-purple-700 mt-0.5">
                    QC ↑{fmtTokens(chunk.qcTokensIn || 0)} ↓{fmtTokens(chunk.qcTokensOut || 0)} · {fmt(chunk.qcTimingMs || 0)}
                  </div>
                )}
              </div>
            </button>
          ))}
        </div>

        {/* Token summary */}
        {(doneCount > 0 || totalIn > 0) && (
          <div className="border-t border-zinc-200 dark:border-zinc-700 px-3 py-2.5 bg-white dark:bg-zinc-900 flex-shrink-0">
            <div className="text-[10px] font-semibold text-zinc-400 uppercase tracking-widest mb-1.5">Tổng cộng</div>
            <div className="flex justify-between text-[11px]">
              <span className="font-mono text-blue-500">↑ {fmtTokens(totalIn)}</span>
              <span className="font-mono text-emerald-500">↓ {fmtTokens(totalOut)}</span>
            </div>
            {state.totalTimingMs > 0 && (
              <div className="text-[10px] text-zinc-400 mt-0.5">{fmt(state.totalTimingMs)} tổng</div>
            )}
          </div>
        )}
      </div>

      {/* Right: chunk detail */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {sel ? (
          <>
            {/* Detail header */}
            <div className="px-4 py-2.5 border-b border-zinc-200 dark:border-zinc-800 flex-shrink-0 bg-white dark:bg-zinc-900">
              {/* Dòng 1: tên chunk + status + spinner */}
              <div className="flex items-center gap-2 min-w-0">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[13px] font-bold text-zinc-700 dark:text-zinc-200">
                      Chunk {sel.index + 1}
                    </span>
                    <span className={`text-[10px] font-semibold px-1.5 py-0.5 rounded border ${STATUS_CLS[sel.status]}`}>
                      {STATUS_LABEL[sel.status]}
                    </span>
                    {sel.status === 'run' && (
                      <div className="flex items-center gap-1.5 text-[11px] text-blue-500">
                        <div className="w-2.5 h-2.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
                        <span className="font-mono">Đang gọi AI...</span>
                        <ChunkTimer active={true} />
                      </div>
                    )}
                  </div>
                  {sel.tomTat && (
                    <div className="text-[11px] text-zinc-400 mt-0.5 truncate">{sel.tomTat}</div>
                  )}
                </div>
              </div>
              {/* Dòng 2: token stats + nút hành động */}
              {sel.status !== 'run' && (
                <div className="flex items-center gap-2 mt-1.5 flex-wrap">
                  {/* Token dịch */}
                  {sel.tokensIn > 0 && (
                    <div className="flex items-center gap-1.5 text-[10px] font-mono bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded px-2 py-0.5">
                      <span className="text-blue-500">↑{fmtTokens(sel.tokensIn)}</span>
                      <span className="text-emerald-500">↓{fmtTokens(sel.tokensOut)}</span>
                      <span className="text-zinc-400">{fmt(sel.timingMs)}</span>
                    </div>
                  )}
                  {/* Token QC */}
                  {(sel.qcTokensIn || 0) > 0 && (
                    <div className="flex items-center gap-1.5 text-[10px] font-mono bg-purple-50 dark:bg-purple-950/30 border border-purple-200 dark:border-purple-800 rounded px-2 py-0.5">
                      <span className="text-purple-400 font-semibold">QC</span>
                      <span className="text-purple-400">↑{fmtTokens(sel.qcTokensIn || 0)}</span>
                      <span className="text-purple-500">↓{fmtTokens(sel.qcTokensOut || 0)}</span>
                      <span className="text-zinc-400">{fmt(sel.qcTimingMs || 0)}</span>
                    </div>
                  )}
                  {/* Spacer */}
                  <div className="flex-1" />
                  {/* Nút hành động */}
                  {sel.status === 'done' && !isChunkBusy(sel.index) && (
                    <>
                      <button onClick={() => onRetryChunk(sel.index)}
                        className="btn text-[11px] px-2.5 py-1 text-blue-500 border-blue-200 dark:border-blue-800"
                        title="Dịch lại chunk này — sẽ ghi đè bản dịch hiện tại">
                        🔄 Dịch lại
                      </button>
                      <button onClick={() => onDeleteChunk(sel.index)}
                        className="btn text-[11px] px-2.5 py-1 text-red-500 border-red-200 dark:border-red-800"
                        title="Xóa bản dịch chunk này">
                        🗑 Xóa
                      </button>
                    </>
                  )}
                  {sel.status === 'err' && !isChunkBusy(sel.index) && (
                    <>
                      <button onClick={() => onRetryChunk(sel.index)}
                        className="btn text-[11px] px-2.5 py-1 text-red-400 border-red-200 dark:border-red-800">
                        🔄 Dịch lại
                      </button>
                      <button onClick={() => onDeleteChunk(sel.index)}
                        className="btn text-[11px] px-2.5 py-1 text-zinc-400 border-zinc-200 dark:border-zinc-700">
                        🗑 Xóa
                      </button>
                    </>
                  )}
                  {sel.status === 'wait' && !isChunkBusy(sel.index) && (
                    <button onClick={() => onRetryChunk(sel.index)}
                      className="btn text-[11px] px-2.5 py-1">
                      ▶ Dịch chunk này
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* Tabs */}
            <div className="flex border-b border-zinc-200 dark:border-zinc-800 flex-shrink-0">
              {([['table', '📋 Bảng dịch'], ['request', '↑↓ API call'], ['response', '🔍 QC Review']] as const).map(([k, label]) => (
                <button key={k} onClick={() => setDetailTab(k as any)}
                  className={`px-4 py-2 text-[12px] font-semibold border-b-2 transition-all -mb-px ${
                    detailTab === k
                      ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                      : 'border-transparent text-zinc-400 hover:text-zinc-600'
                  }`}>
                  {label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto min-h-0">
              {/* Bảng dịch 3 cột */}
              {detailTab === 'table' && (
                <div>
                  {sel.status === 'run' && (
                    <div className="flex items-center gap-3 px-4 py-3 bg-blue-50 dark:bg-blue-950/20 border-b border-blue-100 dark:border-blue-900">
                      <div className="w-3 h-3 rounded-full border-2 border-blue-500 border-t-transparent animate-spin flex-shrink-0" />
                      <div>
                        <span className="text-[12px] text-blue-600 dark:text-blue-400 font-medium">Đang gọi AI dịch chunk này...</span>
                        <span className="text-[11px] text-zinc-400 ml-2">Thinking đã tắt · thường 10–30s</span>
                      </div>
                    </div>
                  )}
                  {sel.status === 'wait' && (
                    <div className="flex items-center justify-center py-12 text-zinc-400 text-[13px]">
                      Chunk này chưa được dịch
                    </div>
                  )}
                  {sel.status === 'err' && (
                    <div className="p-4 m-4 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-[12px] text-red-500 font-mono">
                      ❌ {sel.error}
                    </div>
                  )}
                  {sel.entries.length > 0 && (
                    <table className="w-full border-collapse text-[12px]">
                      <thead className="sticky top-0 bg-zinc-50 dark:bg-zinc-800/90">
                        <tr>
                          <th className="text-left px-3 py-2 text-[10px] font-semibold text-zinc-400 uppercase tracking-widest border-b border-zinc-200 dark:border-zinc-700 w-8">#</th>
                          <th className="text-left px-3 py-2 text-[10px] font-semibold text-zinc-400 uppercase tracking-widest border-b border-zinc-200 dark:border-zinc-700 w-[40%]">Gốc</th>
                          <th className="text-left px-3 py-2 text-[10px] font-semibold text-zinc-400 uppercase tracking-widest border-b border-zinc-200 dark:border-zinc-700">Dịch</th>
                          <th className="text-left px-3 py-2 text-[10px] font-semibold text-zinc-400 uppercase tracking-widest border-b border-zinc-200 dark:border-zinc-700 w-24">Nhân vật</th>
                        </tr>
                      </thead>
                      <tbody>
                        {sel.entries.map((entry, ei) => {
                          const isEditing = editingCell?.entry === ei
                          return (
                            <tr key={ei} className="border-b border-zinc-100 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800/30">
                              <td className="px-3 py-2 font-mono text-zinc-400 align-top">{entry.index}</td>
                              <td className="px-3 py-2 text-zinc-500 dark:text-zinc-400 font-mono text-[11px] leading-snug align-top">
                                {entry.original}
                              </td>
                              <td className="px-3 py-2 align-top">
                                {isEditing ? (
                                  <div className="flex items-start gap-1">
                                    <textarea
                                      autoFocus
                                      value={editingCell.text}
                                      onChange={e => setEditingCell({ ...editingCell, text: e.target.value })}
                                      onKeyDown={e => {
                                        if (e.key === 'Enter' && !e.shiftKey) {
                                          e.preventDefault()
                                          onEditCell(sel.index, ei, editingCell.text)
                                          setEditingCell(null)
                                        }
                                        if (e.key === 'Escape') setEditingCell(null)
                                      }}
                                      rows={2}
                                      className="input text-[12px] w-full resize-none p-1.5"
                                    />
                                    <div className="flex flex-col gap-1 flex-shrink-0">
                                      <button onClick={() => { onEditCell(sel.index, ei, editingCell.text); setEditingCell(null) }}
                                        className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500 text-white">✓</button>
                                      <button onClick={() => setEditingCell(null)}
                                        className="text-[10px] px-1.5 py-0.5 rounded border border-zinc-200 dark:border-zinc-700 text-zinc-400">✕</button>
                                    </div>
                                  </div>
                                ) : (
                                  <div className="group flex items-start gap-1">
                                    <span className="text-zinc-700 dark:text-zinc-200 leading-snug flex-1">
                                      {/* Split "Speaker|text" nếu BE chưa xử lý */}
                                      {entry.translated.includes('|')
                                        ? entry.translated.split('|').slice(1).join('|').trim()
                                        : entry.translated}
                                    </span>
                                    <button
                                      onClick={() => setEditingCell({ entry: ei, text: entry.translated })}
                                      className="opacity-0 group-hover:opacity-100 text-[10px] text-zinc-400 hover:text-blue-500 px-1 flex-shrink-0 transition-opacity">
                                      ✎
                                    </button>
                                  </div>
                                )}
                              </td>
                              <td className="px-3 py-2 text-[10px] align-top">
                                {(() => {
                                  // Lấy speaker từ entry.speaker hoặc split từ translated
                                  const spk = entry.speaker ||
                                    (entry.translated.includes('|')
                                      ? entry.translated.split('|')[0].trim()
                                      : '')
                                  return spk
                                    ? <span className="text-[10px] font-medium text-purple-500">{spk}</span>
                                    : <span className="text-zinc-300 dark:text-zinc-600">—</span>
                                })()}
                              </td>
                            </tr>
                          )
                        })}
                      </tbody>
                    </table>
                  )}
                </div>
              )}

              {/* API Call — Request + Response */}
              {detailTab === 'request' && (() => {
                const mdl = modelName || 'gemini-2.5-flash'
                const m = mdl.toLowerCase()
                let providerLabel: string, apiUrl: string
                if (m.startsWith('deepseek')) {
                  providerLabel = 'DeepSeek API'; apiUrl = 'api.deepseek.com/v1/chat/completions'
                } else if (m.startsWith('gpt') || m.startsWith('o')) {
                  providerLabel = 'OpenAI API'; apiUrl = 'api.openai.com/v1/chat/completions'
                } else {
                  providerLabel = 'Gemini API'
                  apiUrl = `generativelanguage.googleapis.com/v1beta/models/${mdl || '?'}:generateContent`
                }
                return (
                  <div className="flex flex-col gap-4 p-4 text-[12px]">
                    {/* Request */}
                    <div>
                      <div className="panel-label mb-2">↑ Request → {providerLabel} (Pass 3)</div>
                      <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 overflow-hidden">
                        {/* Header */}
                        <div className="flex items-center gap-2 px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border-b border-zinc-200 dark:border-zinc-700">
                          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-950 text-blue-600 dark:text-blue-400">POST</span>
                          <span className="font-mono text-[10px] text-zinc-500 truncate">{apiUrl}</span>
                        </div>
                        {/* Params */}
                        <div className="divide-y divide-zinc-100 dark:divide-zinc-800">
                          <div className="flex items-center gap-3 px-3 py-2">
                            <span className="font-mono text-zinc-400 w-28 flex-shrink-0 text-[11px]">chunk</span>
                            <span className="text-zinc-600 dark:text-zinc-300 font-mono text-[11px]">
                              #{sel.startLine}–{sel.endLine} · {sel.lineCount} dòng
                            </span>
                          </div>
                          {sel.tokensIn > 0 && (
                            <div className="flex items-center gap-3 px-3 py-2">
                              <span className="font-mono text-zinc-400 w-28 flex-shrink-0 text-[11px]">tokens input</span>
                              <span className="font-mono text-blue-500 text-[11px]">~{sel.tokensIn.toLocaleString()}</span>
                            </div>
                          )}
                          {/* Prompt */}
                          <div className="px-3 py-2 flex flex-col gap-1.5">
                            <div className="flex items-center justify-between">
                              <span className="font-mono text-zinc-400 text-[11px]">prompt (pass3_translate.txt)</span>
                              {sel.prompt && (
                                <button onClick={() => navigator.clipboard.writeText(sel.prompt)}
                                  className="text-[10px] text-zinc-400 hover:text-zinc-600 border border-zinc-200 dark:border-zinc-700 rounded px-2 py-0.5 bg-white dark:bg-zinc-800">
                                  Copy
                                </button>
                              )}
                            </div>
                            {sel.prompt ? (
                              <pre className="font-mono text-[10px] text-zinc-600 dark:text-zinc-300 leading-relaxed whitespace-pre-wrap break-words bg-zinc-50 dark:bg-zinc-800 rounded-lg p-3 border border-zinc-200 dark:border-zinc-700 max-h-[35vh] overflow-y-auto">
                                {sel.prompt}
                              </pre>
                            ) : (
                              <div className="flex items-center gap-3 py-2">
                                <span className="text-zinc-400 italic text-[11px] flex-1">
                                  {sel.status === 'wait'
                                    ? 'Prompt sẽ hiển thị sau khi chunk được dịch'
                                    : 'Prompt không lưu sau F5 — dịch lại để xem'}
                                </span>
                                {sel.status === 'done' && !isChunkBusy(sel.index) && (
                                  <button onClick={() => onRetryChunk(sel.index)}
                                    className="text-[11px] px-3 py-1 rounded-lg border border-blue-200 dark:border-blue-800 text-blue-500 bg-blue-50 dark:bg-blue-950/30 hover:bg-blue-100 dark:hover:bg-blue-950/50 transition-colors flex-shrink-0">
                                    🔄 Dịch lại để xem
                                  </button>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Response */}
                    <div>
                      <div className="panel-label mb-2">↓ Response ← {providerLabel}</div>
                      <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 overflow-hidden">
                        {/* Status bar */}
                        <div className="flex items-center gap-3 px-3 py-2 bg-zinc-50 dark:bg-zinc-800 border-b border-zinc-200 dark:border-zinc-700">
                          <span className={`text-[11px] font-bold px-2 py-0.5 rounded ${
                            sel.status === 'done' ? 'bg-emerald-100 dark:bg-emerald-950 text-emerald-600 dark:text-emerald-400' :
                            sel.status === 'run'  ? 'bg-blue-100 dark:bg-blue-950 text-blue-500' :
                            sel.status === 'err'  ? 'bg-red-100 dark:bg-red-950 text-red-500' :
                            'bg-zinc-100 dark:bg-zinc-700 text-zinc-400'
                          }`}>
                            {sel.status === 'done' ? '✓ 200 OK' :
                             sel.status === 'run'  ? '⏳ Đang nhận...' :
                             sel.status === 'err'  ? '✕ Error' : '— Chờ xử lý'}
                          </span>
                          {sel.timingMs > 0 && (
                            <span className="font-mono text-[11px] text-zinc-400">{fmt(sel.timingMs)}</span>
                          )}
                          {sel.status === 'done' && sel.tokensIn > 0 && (
                            <div className="ml-auto flex items-center gap-2">
                              <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-blue-50 dark:bg-blue-950/40 text-blue-500 border border-blue-200 dark:border-blue-800">
                                in: {sel.tokensIn.toLocaleString()}
                              </span>
                              <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-950/40 text-emerald-500 border border-emerald-200 dark:border-emerald-800">
                                out: {sel.tokensOut.toLocaleString()}
                              </span>
                              <span className="font-mono text-[10px] px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-500 border border-zinc-200 dark:border-zinc-700">
                                ∑ {(sel.tokensIn + sel.tokensOut).toLocaleString()}
                              </span>
                            </div>
                          )}
                        </div>
                        {/* Raw response */}
                        <div className="px-3 py-2 flex flex-col gap-1.5">
                          <div className="flex items-center justify-between">
                            <span className="font-mono text-zinc-400 text-[11px]">raw response</span>
                            {sel.response && (
                              <button onClick={() => navigator.clipboard.writeText(sel.response)}
                                className="text-[10px] text-zinc-400 hover:text-zinc-600 border border-zinc-200 dark:border-zinc-700 rounded px-2 py-0.5 bg-white dark:bg-zinc-800">
                                Copy
                              </button>
                            )}
                          </div>
                          {sel.status === 'run' ? (
                            <div className="flex items-center gap-2 text-[11px] text-blue-500 py-2">
                              <div className="w-3 h-3 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />
                              Đang nhận response từ AI...
                            </div>
                          ) : sel.response ? (
                            <pre className="font-mono text-[10px] text-zinc-600 dark:text-zinc-300 leading-relaxed whitespace-pre-wrap break-words bg-zinc-50 dark:bg-zinc-800 rounded-lg p-3 border border-zinc-200 dark:border-zinc-700 max-h-[35vh] overflow-y-auto">
                              {sel.response}
                            </pre>
                          ) : (
                            <div className="flex items-center gap-3 py-2">
                              <span className="text-zinc-400 italic text-[11px] flex-1">
                                {sel.status === 'wait'
                                  ? 'Response sẽ hiển thị sau khi chunk được dịch'
                                  : 'Response không lưu sau F5 — dịch lại để xem'}
                              </span>
                              {sel.status === 'done' && !isChunkBusy(sel.index) && (
                                <button onClick={() => onRetryChunk(sel.index)}
                                  className="text-[11px] px-3 py-1 rounded-lg border border-blue-200 dark:border-blue-800 text-blue-500 bg-blue-50 dark:bg-blue-950/30 hover:bg-blue-100 transition-colors flex-shrink-0">
                                  🔄 Dịch lại để xem
                                </button>
                              )}
                            </div>
                          )}
                          {sel.error && (
                            <div className="px-3 py-2 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-[11px] text-red-500 font-mono">
                              ❌ {sel.error}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                )
              })()}

              {/* QC Review tab */}
              {detailTab === 'response' && (
                <QCReviewPanel
                  chunk={sel}
                  projectId={projectId}
                  bible={pass1Bible}
                  apiKey={getApiKey(loadConfig(), modelName)}
                  model={modelName}
                  onApplyFixes={onApplyQCFixes}
                  onQCDone={onQCDone}
                />
              )}
            </div>
          </>
        ) : (
          <div className="flex-1 flex items-center justify-center text-zinc-400 text-[13px]">
            {chunks.length === 0 ? 'Bắt đầu dịch để xem chunks' : 'Chọn chunk để xem chi tiết'}
          </div>
        )}
      </div>
      </div>
    </div>
  )
}

// ─── Main TranslatePage ────────────────────────────────────────────────────────

interface Props {
  projectId: number
  onBack: () => void
}

export default function TranslatePage({ projectId, onBack }: Props) {
  const project  = useStore(s => s.project)
  const subtitles = useStore(s => s.subtitles)
  const loadProject = useStore(s => s.loadProject)

  const [config, setConfig] = useState(() => loadConfig())

  const [step, setStep] = useState<StepId>(0)

  // Step 0 state
  const [pass0, setPass0] = useState<Pass0State>({
    scanned: false, issues: [], running: false, report: [], cleaned: false,
  })

  // Step 1 state
  const [pass1, setPass1] = useState<Pass1State>({
    running: false, done: false, elapsedMs: 0,
    tokensIn: 0, tokensOut: 0, timingMs: 0, bible: null, error: '',
    pass1a: null, pass1b: null,
    stage: 'idle', stageMessage: '',
    pass1aStats: null, pass1bStats: null,
  })

  // Step 3 state — Pass 2 Speaker (AI quyết định cuối)
  const [pass2Speaker, setPass2Speaker] = useState<Pass2SpeakerState>({
    running: false, done: false,
    total: 0, updated: 0, unknown: 0,
    tokensIn: 0, tokensOut: 0, timingMs: 0,
    sceneCount: 0, doneScenes: 0, totalScenes: 0,
    error: '', stageMessage: '',
  })

  // Step 4 state — Pass 3 dịch
  const [pass3, setPass3] = useState<Pass3State>({
    running: false, runningChunks: new Set(), done: false, chunks: [],
    totalTokensIn: 0, totalTokensOut: 0, totalTimingMs: 0, error: '',
  })

  const [showConfig, setShowConfig] = useState(false)
  const esRef = useRef<EventSource | null>(null)

  // Load project + existing Bible
  useEffect(() => {
    const init = async () => {
      await loadProject(projectId)
      try {
        const r = await api.get(`/projects/${projectId}/bible`)
        if (r.data?.bible) {
          setPass1(s => ({ ...s, done: true, bible: r.data.bible, stage: 'done' }))
          await buildChunksFromBible(r.data.bible)
          setStep(2)  // Đã có Bible → nhảy đến step Phân tích
        }
      } catch {}
    }
    init()
  }, [projectId])

  // Build chunks từ Bible scene_map, load subtitles thẳng từ API
  const buildChunksFromBible = useCallback(async (bible: Bible) => {
    const scenes = bible.scene_map || []
    if (scenes.length === 0) return

    // Load subtitles mới nhất từ DB
    let freshSubs: Subtitle[] = []
    try {
      const r = await api.get(`/subtitles/project/${projectId}`)
      // API trả array trực tiếp hoặc object {subtitles: [...]}
      freshSubs = Array.isArray(r.data) ? r.data : (r.data?.subtitles || r.data || [])
    } catch {}

    // Load saved chunks (status + prompt/response + QC snapshot) từ DB
    let savedChunks: Record<number, any> = {}
    try {
      const cr = await api.get(`/projects/${projectId}/translate/chunks`)
      const arr = Array.isArray(cr.data) ? cr.data : []
      arr.forEach((ch: any) => { savedChunks[ch.chunk_index] = ch })
    } catch {}

    const chunks: ChunkState[] = scenes.map((scene, i) => {
      // scene.tu_dong/den_dong là subtitle index (1-based từ SRT)
      const chunkSubs = freshSubs.filter(
        (s: Subtitle) => s.index >= scene.tu_dong && s.index <= scene.den_dong
      )
      // Trạng thái chunk lấy thẳng từ DB (translate_chunks.status), không phải đoán.
      const saved      = savedChunks[i]
      const dbStatus   = (saved?.status || '') as 'wait' | 'run' | 'done' | 'err' | ''
      const hasResponse = !!(saved && (saved.response || '').trim().length > 0)
      // Nếu DB không có status (row cũ trước migration) → fallback: có response = done
      const status: 'wait' | 'run' | 'done' | 'err' =
        dbStatus || (hasResponse ? 'done' : 'wait')

      const entries = chunkSubs.map((s: Subtitle) => ({
        index:      s.index,
        original:   s.original_text || '',
        translated: s.text || '',
        speaker:    (s as any).character?.name || '',
      }))
      return {
        index:     i,
        startLine: scene.tu_dong,
        endLine:   scene.den_dong,
        lineCount: scene.den_dong - scene.tu_dong + 1,
        status,
        tomTat:    scene.tom_tat || '',
        response:  saved?.response  || '',
        prompt:    saved?.prompt    || '',
        tokensIn:  saved?.tokens_in  || 0,
        tokensOut: saved?.tokens_out || 0,
        timingMs:  saved?.timing_ms  || 0,
        error:     saved?.error || '',
        // entries chỉ hiển thị khi status='done' (chunk đã thực sự được dịch)
        entries:   (status === 'done' || status === 'run') ? entries : [],
        // QC snapshot — nếu có sẽ tự restore khi user click vào chunk
        qcVanDe:    saved?.qc_van_de    || null,
        qcTongKet:  saved?.qc_tong_ket  || null,
        qcTokensIn: saved?.qc_tokens_in || 0,
        qcTokensOut:saved?.qc_tokens_out|| 0,
        qcTimingMs: saved?.qc_timing_ms || 0,
        qcModel:    saved?.qc_model     || '',
        qcRunAt:    saved?.qc_run_at    || '',
      }
    })

    setPass3(s => ({
      ...s,
      chunks,
      done: chunks.length > 0 && chunks.every(ch => ch.status === 'done'),
    }))
  }, [projectId])

  useEffect(() => () => { esRef.current?.close() }, [])

  // ── Pass 0 ──────────────────────────────────────────────────────────────────

  const handleScan = useCallback(() => {
    const issues = scanAbnormal(subtitles)
    setPass0(s => ({ ...s, scanned: true, issues }))
  }, [subtitles])

  const handleClean = useCallback(async () => {
    setPass0(s => ({ ...s, running: true }))
    try {
      const res = await api.post(`/projects/${projectId}/translate/pass0-clean`, {
        api_key: getApiKey(config, config.model_pass1),
        model:   config.model_pass1,
      })
      setPass0(s => ({ ...s, running: false, cleaned: true, report: res.data.report || [] }))
      await loadProject(projectId)
    } catch (err: any) {
      setPass0(s => ({ ...s, running: false }))
      alert(err?.response?.data?.detail || 'Lỗi làm sạch')
    }
  }, [projectId, config])

  // ── Pass 1 ──────────────────────────────────────────────────────────────────

  const handleRunPass1 = useCallback(async () => {
    const apiKey = getApiKey(config, config.model_pass1)
    if (!apiKey) { alert('Chưa có API key! Vào Cấu hình để nhập.'); return }

    setPass1({
      running: true, done: false, elapsedMs: 0,
      tokensIn: 0, tokensOut: 0, timingMs: 0,
      bible: null, error: '', pass1a: null, pass1b: null,
      stage: 'pass1a', stageMessage: 'Đang chuẩn bị...',
      pass1aStats: null, pass1bStats: null,
    })

    // Mở SSE listener — backend sẽ publish event pass1a_start/done, pass1b_start/done
    // qua channel /translate/progress của project.
    // Đóng SSE cũ nếu còn (tránh duplicate listener).
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    const es = new EventSource(`/dub/api/projects/${projectId}/translate/progress`)
    esRef.current = es
    const pass1aStartTime = Date.now()
    let pass1bStartTime = 0

    es.addEventListener('progress', (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data)
        if (d.stage === 'pass1a_start') {
          setPass1(s => ({ ...s, stage: 'pass1a', stageMessage: d.message || 'Đang phân tích nhân vật...' }))
        } else if (d.stage === 'pass1a_done') {
          const elapsedMs = Date.now() - pass1aStartTime
          pass1bStartTime = Date.now()
          setPass1(s => ({
            ...s,
            stage: 'pass1b',
            stageMessage: d.message || 'Pass 1A xong, đang phân tích cốt truyện...',
            // Parse số nhân vật từ message: "phát hiện 15 nhân vật"
            pass1aStats: {
              nhan_vat: parseInt((d.message || '').match(/(\d+)\s*nhân vật/)?.[1] || '0', 10),
              time_ms:  elapsedMs,
            },
          }))
        } else if (d.stage === 'pass1b_start') {
          pass1bStartTime = Date.now()
          setPass1(s => ({ ...s, stage: 'pass1b', stageMessage: d.message || '' }))
        } else if (d.stage === 'pass1b_done') {
          const elapsedMs = Date.now() - pass1bStartTime
          setPass1(s => ({
            ...s,
            stage: 'merging',
            stageMessage: d.message || 'Đang tổng hợp Bible...',
            pass1bStats: {
              scene_count: parseInt((d.message || '').match(/(\d+)\s*đoạn/)?.[1] || '0', 10),
              time_ms:     elapsedMs,
            },
          }))
        }
      } catch (err) {
        console.error('SSE parse error:', err)
      }
    })

    try {
      const res = await api.post(`/projects/${projectId}/translate/analyze`, {
        api_key:     apiKey,
        model:       config.model_pass1,
        source_lang: 'zh',
      })
      // Đóng SSE khi API trả về xong
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      setPass1(s => ({
        ...s,
        running: false, done: true,
        stage:   'done',
        stageMessage: 'Hoàn tất',
        bible:    res.data.bible,
        tokensIn:  res.data.tokens_in  || 0,
        tokensOut: res.data.tokens_out || 0,
        timingMs:  res.data.timing_ms  || 0,
        pass1a:    res.data.pass1a || null,
        pass1b:    res.data.pass1b || null,
      }))
      await buildChunksFromBible(res.data.bible)
    } catch (err: any) {
      if (esRef.current) {
        esRef.current.close()
        esRef.current = null
      }
      setPass1(s => ({
        ...s, running: false,
        stage: 'idle',
        error: err?.response?.data?.detail || err?.message || 'Lỗi Pass 1',
      }))
    }
  }, [projectId, config])

  // ── Pass 2 Speaker ──────────────────────────────────────────────────────────

  const handleRunPass2Speaker = useCallback(async () => {
    const apiKey = getApiKey(config, config.model_pass1)
    if (!apiKey) { alert('Chưa có API key! Vào Cấu hình để nhập.'); return }
    if (!pass1.bible) { alert('Chưa có Bible. Hãy chạy Pass 1 trước.'); return }

    const sceneCount = pass1.bible.scene_map?.length || 0
    setPass2Speaker({
      running: true, done: false,
      total: 0, updated: 0, unknown: 0,
      tokensIn: 0, tokensOut: 0, timingMs: 0,
      sceneCount, doneScenes: 0, totalScenes: sceneCount,
      error: '', stageMessage: `Đang chuẩn bị ${sceneCount} scene...`,
    })

    // Mở SSE để nhận progress per-scene
    if (esRef.current) { esRef.current.close(); esRef.current = null }
    const es = new EventSource(`/dub/api/projects/${projectId}/translate/progress`)
    esRef.current = es

    es.addEventListener('progress', (e: MessageEvent) => {
      try {
        const d = JSON.parse(e.data)
        if (d.stage === 'pass2_start') {
          setPass2Speaker(s => ({ ...s, stageMessage: d.message || '' }))
        } else if (d.stage === 'pass2_scene_done') {
          setPass2Speaker(s => ({
            ...s,
            doneScenes: s.doneScenes + 1,
            stageMessage: d.message || '',
          }))
        } else if (d.stage === 'pass2_scene_err') {
          setPass2Speaker(s => ({ ...s, stageMessage: `⚠ ${d.message}` }))
        } else if (d.stage === 'pass2_done') {
          setPass2Speaker(s => ({ ...s, stageMessage: d.message || '' }))
        }
      } catch {}
    })

    try {
      const res = await api.post(`/projects/${projectId}/translate/pass2-speaker`, {
        api_key: apiKey,
        model:   config.model_pass1,
        concurrency: 3,
      })
      if (esRef.current) { esRef.current.close(); esRef.current = null }
      setPass2Speaker(s => ({
        ...s,
        running: false, done: true,
        total:     res.data.total     || 0,
        updated:   res.data.updated   || 0,
        unknown:   res.data.unknown   || 0,
        tokensIn:  res.data.tokens_in || 0,
        tokensOut: res.data.tokens_out|| 0,
        timingMs:  res.data.timing_ms || 0,
        doneScenes: sceneCount,
        stageMessage: 'Hoàn tất',
      }))
      // Reload subtitles để Pass 3 dùng character_id mới
      await loadProject(projectId)
    } catch (err: any) {
      if (esRef.current) { esRef.current.close(); esRef.current = null }
      setPass2Speaker(s => ({
        ...s, running: false,
        error: err?.response?.data?.detail || err?.message || 'Lỗi Pass 2',
      }))
    }
  }, [projectId, config, pass1.bible])
  // ── Pass 3 ──────────────────────────────────────────────────────────────────

  // Helper: gắn SSE listener cho progress của Pass 3.
  // Tách riêng để cả handleRunPass3 (full run) lẫn handleRetryChunk (dịch lại 1 chunk)
  // đều dùng chung cơ chế stream progress.
  const _attachPass3SSE = useCallback(() => {
    // Đóng SSE cũ nếu còn — tránh duplicate listeners gây state corrupt
    if (esRef.current) {
      esRef.current.close()
      esRef.current = null
    }
    const es = new EventSource(`/dub/api/projects/${projectId}/translate/progress`)
    esRef.current = es

    es.addEventListener('progress', async (e: MessageEvent) => {
      const d = JSON.parse(e.data)

      if (d.stage === 'chunk_start') {
        setPass3(s => {
          const rc = new Set(s.runningChunks)
          rc.add(d.chunk_index)
          return {
            ...s,
            runningChunks: rc,
            chunks: s.chunks.map(ch =>
              ch.index === d.chunk_index ? { ...ch, status: 'run' as const } : ch
            ),
          }
        })
      } else if (d.stage === 'chunk_done') {
        const entries = (d.entries || []).map((e: any) => ({
          index:      e.index,
          original:   e.original   || '',
          translated: e.translated || '',
          speaker:    e.speaker    || '',
        }))
        setPass3(s => {
          const rc = new Set(s.runningChunks)
          rc.delete(d.chunk_index)
          return {
            ...s,
            runningChunks: rc,
            totalTokensIn:  s.totalTokensIn  + (d.tokens_in  || 0),
            totalTokensOut: s.totalTokensOut + (d.tokens_out || 0),
            totalTimingMs:  s.totalTimingMs  + (d.timing_ms  || 0),
            chunks: s.chunks.map(ch =>
              ch.index === d.chunk_index ? {
                ...ch,
                status:    'done' as const,
                response:  d.response  || '',
                prompt:    d.prompt    || '',
                tokensIn:  d.tokens_in  || 0,
                tokensOut: d.tokens_out || 0,
                timingMs:  d.timing_ms  || 0,
                error:     '',
                entries,
              } : ch
            ),
          }
        })
      } else if (d.stage === 'chunk_error') {
        setPass3(s => {
          const rc = new Set(s.runningChunks)
          rc.delete(d.chunk_index)
          return {
            ...s,
            runningChunks: rc,
            chunks: s.chunks.map(ch =>
              ch.index === d.chunk_index
                ? { ...ch, status: 'err' as const, error: d.error || d.message || 'Lỗi' }
                : ch
            ),
          }
        })
      } else if (d.stage === 'pass3') {
        setPass3(s => ({ ...s }))
      } else if (d.stage === 'done') {
        es.close()
        setPass3(s => ({ ...s, running: false, runningChunks: new Set(), done: s.chunks.every(c => c.status === 'done') }))
        // KHÔNG gọi loadProject() ở đây — nó trigger buildChunksFromBible → reset toàn bộ
        // chunk về wait (vì DB chưa kịp flush status=done cho tất cả chunks).
        // State chunk đã được cập nhật đúng real-time qua chunk_done events ở trên.
      } else if (d.stage === 'error') {
        es.close()
        setPass3(s => ({ ...s, running: false, runningChunks: new Set(), error: d.message || 'Lỗi không xác định' }))
      }
    })

    es.onerror = () => {
      es.close()
      setPass3(s => ({ ...s, running: false, runningChunks: new Set(), error: 'Mất kết nối SSE' }))
    }
  }, [projectId])

  const handleRunPass3 = useCallback(async () => {
    const apiKey = getApiKey(config, config.model_pass3)
    if (!apiKey) { alert('Chưa có API key!'); return }
    if (!pass1.bible) { alert('Cần chạy Pass 1 trước!'); return }

    setPass3(s => ({ ...s, running: true, done: false, error: '' }))
    try {
      await api.post(`/projects/${projectId}/translate/run`, {
        api_key:     apiKey,
        model:       config.model_pass3,
        concurrency: config.concurrency,
        enable_qc:   false,
      })
      _attachPass3SSE()
    } catch (err: any) {
      setPass3(s => ({ ...s, running: false, error: err?.response?.data?.detail || err?.message || 'Lỗi Pass 3' }))
    }
  }, [projectId, config, pass1.bible, _attachPass3SSE])

  // Dịch các chunk còn lại (wait + err), KHÔNG động vào chunks done.
  // Đây là hành vi mặc định khi user click nút "Dịch tiếp" ở header.
  const handleRunRemaining = useCallback(async () => {
    const apiKey = getApiKey(config, config.model_pass3)
    if (!apiKey) { alert('Chưa có API key!'); return }
    if (!pass1.bible) { alert('Cần chạy Pass 1 trước!'); return }

    // Lấy chunks chưa dịch (wait/err) từ state hiện tại
    const remaining = pass3.chunks.filter(c => c.status === 'wait' || c.status === 'err')
    if (remaining.length === 0) {
      alert('Tất cả chunks đã dịch xong!\n\nNếu muốn dịch lại toàn bộ, dùng nút "🔄 Dịch lại tất cả".')
      return
    }
    const chunkIndices = remaining.map(c => c.index)

    // Reset các chunk được chọn về wait (chunks done giữ nguyên)
    setPass3(s => ({
      ...s,
      running: true,
      done: false,
      error: '',
      // KHÔNG reset chunks state ở đây — chunks wait/err không có data cần clear
      // Chỉ đảm bảo running=true để header hiện nút Dừng
    }))

    try {
      await api.post(`/projects/${projectId}/translate/run-chunks`, {
        api_key:        apiKey,
        model:          config.model_pass3,
        concurrency:    config.concurrency,
        chunk_indices:  chunkIndices,
      })
      _attachPass3SSE()
    } catch (err: any) {
      setPass3(s => ({ ...s, running: false, error: err?.response?.data?.detail || err?.message || 'Lỗi dịch' }))
    }
  }, [projectId, config, pass1.bible, pass3.chunks, _attachPass3SSE])

  // Dịch LẠI toàn bộ chunks (kể cả đã done) — cần confirm vì sẽ ghi đè kết quả cũ.
  const handleRunAll = useCallback(async () => {
    const doneCount = pass3.chunks.filter(c => c.status === 'done').length
    if (doneCount > 0) {
      const ok = window.confirm(
        `Dịch LẠI toàn bộ ${pass3.chunks.length} chunks?\n\n` +
        `${doneCount} chunks đã dịch sẽ bị GHI ĐÈ — bản dịch hiện tại + QC review của các chunks này sẽ mất.\n\n` +
        `Nếu chỉ muốn dịch các chunks chưa xong, dùng nút "▶ Dịch tiếp".\n\nTiếp tục?`
      )
      if (!ok) return
    }
    handleRunPass3()
  }, [pass3.chunks, handleRunPass3])

  const handleStop = useCallback(() => {
    esRef.current?.close()
    api.post(`/projects/${projectId}/translate/cancel`).catch(() => {})
    setPass3(s => ({ ...s, running: false }))
  }, [projectId])

  // Dịch lại 1 chunk cụ thể — gọi endpoint /translate/run-chunks
  // để BE chỉ chạy đúng chunk đó (không phải full pass3).
  const handleRetryChunk = useCallback(async (chunkIndex: number) => {
    const apiKey = getApiKey(config, config.model_pass3)
    if (!apiKey) { alert('Chưa có API key!'); return }
    if (!pass1.bible) { alert('Cần chạy Pass 1 trước!'); return }

    // Set chunk về 'run' ngay để UI spinner hiện đúng (không cần chờ SSE chunk_start)
    setPass3(s => ({
      ...s,
      done: false,
      error: '',
      chunks: s.chunks.map(c => c.index === chunkIndex
        ? { ...c, status: 'run' as const, error: '', response: '', prompt: '',
            tokensIn: 0, tokensOut: 0, timingMs: 0, entries: [] }
        : c),
    }))

    try {
      await api.post(`/projects/${projectId}/translate/run-chunks`, {
        api_key:        apiKey,
        model:          config.model_pass3,
        concurrency:    config.concurrency,
        chunk_indices:  [chunkIndex],
      })
      _attachPass3SSE()
    } catch (err: any) {
      setPass3(s => ({ ...s, running: false, error: err?.response?.data?.detail || err?.message || 'Lỗi dịch lại chunk' }))
    }
  }, [projectId, config, pass1.bible, _attachPass3SSE])

  // Xóa bản dịch của 1 chunk: reset chunk về 'wait', xóa row translate_chunks,
  // xóa text dịch + character_id của các subtitle trong phạm vi chunk.
  const handleDeleteChunk = useCallback(async (chunkIndex: number) => {
    const ok = window.confirm(
      `Xóa bản dịch chunk ${chunkIndex + 1}?\n\n` +
      `Toàn bộ bản dịch + gán nhân vật + kết quả QC của chunk này sẽ bị xóa. ` +
      `Bản gốc tiếng Trung được giữ nguyên.\n\nKhông thể hoàn tác.`
    )
    if (!ok) return

    try {
      await api.delete(`/projects/${projectId}/translate/chunks/${chunkIndex}`)
      // Reset chunk trong state về wait, clear hết
      setPass3(s => ({
        ...s,
        chunks: s.chunks.map(c => c.index !== chunkIndex ? c : {
          ...c,
          status:    'wait' as const,
          response:  '',
          prompt:    '',
          tokensIn:  0,
          tokensOut: 0,
          timingMs:  0,
          error:     '',
          entries:   [],
          qcVanDe:   null,
          qcTongKet: null,
          qcTokensIn: 0,
          qcTokensOut: 0,
          qcTimingMs: 0,
          qcModel:    '',
          qcRunAt:    '',
        }),
        done: false,
      }))
    } catch (err: any) {
      alert('Lỗi khi xóa: ' + (err?.response?.data?.detail || err?.message || 'Không xác định'))
    }
  }, [projectId])

  const handleEditCell = useCallback((chunkIndex: number, entryIndex: number, newText: string) => {
    setPass3(s => ({
      ...s,
      chunks: s.chunks.map(c => c.index === chunkIndex ? {
        ...c,
        entries: c.entries.map((e, i) => i === entryIndex ? { ...e, translated: newText } : e),
      } : c),
    }))
    // Lưu về BE
    const chunk = pass3.chunks.find(c => c.index === chunkIndex)
    if (chunk) {
      const entry = chunk.entries[entryIndex]
      if (entry) {
        api.patch(`/subtitles/by-index/${projectId}/${entry.index}`, { text: newText }).catch(() => {})
      }
    }
  }, [projectId, pass3.chunks])

  // ─── model label ────────────────────────────────────────────────────────────
  const model1Label = config.model_pass1.split('-').slice(-2).join('-') || config.model_pass1
  const model3Label = config.model_pass3.split('-').slice(-2).join('-') || config.model_pass3

  const STEPS = [
    { id: 0 as StepId, icon: '🧹', label: 'Làm sạch',     sublabel: 'Loại bỏ dòng rác' },
    { id: 1 as StepId, icon: '🎙️', label: 'Diarization', sublabel: 'Nhận diện giọng nói' },
    { id: 2 as StepId, icon: '🔍', label: 'Phân tích',    sublabel: `Pass 1 · ${model1Label}` },
    { id: 3 as StepId, icon: '🎯', label: 'Gán speaker',  sublabel: `Pass 2 · ${model1Label}` },
    { id: 4 as StepId, icon: '🌐', label: 'Dịch thuật',   sublabel: `Pass 3 · ${model3Label}` },
  ]

  return (
    <div className="flex flex-col h-screen bg-white dark:bg-zinc-950 overflow-hidden">
      {/* Top header */}
      <header className="flex items-center gap-3 px-4 h-12 border-b border-zinc-200 dark:border-zinc-800 flex-shrink-0 bg-white dark:bg-zinc-900 z-10">
        <button onClick={onBack} className="btn text-[13px]">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path d="M9 2L4 7l5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          Quay lại Editor
        </button>
        <div className="h-4 w-px bg-zinc-200 dark:bg-zinc-700" />
        <div className="text-[13px] font-semibold text-zinc-700 dark:text-zinc-200 truncate">
          {project?.name || '...'}
        </div>
        <span className="text-[11px] text-zinc-400">{subtitles.length} dòng</span>

        {/* Status badges */}
        {pass1.done && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-purple-100 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400 border border-purple-200 dark:border-purple-800">
            ✓ Bible
          </span>
        )}
        {pass3.done && (
          <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 border border-emerald-200 dark:border-emerald-800">
            ✓ Đã dịch
          </span>
        )}

        <div className="flex-1" />

        {/* Quick next step hint */}
        {!pass1.done && step < 2 && (
          <button onClick={() => setStep(2)} className="btn text-[11px] text-blue-500 border-blue-200 dark:border-blue-800">
            Bỏ qua → Phân tích ngay
          </button>
        )}
        <button onClick={() => setShowConfig(true)}
          className="btn text-[12px] flex items-center gap-1.5 flex-shrink-0">
          <svg width="13" height="13" viewBox="0 0 14 14" fill="none">
            <circle cx="7" cy="7" r="2" stroke="currentColor" strokeWidth="1.3"/>
            <path d="M7 1v1.5M7 11.5V13M1 7h1.5M11.5 7H13M2.93 2.93l1.06 1.06M10.01 10.01l1.06 1.06M2.93 11.07l1.06-1.06M10.01 3.99l1.06-1.06" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
          </svg>
          Cấu hình
        </button>
      </header>

      {showConfig && (
        <ConfigModal
          onClose={() => {
            setShowConfig(false)
            setConfig(loadConfig())  // reload config mới nhất từ localStorage
          }}
          modelStatus="unknown"
          onToggleModel={() => {}}
        />
      )}

      {/* Step tabs */}
      <StepHeader steps={STEPS} current={step} onSelect={setStep} />

      {/* Content */}
      <div className="flex-1 overflow-hidden flex flex-col min-h-0">
        {step === 0 && (
          <div className="flex-1 overflow-y-auto">
            <Step0Panel
              subs={subtitles}
              state={pass0}
              onScan={handleScan}
              onClean={handleClean}
              onSkip={() => setStep(1)}
            />
          </div>
        )}

        {step === 1 && (
          <div className="flex-1 overflow-y-auto pb-6">
            <DiarizePanel
              projectId={projectId}
              hasVideo={!!project?.video_path}
              onSkip={() => setStep(2)}
              onDone={() => setStep(2)}
            />
          </div>
        )}

        {step === 2 && (
          <div className="flex-1 overflow-y-auto pb-6">
            <Step1Panel
              state={pass1}
              modelLabel={config.model_pass1}
              totalSubs={subtitles.length}
              onRun={handleRunPass1}
              onRerun={() => setPass1(s => ({ ...s, done: false, bible: null, error: '' }))}
            />
          </div>
        )}

        {step === 3 && (
          <div className="flex-1 overflow-y-auto pb-6">
            <Pass2SpeakerPanel
              state={pass2Speaker}
              modelLabel={config.model_pass1}
              hasBible={!!pass1.bible}
              onRun={handleRunPass2Speaker}
              onSkip={() => setStep(4)}
            />
          </div>
        )}

        {step === 4 && (
          <Step2Panel
            state={pass3}
            pass1Bible={pass1.bible}
            modelName={config.model_pass3}
            projectId={projectId}
            onApplyQCFixes={(chunkIdx: number, fixedEntries: ChunkState['entries']) => {
              setPass3((s: Pass3State) => ({
                ...s,
                chunks: s.chunks.map((ch: ChunkState) =>
                  ch.index === chunkIdx ? { ...ch, entries: fixedEntries } : ch
                ),
              }))
            }}
            onQCDone={(chunkIdx, info) => {
              setPass3((s: Pass3State) => ({
                ...s,
                chunks: s.chunks.map((ch: ChunkState) =>
                  ch.index === chunkIdx
                    ? { ...ch, qcTokensIn: info.tokensIn, qcTokensOut: info.tokensOut, qcTimingMs: info.timingMs, qcModel: info.model }
                    : ch
                ),
              }))
            }}
            onStartRemaining={handleRunRemaining}
            onStartAll={handleRunAll}
            onStop={handleStop}
            onRetryChunk={handleRetryChunk}
            onDeleteChunk={handleDeleteChunk}
            onEditCell={handleEditCell}
          />
        )}
      </div>

      <style>{`
        @keyframes indeterminate {
          0%   { transform: translateX(-100%); width: 40% }
          50%  { transform: translateX(60%);  width: 60% }
          100% { transform: translateX(200%); width: 40% }
        }
      `}</style>
    </div>
  )
}