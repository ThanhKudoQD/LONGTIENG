/**
 * ConfigPanel — modal cấu hình pipeline trước khi chạy.
 *
 * - Provider: gemini/openai/deepseek
 * - API key (lưu localStorage)
 * - Models theo tier (heavy/medium/light)
 * - Genre pack: auto detect hoặc chọn tay
 * - Project type, CPS max, concurrency
 *
 * Có 2 mode khởi chạy:
 * - "Bắt đầu (toàn bộ pipeline)" → onStart
 * - "Chạy 1 stage" → onRunStage(stage)
 */
import React, { useEffect, useState } from 'react'
import type { Project, TranslateStatus, GenrePackInfo, TranslateConfig } from '../../types'

interface Props {
  project: Project
  status: TranslateStatus | null
  genrePacks: GenrePackInfo[]
  onClose: () => void
  onStart: (config: TranslateConfig) => void
  onRunStage: (config: TranslateConfig, stage: string) => void
}

const STORAGE_KEY = 'translate_config_v2'

// ─── Catalog model cho từng provider ─────────────────────────────────────────

interface ModelOption {
  id: string                           // tên thực dùng cho API
  label: string                        // tên hiển thị
  priceIn: number                      // USD/1M input tokens
  priceOut: number                     // USD/1M output tokens
  desc: string                         // mô tả ngắn
  tier: 'top' | 'balanced' | 'fast'    // loại để gợi ý
}

const MODELS: Record<'gemini' | 'openai' | 'deepseek', ModelOption[]> = {
  gemini: [
    { id: 'gemini-3.1-pro',         label: 'Gemini 3.1 Pro (mới nhất)',  priceIn: 2.00,  priceOut: 12.00, desc: 'Mạnh nhất, hiểu context dài', tier: 'top' },
    { id: 'gemini-3.1-flash-lite-preview',         label: 'Gemini 3.1 Flash-Lite Preview',   priceIn: 0.50,  priceOut: 3.00,  desc: 'Nhanh + thông minh',          tier: 'balanced' },
    { id: 'gemini-2.5-pro',         label: 'Gemini 2.5 Pro',             priceIn: 1.25,  priceOut: 10.00, desc: 'Cân bằng — khuyến nghị Heavy', tier: 'top' },
    { id: 'gemini-2.5-flash',       label: 'Gemini 2.5 Flash',           priceIn: 0.30,  priceOut: 2.50,  desc: 'Nhanh, rẻ',                   tier: 'balanced' },
    { id: 'gemini-2.5-flash-lite',  label: 'Gemini 2.5 Flash-Lite',      priceIn: 0.10,  priceOut: 0.40,  desc: 'Rẻ nhất của Gemini',          tier: 'fast' },
  ],
  openai: [
    { id: 'gpt-5',          label: 'GPT-5',          priceIn: 1.25, priceOut: 10.00, desc: 'Top model OpenAI',           tier: 'top' },
    { id: 'gpt-5-mini',     label: 'GPT-5 Mini',     priceIn: 0.25, priceOut: 2.00,  desc: 'Cân bằng',                    tier: 'balanced' },
    { id: 'gpt-5-nano',     label: 'GPT-5 Nano',     priceIn: 0.05, priceOut: 0.40,  desc: 'Rẻ nhất',                     tier: 'fast' },
    { id: 'gpt-4o',         label: 'GPT-4o',         priceIn: 2.50, priceOut: 10.00, desc: 'Gen cũ, vẫn tốt',             tier: 'top' },
    { id: 'gpt-4o-mini',    label: 'GPT-4o Mini',    priceIn: 0.15, priceOut: 0.60,  desc: 'Gen cũ, rẻ',                  tier: 'balanced' },
  ],
  deepseek: [
    { id: 'deepseek-chat', label: 'DeepSeek-V3 (chat)', priceIn: 0.27, priceOut: 1.10, desc: 'Hiểu tiếng Trung tốt, có context cache 90% off', tier: 'balanced' },
    { id: 'deepseek-reasoner', label: 'DeepSeek-R1 (reasoner)', priceIn: 0.55, priceOut: 2.19, desc: 'Có reasoning, chậm hơn', tier: 'top' },
  ],
}

// ─── Preset profile ──────────────────────────────────────────────────────────

