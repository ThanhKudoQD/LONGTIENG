/**
 * ConfigModal.tsx
 * Modal cấu hình gộp: API Keys + Model selector (có giá) + TTS + Auto TTS
 */
import React, { useState, useEffect } from 'react'
import useStore from '../store'

// ─── Model data với giá ───────────────────────────────────────────────────────

interface ModelInfo {
  id: string
  provider: 'gemini' | 'openai' | 'deepseek'
  label: string
  ctx: string
  priceIn: string
  priceOut: string
  note: string
  recommended?: boolean
}

const MODELS_PASS1: ModelInfo[] = [
  { id: 'gemini-2.5-pro',        provider: 'gemini',   label: '2.5 Pro',        ctx: '1M',   priceIn: '$1.25', priceOut: '$10.00', note: 'Mạnh nhất — lý tưởng Pass 1', recommended: true },
  { id: 'gemini-2.5-flash',      provider: 'gemini',   label: '2.5 Flash',      ctx: '1M',   priceIn: '$0.30', priceOut: '$2.50',  note: 'Cân bằng, có thinking' },
  { id: 'gemini-2.5-flash-lite', provider: 'gemini',   label: '2.5 Flash Lite', ctx: '1M',   priceIn: '$0.10', priceOut: '$0.40',  note: 'Rẻ nhất Gemini' },
  { id: 'gpt-4.1',               provider: 'openai',   label: 'GPT-4.1',        ctx: '1M',   priceIn: '$2.00', priceOut: '$8.00',  note: 'Instruction following tốt' },
  { id: 'gpt-4.1-mini',          provider: 'openai',   label: 'GPT-4.1 mini',   ctx: '1M',   priceIn: '$0.40', priceOut: '$1.60',  note: 'Cân bằng giá/chất lượng' },
  { id: 'gpt-5-mini',            provider: 'openai',   label: 'GPT-5 mini',     ctx: '400K', priceIn: '$0.20', priceOut: '$0.80',  note: 'Thông minh hơn 4.1-mini' },
  { id: 'gpt-5-nano',            provider: 'openai',   label: 'GPT-5 nano',     ctx: '400K', priceIn: '$0.05', priceOut: '$0.40',  note: 'Rẻ nhất OpenAI ⚡' },
  { id: 'deepseek-v4-pro',           provider: 'deepseek', label: 'V4 Pro',             ctx: '1M',   priceIn: '$0.27', priceOut: '$1.10',  note: 'Tốt cho văn bản Trung' },
  { id: 'deepseek-v4-flash',         provider: 'deepseek', label: 'V4 Flash',           ctx: '1M',   priceIn: '$0.14', priceOut: '$0.28',  note: 'Rẻ, nhanh 💰' },
]

const MODELS_PASS3: ModelInfo[] = [
  { id: 'gemini-2.5-flash',      provider: 'gemini',   label: '2.5 Flash',      ctx: '1M',   priceIn: '$0.30', priceOut: '$2.50',  note: 'Khuyến nghị', recommended: true },
  { id: 'gemini-2.5-flash-lite', provider: 'gemini',   label: '2.5 Flash Lite', ctx: '1M',   priceIn: '$0.10', priceOut: '$0.40',  note: 'Rẻ nhất Gemini' },
  { id: 'gemini-2.5-pro',        provider: 'gemini',   label: '2.5 Pro',        ctx: '1M',   priceIn: '$1.25', priceOut: '$10.00', note: 'Chất lượng tối đa' },
  { id: 'gpt-4.1',               provider: 'openai',   label: 'GPT-4.1',        ctx: '1M',   priceIn: '$2.00', priceOut: '$8.00',  note: 'Chất lượng cao nhất' },
  { id: 'gpt-4.1-mini',          provider: 'openai',   label: 'GPT-4.1 mini',   ctx: '1M',   priceIn: '$0.40', priceOut: '$1.60',  note: 'Cân bằng' },
  { id: 'gpt-4.1-nano',          provider: 'openai',   label: 'GPT-4.1 nano',   ctx: '1M',   priceIn: '$0.10', priceOut: '$0.40',  note: 'Rẻ, ctx 1M' },
  { id: 'gpt-5-nano',            provider: 'openai',   label: 'GPT-5 nano',     ctx: '400K', priceIn: '$0.05', priceOut: '$0.40',  note: 'Rẻ nhất OpenAI ⚡' },
  { id: 'deepseek-v4-flash',         provider: 'deepseek', label: 'V4 Flash',           ctx: '1M',   priceIn: '$0.14', priceOut: '$0.28',  note: 'Rẻ nhất thị trường 💰' },
  { id: 'deepseek-v4-pro',           provider: 'deepseek', label: 'V4 Pro',             ctx: '1M',   priceIn: '$0.27', priceOut: '$1.10',  note: 'Cân bằng' },
]

