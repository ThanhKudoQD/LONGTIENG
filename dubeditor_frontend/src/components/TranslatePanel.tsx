import React, { useState, useEffect, useRef, useCallback } from 'react'
import api from '../api'
import useStore from '../store'
import type { Bible } from '../types'

// ─── Types ────────────────────────────────────────────────────────────────────

interface TranslateSettings {
  provider: 'gemini' | 'openai' | 'deepseek'
  api_key: string
  model_pass1: string
  model_pass3: string
  concurrency: number
  enable_qc: boolean
}

interface TranslateStatus {
  stage: 'idle' | 'pass1' | 'pass3' | 'done' | 'error'
  message: string
  percent: number
  chunksTotal: number
  chunksDone: number
}

interface Props {
  projectId: number
  onClose: () => void
  onDone: () => void
}

// ─── Constants ────────────────────────────────────────────────────────────────

const MODELS = {
  gemini:   ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-2.5-flash-lite'],
  openai:   ['gpt-4.1', 'gpt-4.1-mini', 'gpt-5-mini', 'gpt-4o'],
  deepseek: ['deepseek-v4-pro', 'deepseek-v4-flash'],
}

const DEFAULT_SETTINGS: TranslateSettings = {
  provider:    'gemini',
  api_key:     '',
  model_pass1: 'gemini-2.5-flash',
  model_pass3: 'gemini-2.5-flash',
  concurrency: 3,
  enable_qc:   false,
}

function loadSettings(): TranslateSettings {
  try {
    const raw = localStorage.getItem('translate_settings')
    if (raw) return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) }
  } catch {}
  return DEFAULT_SETTINGS
}

function saveSettings(s: TranslateSettings) {
  localStorage.setItem('translate_settings', JSON.stringify(s))
}

// ─── Step indicator ───────────────────────────────────────────────────────────

const STEPS = ['config', 'bible', 'translating', 'done'] as const
type Step = typeof STEPS[number]

function StepDots({ current }: { current: Step }) {
  const ci = STEPS.indexOf(current)
  return (
    <div className="flex items-center gap-1.5">
      {STEPS.map((s, i) => (
        <React.Fragment key={s}>
          <div className={`w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold transition-all ${
            i === ci
              ? 'bg-blue-600 text-white'
              : i < ci
              ? 'bg-emerald-500 text-white'
              : 'bg-zinc-200 dark:bg-zinc-700 text-zinc-400'
          }`}>
            {i < ci ? '✓' : i + 1}
          </div>
          {i < 3 && (
            <div className={`w-4 h-px ${i < ci ? 'bg-emerald-400' : 'bg-zinc-200 dark:bg-zinc-700'}`} />
          )}
        </React.Fragment>
      ))}
    </div>
  )
}

// ─── SettingsSection ──────────────────────────────────────────────────────────