interface Preset {
  id: string
  label: string
  desc: string
  models: { gemini: [string, string, string]; openai: [string, string, string]; deepseek: [string, string, string] }
}

const PRESETS: Preset[] = [
  {
    id: 'budget', label: '💸 Tiết kiệm',
    desc: 'Tất cả dùng model rẻ nhất, giảm 80% chi phí, chấp nhận chất lượng giảm',
    models: {
      gemini:   ['gemini-2.5-flash',       'gemini-2.5-flash-lite', 'gemini-2.5-flash-lite'],
      openai:   ['gpt-5-mini',             'gpt-5-nano',            'gpt-5-nano'],
      deepseek: ['deepseek-chat',          'deepseek-chat',         'deepseek-chat'],
    },
  },
  {
    id: 'balanced', label: '⚖ Cân bằng (khuyến nghị)',
    desc: 'Pro cho Bible+Dịch, Flash-Lite cho Scene/Speaker/Polish. Tiết kiệm 30%',
    models: {
      gemini:   ['gemini-2.5-pro',         'gemini-2.5-flash-lite', 'gemini-2.5-flash-lite'],
      openai:   ['gpt-5',                  'gpt-5-mini',            'gpt-5-nano'],
      deepseek: ['deepseek-reasoner',      'deepseek-chat',         'deepseek-chat'],
    },
  },
  {
    id: 'quality', label: '💎 Chất lượng cao',
    desc: 'Pro cho cả 3 tier — đắt nhất, chất lượng tốt nhất',
    models: {
      gemini:   ['gemini-2.5-pro',         'gemini-2.5-pro',        'gemini-2.5-flash'],
      openai:   ['gpt-5',                  'gpt-5',                 'gpt-5-mini'],
      deepseek: ['deepseek-reasoner',      'deepseek-reasoner',     'deepseek-chat'],
    },
  },
]

interface StoredConfig {
  api_key: string
  provider: 'gemini' | 'openai' | 'deepseek'
  model_heavy: string
  model_medium: string
  model_light: string
  concurrency: number
}

function loadStored(): StoredConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {}
  return {
    api_key: '',
    provider: 'gemini',
    model_heavy: 'gemini-2.5-pro',
    model_medium: 'gemini-2.5-flash',
    model_light: 'gemini-2.5-flash',
    concurrency: 5,
  }
}

function saveStored(cfg: StoredConfig) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg))
  } catch {}
}