const PROV_TABS = [
  { id: 'gemini',   label: 'Gemini',   color: '#1a73e8' },
  { id: 'openai',   label: 'OpenAI',   color: '#10a37f' },
  { id: 'deepseek', label: 'DeepSeek', color: '#4f6eff' },
] as const

// ─── Types ────────────────────────────────────────────────────────────────────

export interface TranslateConfig {
  // API keys
  gemini_key:   string
  openai_key:   string
  deepseek_key: string
  // Models
  model_pass1:        string
  model_pass3:        string
  model_retranslate:  string   // model dùng cho "Dịch lại" từng dòng
  // Chunking
  concurrency: number
  // QC Review (Pass 4) — auto-apply settings
  qc_auto_apply_text:          boolean         // tự động áp dụng sửa văn phong / xưng hô / từ
  qc_auto_apply_speaker:       boolean         // tự động đổi nhân vật khi Pass 4 đề xuất
  qc_speaker_min_confidence:   'cao' | 'trung' // ngưỡng tin cậy tối thiểu để auto-apply speaker
}

const DEFAULT_CONFIG: TranslateConfig = {
  gemini_key:   '',
  openai_key:   '',
  deepseek_key: '',
  model_pass1:        'gemini-2.5-flash',
  model_pass3:        'gemini-2.5-flash',
  model_retranslate:  'gemini-2.5-flash',
  concurrency:  3,
  qc_auto_apply_text:        true,
  qc_auto_apply_speaker:     true,
  qc_speaker_min_confidence: 'cao',
}

export function loadConfig(): TranslateConfig {
  try {
    const raw = localStorage.getItem('dub_translate_config')
    if (raw) return { ...DEFAULT_CONFIG, ...JSON.parse(raw) }
  } catch {}
  return DEFAULT_CONFIG
}

export function saveConfig(c: TranslateConfig) {
  localStorage.setItem('dub_translate_config', JSON.stringify(c))
}

export function getApiKey(config: TranslateConfig, model: string): string {
  const m = model.toLowerCase()
  if (m.startsWith('gemini')) return config.gemini_key
  if (m.startsWith('deepseek')) return config.deepseek_key
  return config.openai_key
}

// ─── ModelSelector ────────────────────────────────────────────────────────────