function SettingsSection({
  settings, onChange, sourceLang, onSourceLang,
}: {
  settings: TranslateSettings
  onChange: (s: TranslateSettings) => void
  sourceLang: 'zh' | 'vi'
  onSourceLang: (l: 'zh' | 'vi') => void
}) {
  const models = MODELS[settings.provider]

  const set = (patch: Partial<TranslateSettings>) => {
    const next = { ...settings, ...patch }
    if (patch.provider && patch.provider !== settings.provider) {
      next.model_pass1 = MODELS[patch.provider][0]
      next.model_pass3 = MODELS[patch.provider][0]
    }
    onChange(next)
  }

  return (
    <div className="flex flex-col gap-4 p-4">

      {/* Source lang */}
      <div>
        <div className="panel-label">Ngôn ngữ gốc</div>
        <div className="flex gap-2">
          {([['zh', '🇨🇳 Tiếng Trung'], ['vi', '🇻🇳 Tiếng Việt']] as const).map(([k, label]) => (
            <button key={k} onClick={() => onSourceLang(k)}
              className={`flex-1 py-2 rounded-lg text-[12px] font-semibold border transition-all ${
                sourceLang === k
                  ? 'border-blue-500 bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400'
                  : 'border-zinc-200 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400 bg-white dark:bg-zinc-800 hover:border-zinc-300'
              }`}>
              {label}
            </button>
          ))}
        </div>
        {sourceLang === 'vi' && (
          <p className="mt-2 text-[11px] text-blue-500 bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-800 rounded-lg px-3 py-2">
            ℹ️ Tiếng Việt: Pass 1 chỉ phân tích nhân vật, không dịch.
          </p>
        )}
      </div>

      {/* Provider */}
      <div>
        <div className="panel-label">AI Provider</div>
        <div className="flex gap-2">
          {(['gemini', 'openai', 'deepseek'] as const).map(p => (
            <button key={p} onClick={() => set({ provider: p })}
              className={`flex-1 py-2 rounded-lg text-[12px] font-semibold border transition-all ${
                settings.provider === p
                  ? 'border-blue-500 bg-blue-600 text-white'
                  : 'border-zinc-200 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400 bg-white dark:bg-zinc-800 hover:border-zinc-300'
              }`}>
              {p === 'gemini' ? 'Gemini' : p === 'openai' ? 'OpenAI' : 'DeepSeek'}
            </button>
          ))}
        </div>
      </div>

      {/* API Key */}
      <div>
        <div className="panel-label">
          API Key — {settings.provider === 'gemini' ? 'Gemini' : settings.provider === 'openai' ? 'OpenAI' : 'DeepSeek'}
        </div>
        <input
          type="password"
          value={settings.api_key}
          onChange={e => set({ api_key: e.target.value })}
          placeholder="Nhập API key..."
          className="input w-full font-mono text-[12px]"
        />
      </div>

      {/* Models */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <div className="panel-label">Model — Pass 1 (phân tích)</div>
          <select value={settings.model_pass1}
            onChange={e => set({ model_pass1: e.target.value })}
            className="input w-full text-[12px]">
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
        <div>
          <div className="panel-label">Model — Pass 3 (dịch)</div>
          <select value={settings.model_pass3}
            onChange={e => set({ model_pass3: e.target.value })}
            className="input w-full text-[12px]">
            {models.map(m => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>
      </div>

      {/* Concurrency + QC */}
      <div className="flex items-end gap-4">
        <div className="flex-1">
          <div className="panel-label">Dịch song song — {settings.concurrency} chunks</div>
          <input type="range" min={1} max={8} value={settings.concurrency}
            onChange={e => set({ concurrency: Number(e.target.value) })}
            className="w-full accent-blue-600" />
        </div>
        <label className="flex items-center gap-2 pb-1 cursor-pointer select-none">
          <input type="checkbox" checked={settings.enable_qc}
            onChange={e => set({ enable_qc: e.target.checked })}
            className="w-4 h-4 accent-blue-600" />
          <span className="text-[12px] text-zinc-500 dark:text-zinc-400">QC review</span>
        </label>
      </div>
    </div>
  )
}

// ─── BibleView ────────────────────────────────────────────────────────────────

const VAI_MAP: Record<string, string> = {
  nu_chinh: 'Nữ chính', nam_chinh: 'Nam chính', phu: 'Phụ', phan_dien: 'Phản diện',
}
const VAI_CLS: Record<string, string> = {
  nu_chinh:  'text-pink-500 bg-pink-50 dark:bg-pink-950/40',
  nam_chinh: 'text-blue-500 bg-blue-50 dark:bg-blue-950/40',
  phu:       'text-purple-500 bg-purple-50 dark:bg-purple-950/40',
  phan_dien: 'text-red-500 bg-red-50 dark:bg-red-950/40',
}

function BibleView({ bible }: { bible: Bible }) {
  const [tab, setTab] = useState<'chars' | 'story' | 'terms'>('chars')
  const charCount = bible.nhan_vat?.length || 0
  const termCount = Object.keys(bible.thuat_ngu || {}).length

  return (
    <div className="flex flex-col gap-3">
      {bible.the_loai && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800">
          <span className="text-[11px] font-bold text-amber-600 dark:text-amber-400 uppercase tracking-widest">
            {bible.the_loai.boi_canh?.replace('_', ' ')}
          </span>
          {bible.the_loai.ghi_chu_dich && (
            <span className="text-[11px] text-amber-600/70 dark:text-amber-400/70 truncate">
              — {bible.the_loai.ghi_chu_dich}
            </span>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex border-b border-zinc-200 dark:border-zinc-700">
        {([
          ['chars', `Nhân vật (${charCount})`],
          ['story', 'Cốt truyện'],
          ['terms', `Thuật ngữ (${termCount})`],
        ] as const).map(([key, label]) => (
          <button key={key} onClick={() => setTab(key)}
            className={`px-3 py-2 text-[12px] font-semibold border-b-2 transition-all -mb-px ${
              tab === key
                ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'chars' && (
        <div className="flex flex-col gap-2">
          {(bible.nhan_vat || []).map((c, i) => (
            <div key={i} className="px-3 py-2.5 rounded-lg bg-zinc-50 dark:bg-zinc-800/60 border border-zinc-100 dark:border-zinc-700/50">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[13px] font-bold text-zinc-800 dark:text-zinc-100">{c.vi}</span>
                <span className="text-[11px] text-zinc-400">{c.zh}</span>
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${VAI_CLS[c.vai] || 'text-zinc-500 bg-zinc-100'}`}>
                  {VAI_MAP[c.vai] || c.vai}
                </span>
              </div>
              <div className="text-[11px] text-zinc-400 mt-0.5 truncate">{c.than_phan}</div>
              {c.tu_xung && (
                <div className="text-[11px] text-zinc-500 mt-0.5">
                  Tự xưng: <span className="font-semibold text-blue-500">{c.tu_xung}</span>
                </div>
              )}
            </div>
          ))}
          {charCount === 0 && (
            <p className="text-center text-zinc-400 text-[12px] py-6">Chưa có dữ liệu nhân vật</p>
          )}
        </div>
      )}

      {tab === 'story' && (
        <p className="text-[12px] text-zinc-600 dark:text-zinc-300 leading-relaxed">
          {bible.story_arc?.tom_tat_phim || 'Chưa có tóm tắt.'}
        </p>
      )}

      {tab === 'terms' && (
        <div className="flex flex-col gap-1.5">
          {Object.entries(bible.thuat_ngu || {}).map(([zh, vi]) => (
            <div key={zh} className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-zinc-50 dark:bg-zinc-800/60 text-[12px]">
              <span className="text-zinc-400 flex-1">{zh}</span>
              <span className="text-zinc-300 dark:text-zinc-600">→</span>
              <span className="font-semibold text-zinc-700 dark:text-zinc-200">{vi}</span>
            </div>
          ))}
          {termCount === 0 && (
            <p className="text-center text-zinc-400 text-[12px] py-6">Không có thuật ngữ đặc thù</p>
          )}
        </div>
      )}
    </div>
  )
}

// ─── ProgressBlock ────────────────────────────────────────────────────────────

function ProgressBlock({ status }: { status: TranslateStatus }) {
  const isDone  = status.stage === 'done'
  const isError = status.stage === 'error'
  return (
    <div className="rounded-xl border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/60 p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between">
        <span className="text-[13px] font-semibold text-zinc-700 dark:text-zinc-200">
          {isDone ? '🎉 Hoàn tất!' : isError ? '❌ Lỗi' : '🔄 Đang dịch...'}
        </span>
        {status.chunksTotal > 0 && (
          <span className="text-[12px] text-zinc-400 font-mono tabular-nums">
            {status.chunksDone}/{status.chunksTotal} chunks
          </span>
        )}
      </div>
      <div className="h-1.5 rounded-full bg-zinc-200 dark:bg-zinc-700 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all duration-300 ${isDone ? 'bg-emerald-500' : isError ? 'bg-red-500' : 'bg-blue-500'}`}
          style={{ width: `${Math.max(0, Math.min(100, status.percent))}%` }}
        />
      </div>
      <p className={`text-[11px] leading-snug ${isError ? 'text-red-500' : 'text-zinc-400'}`}>
        {status.message}
      </p>
    </div>
  )
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export default function TranslatePanel({ projectId, onClose, onDone }: Props) {
  const project     = useStore(s => s.project)

  const [settings, setSettings]     = useState<TranslateSettings>(loadSettings)
  const [sourceLang, setSourceLang] = useState<'zh' | 'vi'>('zh')
  const [step, setStep]             = useState<Step>('config')
  const [bible, setBible]           = useState<Bible | null>(null)
  const [status, setStatus]         = useState<TranslateStatus>({
    stage: 'idle', message: '', percent: 0, chunksTotal: 0, chunksDone: 0,
  })
  const [loadingBible, setLoadingBible]     = useState(false)
  const [retranslating, setRetranslating]   = useState(false)
  const esRef = useRef<EventSource | null>(null)

  // Load Bible nếu đã có
  useEffect(() => {
    api.get(`/projects/${projectId}/bible`)
      .then(r => {
        if (r.data?.bible) {
          setBible(r.data.bible)
          if (r.data.source_lang) setSourceLang(r.data.source_lang)
          setStep('bible')
        }
      })
      .catch(() => {})
  }, [projectId])

  useEffect(() => { saveSettings(settings) }, [settings])
  useEffect(() => () => { esRef.current?.close() }, [])

  const handleRunPass1 = useCallback(async () => {
    if (!settings.api_key.trim()) { alert('Vui lòng nhập API key!'); return }
    setLoadingBible(true)
    setStatus({ stage: 'pass1', message: 'Đang phân tích phim...', percent: 10, chunksTotal: 0, chunksDone: 0 })
    try {
      const res = await api.post(`/projects/${projectId}/translate/analyze`, {
        api_key: settings.api_key, model: settings.model_pass1, source_lang: sourceLang,
      })
      setBible(res.data.bible)
      setStep('bible')
      setStatus(s => ({ ...s, stage: 'idle', message: 'Phân tích xong!', percent: 100 }))
    } catch (err: any) {
      setStatus(s => ({ ...s, stage: 'error', message: err?.response?.data?.detail || err?.message || 'Lỗi Pass 1' }))
    } finally {
      setLoadingBible(false)
    }
  }, [projectId, settings, sourceLang])

  const handleRunPass3 = useCallback(async () => {
    if (!bible) return
    setStep('translating')
    setStatus({ stage: 'pass3', message: 'Bắt đầu dịch...', percent: 0, chunksTotal: 0, chunksDone: 0 })
    try {
      await api.post(`/projects/${projectId}/translate/run`, {
        api_key: settings.api_key, model: settings.model_pass3,
        concurrency: settings.concurrency, enable_qc: settings.enable_qc,
      })
      const es = new EventSource(`/dub/api/projects/${projectId}/translate/progress`)
      esRef.current = es
      es.addEventListener('progress', (e: MessageEvent) => {
        const d = JSON.parse(e.data)
        setStatus({ stage: d.stage || 'pass3', message: d.message || '', percent: d.percent || 0, chunksTotal: d.chunks_total || 0, chunksDone: d.chunks_done || 0 })
        if (d.stage === 'done')  { es.close(); setStep('done'); onDone() }
        if (d.stage === 'error') { es.close() }
      })
      es.onerror = () => { es.close(); setStatus(s => ({ ...s, stage: 'error', message: 'Mất kết nối SSE' })) }
    } catch (err: any) {
      setStatus(s => ({ ...s, stage: 'error', message: err?.response?.data?.detail || err?.message || 'Lỗi Pass 3' }))
    }
  }, [projectId, settings, bible, onDone])

  const handleStop = () => {
    esRef.current?.close()
    api.post(`/projects/${projectId}/translate/cancel`).catch(() => {})
    setStep('bible')
    setStatus(s => ({ ...s, stage: 'idle', message: 'Đã hủy.' }))
  }

  const handleRetranslate = async () => {
    if (!confirm('Dịch lại toàn bộ? Bản dịch hiện tại sẽ bị xoá.')) return
    setRetranslating(true)
    try {
      await api.post(`/projects/${projectId}/translate/reset`)
      setStep('bible')
      setStatus({ stage: 'idle', message: '', percent: 0, chunksTotal: 0, chunksDone: 0 })
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Lỗi reset')
    } finally { setRetranslating(false) }
  }

  return (
    <div className="fixed inset-0 z-[9000] flex items-start justify-end">
      {/* Backdrop */}
      <div onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Drawer */}
      <div
        className="relative z-10 flex flex-col h-screen bg-white dark:bg-zinc-900 border-l border-zinc-200 dark:border-zinc-800 shadow-2xl"
        style={{ width: 420, animation: 'slideInRight .2s ease' }}
      >
        {/* Header */}
        <div className="flex items-center gap-3 px-4 py-3 border-b border-zinc-200 dark:border-zinc-800 flex-shrink-0">
          <div className="flex-1 min-w-0">
            <div className="text-[14px] font-bold text-zinc-800 dark:text-zinc-100">Dịch thuật AI</div>
            <div className="text-[11px] text-zinc-400 mt-0.5 truncate">
              {project?.name} · {project?.subtitle_count || 0} dòng
            </div>
          </div>
          <StepDots current={step} />
          <button onClick={onClose}
            className="w-7 h-7 rounded-lg border border-zinc-200 dark:border-zinc-700 flex items-center justify-center text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 text-[16px] transition-colors flex-shrink-0 bg-white dark:bg-zinc-800">
            ×
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto">

          {/* Config step */}
          {step === 'config' && (
            <>
              <SettingsSection
                settings={settings} onChange={setSettings}
                sourceLang={sourceLang} onSourceLang={setSourceLang}
              />
              {status.stage === 'error' && (
                <div className="mx-4 mb-2 px-3 py-2.5 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-[12px] text-red-500">
                  ❌ {status.message}
                </div>
              )}
              {status.stage === 'pass1' && (
                <div className="mx-4 mb-2">
                  <ProgressBlock status={status} />
                </div>
              )}
            </>
          )}

          {/* Bible + translating + done */}
          {(step === 'bible' || step === 'translating' || step === 'done') && (
            <div className="flex flex-col gap-4 p-4">
              {/* Bible banner */}
              {bible && (
                <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-emerald-50 dark:bg-emerald-950/30 border border-emerald-200 dark:border-emerald-800">
                  <span className="text-base">✅</span>
                  <div className="flex-1 min-w-0">
                    <div className="text-[12px] font-bold text-emerald-700 dark:text-emerald-400">Bible đã sẵn sàng</div>
                    <div className="text-[11px] text-emerald-600/70 dark:text-emerald-500">
                      {bible.nhan_vat?.length || 0} nhân vật · {bible.scene_map?.length || 0} cảnh · {Object.keys(bible.thuat_ngu || {}).length} thuật ngữ
                    </div>
                  </div>
                  {step === 'bible' && (
                    <button onClick={() => setStep('config')}
                      className="text-[11px] text-zinc-400 border border-zinc-200 dark:border-zinc-700 rounded-md px-2 py-1 bg-white dark:bg-zinc-800 hover:text-zinc-600 transition-colors flex-shrink-0">
                      Chỉnh sửa
                    </button>
                  )}
                </div>
              )}

              {/* Bible content */}
              {bible && <BibleView bible={bible} />}

              {/* Progress */}
              {(step === 'translating' || (step === 'done' && status.chunksTotal > 0)) && (
                <ProgressBlock status={status} />
              )}

              {/* Done extras */}
              {step === 'done' && (
                <div className="flex flex-col gap-2">
                  <p className="text-[12px] text-zinc-400 text-center">
                    {status.chunksTotal} chunks · Nhân vật đã gán tự động từ Bible
                  </p>
                  <button onClick={handleRetranslate} disabled={retranslating}
                    className="btn w-full justify-center text-red-400 border-red-200 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-950/30 disabled:opacity-50">
                    {retranslating ? '...' : '🔁 Dịch lại từ đầu'}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-zinc-200 dark:border-zinc-800 flex-shrink-0 flex gap-2">
          {step === 'config' && (
            <>
              <button onClick={onClose} className="btn flex-shrink-0">Huỷ</button>
              <button onClick={handleRunPass1} disabled={loadingBible}
                className="btn-primary flex-1 justify-center gap-2 disabled:opacity-60">
                {loadingBible
                  ? <><div className="w-3.5 h-3.5 rounded-full border-2 border-white border-t-transparent animate-spin" /> Đang phân tích...</>
                  : '🔍 Pass 1 — Phân tích phim'}
              </button>
            </>
          )}

          {step === 'bible' && (
            <>
              <button onClick={() => setStep('config')} className="btn flex-shrink-0">← Cài đặt</button>
              <button onClick={handleRunPass3} className="btn-primary flex-1 justify-center">
                🚀 Pass 3 — Bắt đầu dịch
              </button>
            </>
          )}

          {step === 'translating' && (
            <button onClick={handleStop}
              className="flex-1 py-2 rounded-lg border border-red-200 dark:border-red-800 text-[13px] font-bold text-red-500 bg-transparent hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors">
              ⏹ Dừng dịch
            </button>
          )}

          {step === 'done' && (
            <button onClick={onClose}
              className="btn-primary flex-1 justify-center bg-emerald-500 hover:bg-emerald-600">
              ✓ Đóng — Vào Editor
            </button>
          )}
        </div>
      </div>

      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(40px); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
      `}</style>
    </div>
  )
}