export default function ConfigPanel({
  project, status, genrePacks, onClose, onStart, onRunStage,
}: Props) {
  const stored = loadStored()

  const [provider, setProvider] = useState(stored.provider)
  const [apiKey, setApiKey] = useState(stored.api_key)
  const [showKey, setShowKey] = useState(false)
  const [modelHeavy, setModelHeavy] = useState(stored.model_heavy)
  const [modelMedium, setModelMedium] = useState(stored.model_medium)
  const [modelLight, setModelLight] = useState(stored.model_light)
  const [concurrency, setConcurrency] = useState(stored.concurrency)

  const [projectType, setProjectType] = useState<'short_drama' | 'drama_series' | 'movie'>(
    project.project_type || 'short_drama'
  )
  const [genrePack, setGenrePack] = useState<string>(project.genre_pack || 'auto')
  const [cpsMax, setCpsMax] = useState<string>('')

  // Auto-save settings vào localStorage mỗi khi user gõ (debounce 300ms).
  // Tách riêng useEffect này khỏi buildConfig() để key được lưu KỂ CẢ khi
  // user đóng modal mà chưa bấm Start.
  useEffect(() => {
    const handle = setTimeout(() => {
      saveStored({
        api_key: apiKey,
        provider,
        model_heavy: modelHeavy,
        model_medium: modelMedium,
        model_light: modelLight,
        concurrency,
      })
    }, 300)
    return () => clearTimeout(handle)
  }, [apiKey, provider, modelHeavy, modelMedium, modelLight, concurrency])

  // Auto-suggest models when provider changes
  useEffect(() => {
    if (provider === 'gemini') {
      if (!modelHeavy.startsWith('gemini')) setModelHeavy('gemini-2.5-pro')
      if (!modelMedium.startsWith('gemini')) setModelMedium('gemini-2.5-flash')
      if (!modelLight.startsWith('gemini')) setModelLight('gemini-2.5-flash')
    } else if (provider === 'openai') {
      if (!modelHeavy.startsWith('gpt')) setModelHeavy('gpt-5')
      if (!modelMedium.startsWith('gpt')) setModelMedium('gpt-5-mini')
      if (!modelLight.startsWith('gpt')) setModelLight('gpt-5-mini')
    } else if (provider === 'deepseek') {
      if (!modelHeavy.startsWith('deepseek')) setModelHeavy('deepseek-chat')
      if (!modelMedium.startsWith('deepseek')) setModelMedium('deepseek-chat')
      if (!modelLight.startsWith('deepseek')) setModelLight('deepseek-chat')
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider])

  function buildConfig(): TranslateConfig {
    saveStored({
      api_key: apiKey,
      provider, model_heavy: modelHeavy, model_medium: modelMedium,
      model_light: modelLight, concurrency,
    })

    return {
      api_key: apiKey.trim(),
      provider,
      model_heavy: modelHeavy.trim(),
      model_medium: modelMedium.trim(),
      model_light: modelLight.trim(),
      project_type: projectType,
      genre_pack: genrePack === 'auto' ? null : genrePack,
      cps_max: cpsMax ? parseFloat(cpsMax) : null,
      concurrency,
      source_lang: 'zh',
    }
  }

  function handleStart() {
    if (!apiKey.trim()) {
      alert('Cần API key')
      return
    }
    onStart(buildConfig())
  }

  function handleRunStage(stage: string) {
    if (!apiKey.trim()) {
      alert('Cần API key')
      return
    }
    onRunStage(buildConfig(), stage)
  }

  const hasBible = status?.has_bible
  const hasScenes = (status?.scene_count ?? 0) > 0

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-auto"
           onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center">
          <h2 className="text-base font-semibold text-zinc-800 dark:text-zinc-100">
            Cấu hình Pipeline dịch
          </h2>
          <div className="flex-1" />
          <button onClick={onClose} className="btn">✕</button>
        </div>

        {/* Body */}
        <div className="p-5 space-y-5">

          {/* Provider + API key */}
          <section>
            <SectionLabel>1. API Provider</SectionLabel>
            <div className="grid grid-cols-3 gap-2 mb-3">
              {(['gemini', 'openai', 'deepseek'] as const).map(p => (
                <button
                  key={p}
                  onClick={() => setProvider(p)}
                  className={`px-3 py-2 rounded-lg border text-[13px] font-medium transition-all ${
                    provider === p
                      ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                      : 'border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                  }`}
                >
                  {p === 'gemini' && '🤖 Gemini'}
                  {p === 'openai' && '🧠 OpenAI'}
                  {p === 'deepseek' && '🐳 DeepSeek'}
                </button>
              ))}
            </div>
            <div className="relative">
              <input
                type={showKey ? 'text' : 'password'}
                value={apiKey}
                onChange={e => setApiKey(e.target.value)}
                placeholder={`Paste ${provider} API key...`}
                className="input w-full pr-20"
                autoComplete="off"
                spellCheck={false}
              />
              <button
                type="button"
                onClick={() => setShowKey(s => !s)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-[11px] text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 px-1.5 py-0.5"
                tabIndex={-1}
              >
                {showKey ? '🙈 Ẩn' : '👁 Hiện'}
              </button>
            </div>
            <div className="flex items-center gap-2 text-[11px] mt-1">
              <span className="text-zinc-500">
                Key lưu trong browser, không gửi đi đâu khác ngoài API provider.
              </span>
              {apiKey && (
                <span className="text-green-600 dark:text-green-400 ml-auto">
                  ✓ Đã lưu ({apiKey.length} ký tự)
                </span>
              )}
            </div>
          </section>

          {/* Models */}
          <section>
            <SectionLabel>2. Models — chọn cho từng giai đoạn</SectionLabel>

            {/* Preset profiles */}
            <div className="mb-3">
              <div className="text-[11px] text-zinc-500 mb-1.5">Preset nhanh:</div>
              <div className="grid grid-cols-3 gap-2">
                {PRESETS.map(p => {
                  const tuple = p.models[provider]
                  const isActive = modelHeavy === tuple[0] && modelMedium === tuple[1] && modelLight === tuple[2]
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => {
                        setModelHeavy(tuple[0])
                        setModelMedium(tuple[1])
                        setModelLight(tuple[2])
                      }}
                      className={`px-3 py-2 rounded-lg border text-left transition-all ${
                        isActive
                          ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30'
                          : 'border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                      }`}
                    >
                      <div className="text-[12px] font-medium text-zinc-800 dark:text-zinc-100">{p.label}</div>
                      <div className="text-[10px] text-zinc-500 mt-0.5 leading-snug">{p.desc}</div>
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Hoặc chỉnh tay từng tier */}
            <div className="text-[11px] text-zinc-500 mb-1.5">Hoặc chỉnh tay từng giai đoạn:</div>
            <div className="space-y-2">
              <ModelSelector
                tier="Heavy"
                stages="Bible + Translate (dòng dịch chính)"
                provider={provider}
                value={modelHeavy}
                onChange={setModelHeavy}
              />
              <ModelSelector
                tier="Medium"
                stages="Scene · Speaker · Consistency check · Glossary scan"
                provider={provider}
                value={modelMedium}
                onChange={setModelMedium}
              />
              <ModelSelector
                tier="Light"
                stages="CPS condense (rút gọn câu vượt CPS)"
                provider={provider}
                value={modelLight}
                onChange={setModelLight}
              />
            </div>
          </section>

          {/* Project type */}
          <section>
            <SectionLabel>3. Loại project</SectionLabel>
            <div className="grid grid-cols-3 gap-2">
              <TypeButton active={projectType === 'short_drama'} onClick={() => setProjectType('short_drama')}
                title="Short drama" desc="60 tập × 2 phút, CPS ≤15" />
              <TypeButton active={projectType === 'drama_series'} onClick={() => setProjectType('drama_series')}
                title="Drama series" desc="40-45 phút/tập, CPS ≤17" />
              <TypeButton active={projectType === 'movie'} onClick={() => setProjectType('movie')}
                title="Movie" desc="Phim điện ảnh 1.5-2h" />
            </div>
          </section>

          {/* Genre pack */}
          <section>
            <SectionLabel>4. Thể loại</SectionLabel>
            <select
              value={genrePack}
              onChange={e => setGenrePack(e.target.value)}
              className="input w-full"
            >
              <option value="auto">🪄 Tự động (auto detect từ phim)</option>
              {genrePacks.map(p => (
                <option key={p.id} value={p.id}>
                  {p.name_vi} ({p.name_zh})
                </option>
              ))}
            </select>
            {genrePack !== 'auto' && (
              <div className="text-[11px] text-zinc-500 mt-1">
                {genrePacks.find(p => p.id === genrePack)?.description}
              </div>
            )}
          </section>

          {/* Advanced */}
          <details>
            <summary className="cursor-pointer text-[11px] font-semibold text-zinc-400 uppercase tracking-widest hover:text-zinc-600">
              Tùy chọn nâng cao
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] font-medium text-zinc-600 dark:text-zinc-400 block mb-1">
                  CPS tối đa (chars/giây)
                </label>
                <input
                  type="number"
                  value={cpsMax}
                  onChange={e => setCpsMax(e.target.value)}
                  placeholder="auto (15 cho short drama)"
                  className="input w-full"
                  step="0.5"
                  min="10"
                  max="25"
                />
              </div>
              <div>
                <label className="text-[11px] font-medium text-zinc-600 dark:text-zinc-400 block mb-1">
                  Concurrency (số call song song)
                </label>
                <input
                  type="number"
                  value={concurrency}
                  onChange={e => setConcurrency(Math.max(1, Math.min(20, parseInt(e.target.value) || 5)))}
                  className="input w-full"
                  min="1"
                  max="20"
                />
              </div>
            </div>
          </details>
        </div>

        {/* Footer — actions */}
        <div className="px-5 py-4 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950">
          <div className="flex items-center gap-2 mb-3">
            <button onClick={handleStart} className="btn-primary flex-1 py-2">
              ▶ Bắt đầu toàn bộ pipeline (5 stage)
            </button>
          </div>

          <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-widest mb-2">
            Hoặc chạy 1 stage cụ thể (resume / debug)
          </div>
          <div className="grid grid-cols-5 gap-2">
            <StageButton onClick={() => handleRunStage('bible')} done={hasBible}>1. Bible</StageButton>
            <StageButton onClick={() => handleRunStage('scenes')} done={hasScenes} disabled={!hasBible}>2. Scenes</StageButton>
            <StageButton onClick={() => handleRunStage('speaker')} disabled={!hasScenes}>3. Speaker</StageButton>
            <StageButton onClick={() => handleRunStage('translate')} disabled={!hasScenes}>4. Translate</StageButton>
            <StageButton onClick={() => handleRunStage('polish')} disabled={!hasBible}>5. Polish</StageButton>
          </div>
        </div>
      </div>
    </div>
  )
}

// ─── Sub components ──────────────────────────────────────────────────────────

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-2">
      {children}
    </div>
  )
}