function ModelSelector({
  models, value, onChange, label,
}: {
  models: ModelInfo[]
  value: string
  onChange: (id: string) => void
  label: string
}) {
  const currentProv = (models.find(m => m.id === value)?.provider) ?? 'gemini'
  const [tab, setTab] = useState<'gemini' | 'openai' | 'deepseek'>(currentProv)
  const filtered = models.filter(m => m.provider === tab)
  const availableProvs = [...new Set(models.map(m => m.provider))]

  const COLORS: Record<string, string> = { gemini: '#1a73e8', openai: '#10a37f', deepseek: '#4f6eff' }
  const color = COLORS[tab]

  return (
    <div>
      <div className="panel-label">{label}</div>

      {/* Provider tabs */}
      <div className="flex gap-1.5 mb-3">
        {PROV_TABS.filter(p => availableProvs.includes(p.id)).map(p => (
          <button key={p.id} onClick={() => setTab(p.id)}
            className={`px-3 py-1 rounded-md text-[11px] font-semibold border transition-all ${
              tab === p.id
                ? 'text-white border-transparent'
                : 'bg-white dark:bg-zinc-800 text-zinc-500 border-zinc-200 dark:border-zinc-700 hover:border-zinc-300'
            }`}
            style={tab === p.id ? { background: p.color, borderColor: p.color } : {}}>
            {p.label}
          </button>
        ))}
      </div>

      {/* Model cards grid */}
      <div className="grid grid-cols-2 gap-2">
        {filtered.map(m => {
          const sel = value === m.id
          return (
            <button key={m.id} onClick={() => onChange(m.id)}
              className={`text-left p-2.5 rounded-lg border transition-all ${
                sel
                  ? 'border-[2px]'
                  : 'border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:border-zinc-300 dark:hover:border-zinc-600'
              }`}
              style={sel ? { borderColor: color, background: color + '10' } : {}}>
              {/* Top row */}
              <div className="flex items-start justify-between gap-1 mb-1">
                <span className="text-[11px] font-bold font-mono"
                  style={{ color: sel ? color : undefined }}>
                  {m.label}
                </span>
                <span className="text-[9px] px-1 py-0.5 rounded bg-zinc-100 dark:bg-zinc-700 text-zinc-400 font-mono flex-shrink-0">
                  {m.ctx}
                </span>
              </div>
              {/* Price */}
              <div className="flex items-center gap-1 mb-1">
                <span className="text-[10px] font-mono text-blue-500">↑{m.priceIn}</span>
                <span className="text-[10px] text-zinc-300 dark:text-zinc-600">·</span>
                <span className="text-[10px] font-mono text-emerald-500">↓{m.priceOut}</span>
                <span className="text-[9px] text-zinc-300 dark:text-zinc-600 ml-0.5">/1M</span>
              </div>
              {/* Note */}
              <div className="text-[10px] text-zinc-400 leading-snug">
                {m.recommended && <span className="text-amber-500 mr-1">★</span>}
                {m.note}
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}

// ─── ApiKeyInput ──────────────────────────────────────────────────────────────

function ApiKeyInput({
  label, value, onChange, placeholder, hint, link,
}: {
  label: string; value: string; onChange: (v: string) => void
  placeholder: string; hint: string; link: string
}) {
  const [show, setShow] = useState(false)
  const masked = value ? value.slice(0, 8) + '••••••••' + value.slice(-4) : ''

  return (
    <div>
      <div className="flex items-center gap-2 mb-1.5">
        <span className="panel-label mb-0">{label}</span>
        <a href={link} target="_blank" rel="noreferrer"
          className="text-[10px] text-blue-500 hover:underline ml-auto">
          Lấy key →
        </a>
      </div>
      <div className="relative">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder}
          className="input w-full font-mono text-[12px] pr-16"
        />
        <button onClick={() => setShow(v => !v)}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-[10px] text-zinc-400 hover:text-zinc-600 px-1.5 py-0.5 rounded border border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800">
          {show ? 'Ẩn' : 'Hiện'}
        </button>
      </div>
      {value && (
        <div className="text-[10px] text-emerald-500 mt-1 font-mono">✓ {masked}</div>
      )}
      <div className="text-[10px] text-zinc-400 mt-1">{hint}</div>
    </div>
  )
}

// ─── Main ─────────────────────────────────────────────────────────────────────

interface Props {
  onClose: () => void
  modelStatus: 'unknown' | 'loaded' | 'loading' | 'unloaded'
  onToggleModel: () => void
}

export default function ConfigModal({ onClose, modelStatus, onToggleModel }: Props) {
  const autoTTS    = useStore(s => s.autoTTS)
  const setAutoTTS = useStore(s => s.setAutoTTS)

  const [config, setConfig] = useState<TranslateConfig>(loadConfig)
  const [saved,  setSaved]  = useState(false)
  const [tab,    setTab]    = useState<'api' | 'model' | 'qc' | 'tts'>('api')

  const set = (patch: Partial<TranslateConfig>) => setConfig(c => ({ ...c, ...patch }))

  const handleSave = () => {
    saveConfig(config)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }

  return (
    <div className="fixed inset-0 z-[9500] flex items-center justify-center">
      {/* Backdrop */}
      <div onClick={onClose} className="absolute inset-0 bg-black/50 backdrop-blur-sm" />

      {/* Modal */}
      <div className="relative z-10 w-[680px] max-h-[88vh] bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-700 shadow-2xl flex flex-col overflow-hidden">

        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-zinc-200 dark:border-zinc-800 flex-shrink-0">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-zinc-500">
            <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.22 3.22l1.41 1.41M11.37 11.37l1.41 1.41M3.22 12.78l1.41-1.41M11.37 4.63l1.41-1.41" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
            <circle cx="8" cy="8" r="2.5" stroke="currentColor" strokeWidth="1.5"/>
          </svg>
          <div className="text-[14px] font-bold text-zinc-800 dark:text-zinc-100">Cấu hình</div>
          <button onClick={onClose}
            className="ml-auto w-7 h-7 rounded-lg border border-zinc-200 dark:border-zinc-700 flex items-center justify-center text-zinc-400 hover:text-zinc-600 text-[16px] bg-white dark:bg-zinc-800 transition-colors">
            ×
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-zinc-200 dark:border-zinc-800 flex-shrink-0 px-5">
          {([
            ['api',   '🔑 API Keys'],
            ['model', '🤖 Models'],
            ['qc',    '🔍 QC Review'],
            ['tts',   '🔊 TTS & Editor'],
          ] as const).map(([key, label]) => (
            <button key={key} onClick={() => setTab(key)}
              className={`px-4 py-2.5 text-[12px] font-semibold border-b-2 transition-all -mb-px ${
                tab === key
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300'
              }`}>
              {label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-5 flex flex-col gap-6">

          {/* ── API Keys ── */}
          {tab === 'api' && (
            <>
              <ApiKeyInput
                label="Gemini API Key"
                value={config.gemini_key}
                onChange={v => set({ gemini_key: v })}
                placeholder="AIza..."
                hint="Dùng cho model Gemini 2.5 Flash/Pro"
                link="https://aistudio.google.com/apikey"
              />
              <div className="border-t border-zinc-100 dark:border-zinc-800" />
              <ApiKeyInput
                label="OpenAI API Key"
                value={config.openai_key}
                onChange={v => set({ openai_key: v })}
                placeholder="sk-proj-..."
                hint="Dùng cho GPT-4.1, GPT-5 nano/mini"
                link="https://platform.openai.com/api-keys"
              />
              <div className="border-t border-zinc-100 dark:border-zinc-800" />
              <ApiKeyInput
                label="DeepSeek API Key"
                value={config.deepseek_key}
                onChange={v => set({ deepseek_key: v })}
                placeholder="sk-..."
                hint="Dùng cho DeepSeek V3 / Chat — rẻ nhất"
                link="https://platform.deepseek.com/api_keys"
              />
            </>
          )}

          {/* ── Models ── */}
          {tab === 'model' && (
            <>
              <div className="text-[11px] text-zinc-400 bg-zinc-50 dark:bg-zinc-800 rounded-lg px-3 py-2 border border-zinc-200 dark:border-zinc-700">
                Giá hiển thị per 1M tokens: <span className="text-blue-500 font-mono">↑ input</span> · <span className="text-emerald-500 font-mono">↓ output</span>
              </div>

              <ModelSelector
                label="MODEL — PASS 1 (Phân tích phim · chạy 1 lần)"
                models={MODELS_PASS1}
                value={config.model_pass1}
                onChange={v => set({ model_pass1: v })}
              />

              <div className="border-t border-zinc-100 dark:border-zinc-800" />

              <ModelSelector
                label="MODEL — PASS 3 (Dịch từng chunk · chạy nhiều lần)"
                models={MODELS_PASS3}
                value={config.model_pass3}
                onChange={v => set({ model_pass3: v })}
              />

              <div className="border-t border-zinc-100 dark:border-zinc-800" />

              <ModelSelector
                label="MODEL — DỊCH LẠI (từng dòng trong Editor)"
                models={MODELS_PASS3}
                value={config.model_retranslate}
                onChange={v => set({ model_retranslate: v })}
              />

              <div className="border-t border-zinc-100 dark:border-zinc-800" />

              <div>
                <div className="panel-label">Dịch song song — {config.concurrency} chunks cùng lúc</div>
                <div className="flex items-center gap-3">
                  <input type="range" min={1} max={8} value={config.concurrency}
                    onChange={e => set({ concurrency: Number(e.target.value) })}
                    className="flex-1 accent-blue-600" />
                  <span className="text-[13px] font-bold text-blue-500 w-5 text-center">
                    {config.concurrency}
                  </span>
                </div>
                <p className="text-[11px] text-zinc-400 mt-1">
                  Cao → nhanh hơn nhưng tốn quota API nhiều hơn. Khuyến nghị: 3
                </p>
              </div>
            </>
          )}

          {/* ── QC Review (Pass 4) ── */}
          {tab === 'qc' && (
            <div className="flex flex-col gap-5">
              <div>
                <div className="panel-label">Tự động áp dụng sửa từ Pass 4</div>
                <p className="text-[11px] text-zinc-400 mb-3">
                  Khi bật, các sửa đổi từ Pass 4 (QC Review) sẽ được áp dụng ngay sau khi review xong.
                  Khi tắt, bạn phải duyệt thủ công từng dòng.
                </p>

                {/* Toggle: auto-apply text */}
                <label className="flex items-center gap-3 p-3 rounded-lg border border-zinc-200 dark:border-zinc-700 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/60 transition-colors mb-2">
                  <div className={`relative w-9 h-5 rounded-full transition-colors flex-shrink-0 ${config.qc_auto_apply_text ? 'bg-blue-500' : 'bg-zinc-300 dark:bg-zinc-600'}`}>
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${config.qc_auto_apply_text ? 'translate-x-4' : 'translate-x-0.5'}`} />
                  </div>
                  <div className="flex-1">
                    <div className="text-[13px] font-medium text-zinc-700 dark:text-zinc-200">
                      Áp dụng sửa văn phong / xưng hô / từ
                    </div>
                    <div className="text-[11px] text-zinc-400">
                      Sửa câu dịch theo gợi ý của Pass 4 (không đổi nhân vật)
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={config.qc_auto_apply_text}
                    onChange={e => set({ qc_auto_apply_text: e.target.checked })}
                    className="sr-only"
                  />
                </label>

                {/* Toggle: auto-apply speaker */}
                <label className="flex items-center gap-3 p-3 rounded-lg border border-zinc-200 dark:border-zinc-700 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/60 transition-colors">
                  <div className={`relative w-9 h-5 rounded-full transition-colors flex-shrink-0 ${config.qc_auto_apply_speaker ? 'bg-blue-500' : 'bg-zinc-300 dark:bg-zinc-600'}`}>
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${config.qc_auto_apply_speaker ? 'translate-x-4' : 'translate-x-0.5'}`} />
                  </div>
                  <div className="flex-1">
                    <div className="text-[13px] font-medium text-zinc-700 dark:text-zinc-200">
                      Áp dụng đổi nhân vật (speaker)
                    </div>
                    <div className="text-[11px] text-zinc-400">
                      Pass 4 phát hiện sai nhân vật → tự đổi character cho subtitle
                    </div>
                  </div>
                  <input
                    type="checkbox"
                    checked={config.qc_auto_apply_speaker}
                    onChange={e => set({ qc_auto_apply_speaker: e.target.checked })}
                    className="sr-only"
                  />
                </label>
              </div>

              {/* Min confidence radio — chỉ hiện khi auto-apply speaker bật */}
              {config.qc_auto_apply_speaker && (
                <div className="border-t border-zinc-100 dark:border-zinc-800 pt-4">
                  <div className="panel-label">Mức tin cậy tối thiểu để đổi speaker</div>
                  <p className="text-[11px] text-zinc-400 mb-3">
                    Pass 4 chấm độ tin cậy cho mỗi đề xuất đổi nhân vật. Đặt ngưỡng cao = an toàn hơn nhưng có thể bỏ sót.
                  </p>
                  <div className="flex gap-2">
                    {([
                      ['cao',   '🟢 Chỉ "cao"',         'An toàn — chỉ apply khi Pass 4 chắc chắn'],
                      ['trung', '🟡 "cao" + "trung"',   'Mạnh tay — apply cả các đề xuất tin cậy trung bình'],
                    ] as const).map(([val, label, hint]) => (
                      <label key={val}
                        className={`flex-1 p-3 rounded-lg border cursor-pointer transition-all ${
                          config.qc_speaker_min_confidence === val
                            ? 'border-blue-400 bg-blue-50 dark:bg-blue-950/20'
                            : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300'
                        }`}>
                        <input type="radio" name="qc_min_conf" value={val}
                          checked={config.qc_speaker_min_confidence === val}
                          onChange={() => set({ qc_speaker_min_confidence: val })}
                          className="sr-only" />
                        <div className="text-[12px] font-semibold text-zinc-700 dark:text-zinc-200">{label}</div>
                        <div className="text-[10px] text-zinc-400 mt-1 leading-snug">{hint}</div>
                      </label>
                    ))}
                  </div>
                </div>
              )}

              {/* Info box */}
              <div className="rounded-lg border border-blue-200 dark:border-blue-900 bg-blue-50 dark:bg-blue-950/20 p-3">
                <div className="text-[11px] text-blue-700 dark:text-blue-300 leading-relaxed">
                  💡 <strong>Pass 4</strong> kiểm tra 4 trục: speaker (ai nói), văn phong, xưng hô, tên/thuật ngữ/cường độ.
                  Mỗi đề xuất sửa kèm bằng chứng cụ thể và mức tin cậy. Đề xuất tin cậy "thấp" tự động bị bỏ qua.
                </div>
              </div>
            </div>
          )}

          {/* ── TTS & Editor ── */}
          {tab === 'tts' && (
            <div className="flex flex-col gap-5">
              {/* Model TTS */}
              <div>
                <div className="panel-label">VoxCPM2 Model (TTS)</div>
                <div className={`flex items-center gap-3 p-3 rounded-lg border transition-all ${
                  modelStatus === 'loaded'
                    ? 'border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-950/20'
                    : modelStatus === 'loading'
                    ? 'border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/20'
                    : 'border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/60'
                }`}>
                  <div className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${
                    modelStatus === 'loaded' ? 'bg-emerald-500' :
                    modelStatus === 'loading' ? 'bg-amber-400 animate-pulse' :
                    'bg-zinc-400'
                  }`} />
                  <div className="flex-1">
                    <div className="text-[13px] font-semibold text-zinc-700 dark:text-zinc-200">
                      {modelStatus === 'loaded' ? 'Model đang chạy' :
                       modelStatus === 'loading' ? 'Đang load...' :
                       'Model chưa load'}
                    </div>
                    <div className="text-[11px] text-zinc-400 mt-0.5">
                      {modelStatus === 'loaded'
                        ? 'TTS khả dụng. Click Unload để giải phóng VRAM.'
                        : 'Load model để dùng TTS lồng tiếng.'}
                    </div>
                  </div>
                  <button onClick={onToggleModel}
                    disabled={modelStatus === 'loading'}
                    className={`btn flex-shrink-0 disabled:opacity-50 ${
                      modelStatus === 'loaded'
                        ? 'text-red-500 border-red-200 dark:border-red-800 hover:bg-red-50 dark:hover:bg-red-950/20'
                        : 'text-emerald-600 border-emerald-300 dark:border-emerald-700 hover:bg-emerald-50 dark:hover:bg-emerald-950/20'
                    }`}>
                    {modelStatus === 'loaded' ? 'Unload' :
                     modelStatus === 'loading' ? 'Loading...' : 'Load Model'}
                  </button>
                </div>
              </div>

              {/* Auto TTS */}
              <div className="border-t border-zinc-100 dark:border-zinc-800 pt-4">
                <div className="panel-label">Auto TTS</div>
                <label className="flex items-center gap-3 p-3 rounded-lg border border-zinc-200 dark:border-zinc-700 cursor-pointer hover:bg-zinc-50 dark:hover:bg-zinc-800/60 transition-colors">
                  <div className={`relative w-9 h-5 rounded-full transition-colors flex-shrink-0 ${autoTTS ? 'bg-blue-500' : 'bg-zinc-300 dark:bg-zinc-600'}`}>
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${autoTTS ? 'translate-x-4' : 'translate-x-0.5'}`} />
                  </div>
                  <div>
                    <div className="text-[13px] font-medium text-zinc-700 dark:text-zinc-200">
                      Tự động TTS khi gán nhân vật
                    </div>
                    <div className="text-[11px] text-zinc-400">
                      Gán nhân vật cho dòng phụ đề → tự động tạo audio
                    </div>
                  </div>
                  <input type="checkbox" checked={autoTTS} onChange={e => setAutoTTS(e.target.checked)} className="sr-only" />
                </label>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center gap-3 px-5 py-3 border-t border-zinc-200 dark:border-zinc-800 flex-shrink-0 bg-zinc-50 dark:bg-zinc-800/60">
          <span className={`text-[12px] transition-all ${saved ? 'text-emerald-500' : 'text-transparent'}`}>
            ✓ Đã lưu
          </span>
          <button onClick={onClose} className="btn ml-auto">Đóng</button>
          <button onClick={handleSave} className="btn-primary px-6">Lưu cấu hình</button>
        </div>
      </div>
    </div>
  )
}