function ModelSelector({ tier, stages, provider, value, onChange }: {
  tier: string
  stages: string
  provider: 'gemini' | 'openai' | 'deepseek'
  value: string
  onChange: (v: string) => void
}) {
  const options = MODELS[provider] || []
  const known = options.find(m => m.id === value)
  const [customMode, setCustomMode] = React.useState(!known && !!value)

  // Khi user đổi provider, tự switch về dropdown nếu model hiện tại match catalog
  React.useEffect(() => {
    if (options.find(m => m.id === value)) {
      setCustomMode(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, provider])

  const tierColor =
    tier === 'Heavy' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
    : tier === 'Medium' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
    : 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'

  return (
    <div className="border border-zinc-200 dark:border-zinc-700 rounded-lg p-2.5 bg-zinc-50/50 dark:bg-zinc-900/50">
      <div className="flex items-center gap-2 mb-1.5">
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${tierColor}`}>
          {tier}
        </span>
        <span className="text-[11px] text-zinc-600 dark:text-zinc-400 flex-1">{stages}</span>
        <button
          type="button"
          onClick={() => setCustomMode(c => !c)}
          className="text-[10px] text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 underline"
        >
          {customMode ? '← Dùng dropdown' : '✎ Gõ tay'}
        </button>
      </div>

      {customMode ? (
        <input
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="Tên model (vd: gemini-2.5-pro)"
          className="input w-full text-[12px] font-mono"
        />
      ) : (
        <>
          <select
            value={value}
            onChange={e => onChange(e.target.value)}
            className="input w-full text-[12px]"
          >
            {options.map(m => (
              <option key={m.id} value={m.id}>
                {m.label}  ·  ${m.priceIn}/$ {m.priceOut} per 1M
              </option>
            ))}
          </select>
          {known && (
            <div className="text-[10px] text-zinc-500 mt-1 leading-snug">
              {known.desc}
            </div>
          )}
        </>
      )}
    </div>
  )
}

// Backward compat — không xóa để tránh break component khác nếu có import
function ModelInput({ label, hint, value, onChange }: {
  label: string; hint: string; value: string; onChange: (v: string) => void
}) {
  return (
    <div>
      <label className="text-[11px] font-medium text-zinc-600 dark:text-zinc-400 block">
        {label} <span className="text-zinc-400 font-normal">· {hint}</span>
      </label>
      <input value={value} onChange={e => onChange(e.target.value)} className="input w-full mt-1" />
    </div>
  )
}

function TypeButton({ active, onClick, title, desc }: {
  active: boolean; onClick: () => void; title: string; desc: string
}) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-2 rounded-lg border text-left transition-all ${
        active
          ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30'
          : 'border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800'
      }`}
    >
      <div className="text-[13px] font-medium text-zinc-800 dark:text-zinc-100">{title}</div>
      <div className="text-[11px] text-zinc-500 mt-0.5">{desc}</div>
    </button>
  )
}

function StageButton({ onClick, done, disabled, children }: {
  onClick: () => void; done?: boolean; disabled?: boolean; children: React.ReactNode
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`px-2 py-2 rounded-lg border text-[12px] font-medium transition-all relative ${
        disabled
          ? 'border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 text-zinc-400 cursor-not-allowed'
          : 'border-zinc-200 dark:border-zinc-700 bg-white dark:bg-zinc-800 hover:bg-blue-50 dark:hover:bg-blue-900/30 text-zinc-700 dark:text-zinc-200'
      }`}
    >
      {done && <span className="absolute top-0.5 right-1 text-[10px]">✓</span>}
      {children}
    </button>
  )
}