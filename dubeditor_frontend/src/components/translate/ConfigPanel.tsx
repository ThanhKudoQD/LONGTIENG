/**
 * ConfigPanel v3 — modal cấu hình pipeline trước khi chạy.
 *
 * Thay đổi v3:
 * - Bỏ Genre Pack (đã gộp vào Glossary Bible)
 * - Thêm Variant Mode (off/important_only/always)
 * - Thêm Chunk Overlap (sliding window)
 * - Thêm Cache toggle
 * - Bỏ stage "scenes" — thay bằng "chunks" (gộp chunks+scenes)
 */
import React, { useEffect, useState } from 'react'
import type {
  Project, TranslateStatus, TranslateConfig, VariantMode,
} from '../../types'
import { VARIANT_MODE_LABELS } from '../../types'

interface Props {
  project: Project
  status: TranslateStatus | null
  onClose: () => void
  onStart: (config: TranslateConfig) => void
  onRunStage: (config: TranslateConfig, stage: string) => void
}

const STORAGE_KEY = 'translate_config_v3'

// ─── Catalog model cho từng provider ─────────────────────────────────────────

interface ModelOption {
  id: string
  label: string
  priceIn: number
  priceOut: number
  desc: string
  tier: 'top' | 'balanced' | 'fast'
}

const MODELS: Record<'gemini' | 'openai' | 'deepseek', ModelOption[]> = {
  gemini: [
    { id: 'gemini-3.1-pro',          label: 'Gemini 3.1 Pro (mới nhất)',     priceIn: 2.00, priceOut: 12.00, desc: 'Mạnh nhất, hiểu context dài', tier: 'top' },
    { id: 'gemini-3.1-flash-lite',   label: 'Gemini 3.1 Flash-Lite',         priceIn: 0.50, priceOut: 3.00,  desc: 'Nhanh + thông minh',          tier: 'balanced' },
    { id: 'gemini-2.5-pro',          label: 'Gemini 2.5 Pro',                priceIn: 1.25, priceOut: 10.00, desc: 'Cân bằng — khuyến nghị task khó',tier: 'top' },
    { id: 'gemini-2.5-flash',        label: 'Gemini 2.5 Flash',              priceIn: 0.30, priceOut: 2.50,  desc: 'Nhanh, rẻ',                   tier: 'balanced' },
    { id: 'gemini-2.5-flash-lite',   label: 'Gemini 2.5 Flash-Lite',         priceIn: 0.10, priceOut: 0.40,  desc: 'Rẻ nhất của Gemini',          tier: 'fast' },
  ],
  openai: [
    { id: 'gpt-5',       label: 'GPT-5',       priceIn: 1.25, priceOut: 10.00, desc: 'Top model OpenAI', tier: 'top' },
    { id: 'gpt-5-mini',  label: 'GPT-5 Mini',  priceIn: 0.25, priceOut: 2.00,  desc: 'Cân bằng',         tier: 'balanced' },
    { id: 'gpt-5-nano',  label: 'GPT-5 Nano',  priceIn: 0.05, priceOut: 0.40,  desc: 'Rẻ nhất',          tier: 'fast' },
    { id: 'gpt-4o',      label: 'GPT-4o',      priceIn: 2.50, priceOut: 10.00, desc: 'Gen cũ, vẫn tốt',  tier: 'top' },
    { id: 'gpt-4o-mini', label: 'GPT-4o Mini', priceIn: 0.15, priceOut: 0.60,  desc: 'Gen cũ, rẻ',       tier: 'balanced' },
  ],
  deepseek: [
    { id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash',
      priceIn: 0.14, priceOut: 0.28,
      desc: 'Nhanh, rẻ. Cache hit $0.0028/1M. Context 1M.', tier: 'fast' },
    { id: 'deepseek-v4-pro',   label: 'DeepSeek V4 Pro',
      priceIn: 0.435, priceOut: 0.87,
      desc: 'Top model DeepSeek. Cache hit $0.0036/1M. Context 1M.', tier: 'top' },
  ],
}

// ─── Stage definitions (v3.5 — gộp theo Stage thay vì tier) ──────────────────
// Mỗi entry = 1 card trong UI. UI render 1 ModelSelector per stage độc lập.

interface StageDef {
  key: 'stage0' | 'stage1' | 'stage2' | 'stage3' | 'stage4' | 'stage5' | 'retranslate'
  title: string             // Tiêu đề lớn — STAGE 1, STAGE 2…
  desc: string              // Mô tả ngắn nhiệm vụ của stage
  badgeColor: string        // Tailwind class cho badge
  isMain?: boolean          // Đánh dấu Stage 4 — Task chính
  defaultModel: {           // Default model khi provider thay đổi
    gemini: string; openai: string; deepseek: string
  }
  defaultThinking: boolean
  thinkingHint: string
  allowEmpty?: boolean
  emptyLabel?: string
}

const STAGES: StageDef[] = [
  {
    key: 'stage0',
    title: 'STAGE 0 · Chuẩn hóa phụ đề',
    desc: 'AI quét phụ đề, dọn watermark/filler/dòng nhiễu trước khi dịch.',
    badgeColor: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
    defaultModel: { gemini: 'gemini-2.5-flash-lite', openai: 'gpt-5-nano', deepseek: 'deepseek-v4-flash' },
    defaultThinking: false,
    thinkingHint: 'Task đơn giản — tắt là đủ',
    allowEmpty: true,
    emptyLabel: '↪ Dùng model rẻ nhất (mặc định)',
  },
  {
    key: 'stage1',
    title: 'STAGE 1 · Bible',
    desc: 'Trích nhân vật + thuật ngữ + bối cảnh + story arcs. Gộp 1A Cast+Glossary và 1B World+Arcs.',
    badgeColor: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
    defaultModel: { gemini: 'gemini-2.5-pro', openai: 'gpt-5', deepseek: 'deepseek-v4-pro' },
    defaultThinking: true,
    thinkingHint: 'Trích nhân vật + Hán Việt — bật thinking giúp Bible chuẩn hơn',
  },
  {
    key: 'stage2',
    title: 'STAGE 2 · Chunks + Scenes',
    desc: 'Chia phim thành chunks (~300 dòng) và scenes con. 1 call/arc.',
    badgeColor: 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300',
    defaultModel: { gemini: 'gemini-2.5-flash', openai: 'gpt-5-mini', deepseek: 'deepseek-v4-flash' },
    defaultThinking: false,
    thinkingHint: 'Extract structure đơn giản — tắt là đủ',
  },
  {
    key: 'stage3',
    title: 'STAGE 3 · Speaker',
    desc: 'Đoán ai nói câu nào dựa trên thoại + quan hệ + cảnh.',
    badgeColor: 'bg-cyan-100 text-cyan-700 dark:bg-cyan-900/40 dark:text-cyan-300',
    defaultModel: { gemini: 'gemini-2.5-flash', openai: 'gpt-5-mini', deepseek: 'deepseek-v4-flash' },
    defaultThinking: false,
    thinkingHint: 'Gán speaker — tắt là đủ',
  },
  {
    key: 'stage4',
    title: 'STAGE 4 · Translate ⭐',
    desc: 'Dịch theo chunk với 2 bản v1/v2. ĐÂY LÀ TASK CHÍNH — chất lượng dịch phụ thuộc vào stage này.',
    badgeColor: 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300',
    isMain: true,
    defaultModel: { gemini: 'gemini-2.5-pro', openai: 'gpt-5', deepseek: 'deepseek-v4-pro' },
    defaultThinking: true,
    thinkingHint: '⭐ TASK CHÍNH — bật để dịch chất lượng cao hơn (recommended)',
  },
  {
    key: 'stage5',
    title: 'STAGE 5 · Retry',
    desc: 'Retry các dòng còn tiếng Trung / rỗng. Chạy sau Stage 4.',
    badgeColor: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300',
    defaultModel: { gemini: 'gemini-2.5-flash-lite', openai: 'gpt-5-nano', deepseek: 'deepseek-v4-flash' },
    defaultThinking: false,
    thinkingHint: 'Retry đơn giản — tắt là đủ',
  },
  {
    key: 'retranslate',
    title: 'DỊCH LẠI (trong Editor)',
    desc: 'Khi user bấm "Dịch lại" cho 1 dòng cụ thể trong editor.',
    badgeColor: 'bg-fuchsia-100 text-fuchsia-700 dark:bg-fuchsia-900/40 dark:text-fuchsia-300',
    defaultModel: { gemini: 'gemini-2.5-pro', openai: 'gpt-5', deepseek: 'deepseek-v4-pro' },
    defaultThinking: false,
    thinkingHint: 'Bật nếu muốn chất lượng cao hơn cho lần dịch lại',
  },
]

interface StoredConfig {
  api_keys: {
    gemini: string
    openai: string
    deepseek: string
  }
  provider: 'gemini' | 'openai' | 'deepseek'
  // ── Legacy tier (giữ để backward compat khi backend chưa cập nhật) ─
  model_heavy: string
  model_medium: string
  model_light: string
  heavy_thinking: boolean
  medium_thinking: boolean
  light_thinking: boolean
  translate_thinking: boolean
  // ── v3.5: per-stage model + thinking (UI mới) ───────────────────────
  model_stage0: string
  model_stage1: string
  model_stage2: string
  model_stage3: string
  model_stage4: string
  model_stage5: string
  model_retranslate: string
  thinking_stage0: boolean
  thinking_stage1: boolean
  thinking_stage2: boolean
  thinking_stage3: boolean
  thinking_stage4: boolean
  thinking_stage5: boolean
  thinking_retranslate: boolean
  concurrency: number
  variant_mode: VariantMode
  chunk_overlap: number
  cache_enabled: boolean
  chunks_parallel: boolean
  speaker_parallel: boolean
  speaker_context_window: number
  stage0_enabled: boolean
  stage0_model: string                  // (legacy) deprecated — nhường chỗ cho model_stage0
  stage0_context_window: number
}

function loadStored(): StoredConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const parsed = JSON.parse(raw)
      // Migration: api_key (string cũ) → api_keys (object mới)
      if (typeof parsed.api_key === 'string' && !parsed.api_keys) {
        parsed.api_keys = {
          gemini: parsed.provider === 'gemini' ? parsed.api_key : '',
          openai: parsed.provider === 'openai' ? parsed.api_key : '',
          deepseek: parsed.provider === 'deepseek' ? parsed.api_key : '',
        }
        delete parsed.api_key
      }
      // v3.5 migration: nếu chưa có model_stage1 → migrate từ tier cũ
      //   stage1, stage4, retranslate ← heavy
      //   stage2, stage3              ← medium
      //   stage0, stage5              ← light
      if (parsed.model_heavy && !parsed.model_stage1) {
        parsed.model_stage1      = parsed.model_heavy
        parsed.model_stage4      = parsed.model_heavy
        parsed.model_retranslate = parsed.model_heavy
        parsed.model_stage2      = parsed.model_medium || parsed.model_heavy
        parsed.model_stage3      = parsed.model_medium || parsed.model_heavy
        parsed.model_stage0      = parsed.stage0_model || parsed.model_light || ''
        parsed.model_stage5      = parsed.model_light || parsed.model_medium || ''
      }
      if (typeof parsed.heavy_thinking === 'boolean' && parsed.thinking_stage1 === undefined) {
        parsed.thinking_stage1      = parsed.heavy_thinking
        parsed.thinking_stage4      = parsed.translate_thinking ?? parsed.heavy_thinking
        parsed.thinking_retranslate = false
        parsed.thinking_stage2      = parsed.medium_thinking ?? false
        parsed.thinking_stage3      = parsed.medium_thinking ?? false
        parsed.thinking_stage0      = parsed.light_thinking ?? false
        parsed.thinking_stage5      = parsed.light_thinking ?? false
      }
      return { ...defaultStored(), ...parsed }
    }
  } catch {}
  return defaultStored()
}

function defaultStored(): StoredConfig {
  // Mặc định lấy từ STAGES.defaultModel để consistent
  const get = (key: StageDef['key'], provider: 'gemini' | 'openai' | 'deepseek') => {
    const st = STAGES.find(s => s.key === key)
    return st ? st.defaultModel[provider] : ''
  }
  return {
    api_keys: { gemini: '', openai: '', deepseek: '' },
    provider: 'gemini',
    model_heavy: 'gemini-2.5-pro',
    model_medium: 'gemini-2.5-flash',
    model_light: 'gemini-2.5-flash',
    heavy_thinking: true,
    medium_thinking: false,
    light_thinking: false,
    translate_thinking: true,
    // v3.5: per-stage defaults
    model_stage0:      get('stage0', 'gemini'),
    model_stage1:      get('stage1', 'gemini'),
    model_stage2:      get('stage2', 'gemini'),
    model_stage3:      get('stage3', 'gemini'),
    model_stage4:      get('stage4', 'gemini'),
    model_stage5:      get('stage5', 'gemini'),
    model_retranslate: get('retranslate', 'gemini'),
    thinking_stage0:      STAGES.find(s => s.key === 'stage0')!.defaultThinking,
    thinking_stage1:      STAGES.find(s => s.key === 'stage1')!.defaultThinking,
    thinking_stage2:      STAGES.find(s => s.key === 'stage2')!.defaultThinking,
    thinking_stage3:      STAGES.find(s => s.key === 'stage3')!.defaultThinking,
    thinking_stage4:      STAGES.find(s => s.key === 'stage4')!.defaultThinking,
    thinking_stage5:      STAGES.find(s => s.key === 'stage5')!.defaultThinking,
    thinking_retranslate: STAGES.find(s => s.key === 'retranslate')!.defaultThinking,
    concurrency: 5,
    variant_mode: 'important_only',
    chunk_overlap: 30,
    cache_enabled: true,
    chunks_parallel: false,
    speaker_parallel: true,
    speaker_context_window: 20,
    stage0_enabled: true,
    stage0_model: '',                   // deprecated
    stage0_context_window: 2,
  }
}

function saveStored(cfg: StoredConfig) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cfg))
  } catch {}
}

export default function ConfigPanel({
  project, status, onClose, onStart, onRunStage,
}: Props) {
  const stored = loadStored()

  const [provider, setProvider] = useState(stored.provider)
  const [apiKeys, setApiKeys] = useState<{gemini: string; openai: string; deepseek: string}>(stored.api_keys)
  const [showKey, setShowKey] = useState(false)
  // Legacy tier state — vẫn lưu để gửi xuống backend backward compat
  const [modelHeavy, setModelHeavy] = useState(stored.model_heavy)
  const [modelMedium, setModelMedium] = useState(stored.model_medium)
  const [modelLight, setModelLight] = useState(stored.model_light)
  const [heavyThinking, setHeavyThinking] = useState(stored.heavy_thinking)
  const [mediumThinking, setMediumThinking] = useState(stored.medium_thinking)
  const [lightThinking, setLightThinking] = useState(stored.light_thinking)
  const [translateThinking, setTranslateThinking] = useState(stored.translate_thinking)

  // ── v3.5: per-stage state ──────────────────────────────────────────
  const [stageModels, setStageModels] = useState<Record<StageDef['key'], string>>({
    stage0:      stored.model_stage0,
    stage1:      stored.model_stage1,
    stage2:      stored.model_stage2,
    stage3:      stored.model_stage3,
    stage4:      stored.model_stage4,
    stage5:      stored.model_stage5,
    retranslate: stored.model_retranslate,
  })
  const [stageThinking, setStageThinking] = useState<Record<StageDef['key'], boolean>>({
    stage0:      stored.thinking_stage0,
    stage1:      stored.thinking_stage1,
    stage2:      stored.thinking_stage2,
    stage3:      stored.thinking_stage3,
    stage4:      stored.thinking_stage4,
    stage5:      stored.thinking_stage5,
    retranslate: stored.thinking_retranslate,
  })
  const setStageModel = (key: StageDef['key'], v: string) =>
    setStageModels(prev => ({ ...prev, [key]: v }))
  const setStageThinkingFor = (key: StageDef['key'], v: boolean) =>
    setStageThinking(prev => ({ ...prev, [key]: v }))

  const [concurrency, setConcurrency] = useState(stored.concurrency)

  const [projectType, setProjectType] = useState<'short_drama' | 'drama_series' | 'movie'>(
    project.project_type || 'short_drama'
  )
  const [cpsMax, setCpsMax] = useState<string>('')

  // v3 fields
  const [variantMode, setVariantMode] = useState<VariantMode>(stored.variant_mode)
  const [chunkOverlap, setChunkOverlap] = useState<number>(stored.chunk_overlap)
  const [cacheEnabled, setCacheEnabled] = useState<boolean>(stored.cache_enabled)
  const [chunksParallel, setChunksParallel] = useState<boolean>(stored.chunks_parallel)
  const [speakerParallel, setSpeakerParallel] = useState<boolean>(stored.speaker_parallel)
  const [speakerContextWindow, setSpeakerContextWindow] = useState<number>(stored.speaker_context_window)
  const [stage0Enabled, setStage0Enabled] = useState<boolean>(stored.stage0_enabled)
  const [stage0Model, setStage0Model] = useState<string>(stored.stage0_model)
  const [stage0ContextWindow, setStage0ContextWindow] = useState<number>(stored.stage0_context_window)

  // Save state — báo "đã lưu" sau khi user bấm
  const [savedTick, setSavedTick] = useState(0)

  // Current API key theo provider đang chọn
  const apiKey = apiKeys[provider] || ''
  const setApiKey = (v: string) => {
    setApiKeys(prev => ({ ...prev, [provider]: v }))
  }

  // Build StoredConfig hiện tại
  function currentStored(): StoredConfig {
    return {
      api_keys: apiKeys, provider,
      model_heavy: modelHeavy, model_medium: modelMedium, model_light: modelLight,
      heavy_thinking: heavyThinking,
      medium_thinking: mediumThinking,
      light_thinking: lightThinking,
      translate_thinking: translateThinking,
      // v3.5
      model_stage0:      stageModels.stage0,
      model_stage1:      stageModels.stage1,
      model_stage2:      stageModels.stage2,
      model_stage3:      stageModels.stage3,
      model_stage4:      stageModels.stage4,
      model_stage5:      stageModels.stage5,
      model_retranslate: stageModels.retranslate,
      thinking_stage0:      stageThinking.stage0,
      thinking_stage1:      stageThinking.stage1,
      thinking_stage2:      stageThinking.stage2,
      thinking_stage3:      stageThinking.stage3,
      thinking_stage4:      stageThinking.stage4,
      thinking_stage5:      stageThinking.stage5,
      thinking_retranslate: stageThinking.retranslate,
      concurrency,
      variant_mode: variantMode,
      chunk_overlap: chunkOverlap,
      cache_enabled: cacheEnabled,
      chunks_parallel: chunksParallel,
      speaker_parallel: speakerParallel,
      speaker_context_window: speakerContextWindow,
      stage0_enabled: stage0Enabled,
      stage0_model: stage0Model,
      stage0_context_window: stage0ContextWindow,
    }
  }

  // Auto-save vào localStorage (debounce 300ms) — vẫn giữ vì tiện
  useEffect(() => {
    const handle = setTimeout(() => {
      saveStored(currentStored())
    }, 300)
    return () => clearTimeout(handle)
  }, [apiKeys, provider, modelHeavy, modelMedium, modelLight, concurrency,
      heavyThinking, mediumThinking, lightThinking, translateThinking,
      stageModels, stageThinking,
      variantMode, chunkOverlap, cacheEnabled, chunksParallel, speakerParallel,
      speakerContextWindow, stage0Enabled, stage0Model, stage0ContextWindow])

  // Manual save — báo cho user biết
  function handleSave() {
    saveStored(currentStored())
    setSavedTick(t => t + 1)
    setTimeout(() => setSavedTick(0), 2000)
  }

  // Auto-suggest models when provider changes
  useEffect(() => {
    if (provider === 'gemini') {
      if (!modelHeavy.startsWith('gemini')) setModelHeavy('gemini-2.5-pro')
      if (!modelMedium.startsWith('gemini')) setModelMedium('gemini-2.5-flash')
      if (!modelLight.startsWith('gemini')) setModelLight('gemini-2.5-flash')
      if (stage0Model && !stage0Model.startsWith('gemini')) setStage0Model('')
    } else if (provider === 'openai') {
      if (!modelHeavy.startsWith('gpt')) setModelHeavy('gpt-5')
      if (!modelMedium.startsWith('gpt')) setModelMedium('gpt-5-mini')
      if (!modelLight.startsWith('gpt')) setModelLight('gpt-5-mini')
      if (stage0Model && !stage0Model.startsWith('gpt')) setStage0Model('')
    } else if (provider === 'deepseek') {
      if (!modelHeavy.startsWith('deepseek')) setModelHeavy('deepseek-v4-pro')
      if (!modelMedium.startsWith('deepseek')) setModelMedium('deepseek-v4-flash')
      if (!modelLight.startsWith('deepseek')) setModelLight('deepseek-v4-flash')
      if (stage0Model && !stage0Model.startsWith('deepseek')) setStage0Model('')
    }
    // v3.5: per-stage cũng switch theo provider mới
    const prefix = provider === 'gemini' ? 'gemini' : provider === 'openai' ? 'gpt' : 'deepseek'
    setStageModels(prev => {
      const next = { ...prev }
      for (const st of STAGES) {
        const cur = prev[st.key] || ''
        if (cur && !cur.startsWith(prefix)) {
          // Rỗng được phép với stage0 (allowEmpty) → giữ rỗng
          next[st.key] = st.allowEmpty && !cur ? '' : st.defaultModel[provider]
        }
        // Nếu trống và không allowEmpty → set default
        if (!cur && !st.allowEmpty) {
          next[st.key] = st.defaultModel[provider]
        }
      }
      return next
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider])

  function buildConfig(): TranslateConfig {
    return {
      api_key: apiKey.trim(),
      provider,
      // Legacy tier (backend backward compat)
      model_heavy: modelHeavy.trim(),
      model_medium: modelMedium.trim(),
      model_light: modelLight.trim(),
      heavy_thinking: heavyThinking,
      medium_thinking: mediumThinking,
      light_thinking: lightThinking,
      translate_thinking: translateThinking,
      // v3.5: per-stage
      model_stage0:      stageModels.stage0.trim() || null,
      model_stage1:      stageModels.stage1.trim() || null,
      model_stage2:      stageModels.stage2.trim() || null,
      model_stage3:      stageModels.stage3.trim() || null,
      model_stage4:      stageModels.stage4.trim() || null,
      model_stage5:      stageModels.stage5.trim() || null,
      model_retranslate: stageModels.retranslate.trim() || null,
      thinking_stage0:      stageThinking.stage0,
      thinking_stage1:      stageThinking.stage1,
      thinking_stage2:      stageThinking.stage2,
      thinking_stage3:      stageThinking.stage3,
      thinking_stage4:      stageThinking.stage4,
      thinking_stage5:      stageThinking.stage5,
      thinking_retranslate: stageThinking.retranslate,
      project_type: projectType,
      cps_max: cpsMax ? parseFloat(cpsMax) : null,
      concurrency,
      source_lang: 'zh',
      variant_mode: variantMode,
      chunk_overlap: chunkOverlap,
      cache_enabled: cacheEnabled,
      chunks_parallel: chunksParallel,
      speaker_parallel: speakerParallel,
      speaker_context_window: speakerContextWindow,
      stage0_enabled: stage0Enabled,
      stage0_model: stage0Model.trim() || null,
      stage0_context_window: stage0ContextWindow,
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
  const hasChunks = (status?.chunk_count ?? 0) > 0
  const hasSpeaker = (status?.speaker_assigned_count ?? 0) > 0
  const hasTranslated = (status?.translated_count ?? 0) > 0
  const hasNormalized = ((status?.cleaned_count ?? 0) + (status?.removed_count ?? 0)) > 0

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl w-full max-w-3xl max-h-[90vh] overflow-auto"
           onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="px-5 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center">
          <h2 className="text-base font-semibold text-zinc-800 dark:text-zinc-100">
            Cấu hình Pipeline dịch (v3)
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
              {(['gemini', 'openai', 'deepseek'] as const).map(p => {
                const hasKey = !!apiKeys[p]
                return (
                  <button
                    key={p}
                    onClick={() => setProvider(p)}
                    className={`px-3 py-2 rounded-lg border text-[13px] font-medium transition-all relative ${
                      provider === p
                        ? 'border-blue-500 bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-300'
                        : 'border-zinc-200 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800'
                    }`}
                  >
                    <span className="flex items-center justify-center gap-1.5">
                      {p === 'gemini' && '🤖 Gemini'}
                      {p === 'openai' && '🧠 OpenAI'}
                      {p === 'deepseek' && '🐳 DeepSeek'}
                      {hasKey && (
                        <span className="text-[10px] text-emerald-600 dark:text-emerald-400" title="Có API key">●</span>
                      )}
                    </span>
                  </button>
                )
              })}
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
                Key của <span className="font-medium text-zinc-700 dark:text-zinc-300">{provider}</span> lưu riêng trong browser.
              </span>
              {apiKey && (
                <span className="text-green-600 dark:text-green-400 ml-auto">
                  ✓ {apiKey.length} ký tự
                </span>
              )}
            </div>
          </section>

          {/* Models — v3.5: gom theo từng Stage, mỗi stage 1 model độc lập */}
          <section>
            <SectionLabel>2. Models — chọn cho từng Stage</SectionLabel>
            <div className="text-[11px] text-zinc-500 mb-3 leading-snug">
              Mỗi Stage chọn model độc lập. Stage 4 Translate là task chính,
              các stage khác có thể dùng model rẻ hơn để tiết kiệm chi phí.
            </div>
            <div className="space-y-2.5">
              {STAGES.map(st => (
                <StageModelCard
                  key={st.key}
                  stage={st}
                  provider={provider}
                  value={stageModels[st.key]}
                  onChange={v => setStageModel(st.key, v)}
                  thinking={stageThinking[st.key]}
                  onThinkingChange={v => setStageThinkingFor(st.key, v)}
                />
              ))}
            </div>
          </section>

          {/* Project type */}
          <section>
            <SectionLabel>3. Loại project</SectionLabel>
            <div className="grid grid-cols-3 gap-2">
              <TypeButton active={projectType === 'short_drama'} onClick={() => setProjectType('short_drama')}
                title="Short drama" desc="60 tập × 2 phút, CPS ≤22" />
              <TypeButton active={projectType === 'drama_series'} onClick={() => setProjectType('drama_series')}
                title="Drama series" desc="40-45 phút/tập, CPS ≤20" />
              <TypeButton active={projectType === 'movie'} onClick={() => setProjectType('movie')}
                title="Movie" desc="Phim điện ảnh 1.5-2h" />
            </div>
          </section>

          {/* v3: Variant mode */}
          <section>
            <SectionLabel>4. Variant — 2 bản dịch (v3 mới)</SectionLabel>
            <div className="grid grid-cols-1 gap-2">
              <VariantOption
                active={variantMode === 'off'} onClick={() => setVariantMode('off')}
                title="🔘 Tắt — chỉ 1 bản" desc="Tiết kiệm token nhất. Chỉ dùng text_v1 (sát nghĩa)." />
              <VariantOption
                active={variantMode === 'important_only'} onClick={() => setVariantMode('important_only')}
                title="⭐ Cảnh quan trọng (khuyến nghị)"
                desc="Cảnh HOOK/PEAK/intimate/angry có 2 bản (v1 sát nghĩa + v2 thoát ý). Tăng ~24% cost." />
              <VariantOption
                active={variantMode === 'always'} onClick={() => setVariantMode('always')}
                title="✨ Luôn 2 bản"
                desc="Mọi dòng đều có 2 bản. Tăng ~80% cost. Dành cho phim ngắn cần chất lượng tối đa." />
            </div>
          </section>

          {/* Advanced v3 */}
          <details open>
            <summary className="cursor-pointer text-[11px] font-semibold text-zinc-400 uppercase tracking-widest hover:text-zinc-600">
              5. Tùy chọn nâng cao
            </summary>
            <div className="mt-3 grid grid-cols-2 gap-3">
              <div>
                <label className="text-[11px] font-medium text-zinc-600 dark:text-zinc-400 block mb-1">
                  CPS tối đa
                </label>
                <input
                  type="number"
                  value={cpsMax}
                  onChange={e => setCpsMax(e.target.value)}
                  placeholder="auto (22 cho short drama)"
                  className="input w-full"
                  step="0.5"
                  min="10"
                  max="30"
                />
              </div>
              <div>
                <label className="text-[11px] font-medium text-zinc-600 dark:text-zinc-400 block mb-1">
                  Concurrency
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
              <div>
                <label className="text-[11px] font-medium text-zinc-600 dark:text-zinc-400 block mb-1">
                  Chunk overlap (sliding window dòng)
                </label>
                <input
                  type="number"
                  value={chunkOverlap}
                  onChange={e => setChunkOverlap(Math.max(0, Math.min(100, parseInt(e.target.value) || 30)))}
                  className="input w-full"
                  min="0"
                  max="100"
                />
                <div className="text-[10px] text-zinc-400 mt-0.5">Mặc định 30. Tăng → mạch cảnh tốt hơn nhưng tốn token.</div>
              </div>
              <div className="flex items-center pt-5">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={cacheEnabled}
                    onChange={e => setCacheEnabled(e.target.checked)}
                    className="w-4 h-4"
                  />
                  <span className="text-[12px] text-zinc-700 dark:text-zinc-300">
                    Bật prompt caching (giảm 50-90% chi phí Bước 4)
                  </span>
                </label>
              </div>

              {/* Bước 0 — Chuẩn hóa */}
              <div className="col-span-full pt-2 border-t border-zinc-200 dark:border-zinc-800">
                <label className="text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider block mb-2">
                  Bước 0 — Chuẩn hóa phụ đề
                </label>
                <div className="grid grid-cols-[1fr_140px] gap-2 items-stretch">
                  <button
                    onClick={() => setStage0Enabled(!stage0Enabled)}
                    className={`p-2.5 rounded-lg border text-left transition-all ${
                      stage0Enabled
                        ? 'border-emerald-500 bg-emerald-50/60 dark:bg-emerald-900/20'
                        : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[12px] font-bold ${stage0Enabled ? 'text-emerald-700 dark:text-emerald-300' : 'text-zinc-700 dark:text-zinc-300'}`}>
                        {stage0Enabled ? '✓ Bật chuẩn hóa' : '✕ Tắt chuẩn hóa'}
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-500 leading-relaxed">
                      Scan dòng khả nghi (watermark, logo, filler, ký tự rác) → gửi AI phân tích context →
                      remove/clean/keep. Chạy 1 lần trước Bible. <br />
                      Model cấu hình ở mục "Stage 0" phía trên.
                    </div>
                  </button>
                  <div>
                    <label className="text-[10px] text-zinc-500 block mb-1">
                      Context ±N (dòng)
                    </label>
                    <input
                      type="number"
                      value={stage0ContextWindow}
                      onChange={e => setStage0ContextWindow(Math.max(0, Math.min(10, parseInt(e.target.value) || 2)))}
                      disabled={!stage0Enabled}
                      className="input w-full disabled:opacity-50"
                      min="0"
                      max="10"
                    />
                    <div className="text-[9px] text-zinc-400 mt-0.5 leading-tight">
                      ±N dòng quanh mỗi nghi ngờ.
                    </div>
                  </div>
                </div>
              </div>

              {/* Bước 2 mode */}
              <div className="col-span-full pt-2 border-t border-zinc-200 dark:border-zinc-800">
                <label className="text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider block mb-2">
                  Bước 2 — Chia chunks
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <button
                    onClick={() => setChunksParallel(false)}
                    className={`p-2.5 rounded-lg border text-left transition-all ${
                      !chunksParallel
                        ? 'border-blue-500 bg-blue-50/60 dark:bg-blue-900/20'
                        : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[12px] font-bold ${!chunksParallel ? 'text-blue-700 dark:text-blue-300' : 'text-zinc-700 dark:text-zinc-300'}`}>
                        🔁 Tuần tự (khuyến nghị)
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-500 leading-relaxed">
                      Cache Bible giữa các arc → giảm 50-90% input cost.
                      Chậm hơn ~30% (vd 50s thay vì 30s).
                    </div>
                  </button>
                  <button
                    onClick={() => setChunksParallel(true)}
                    className={`p-2.5 rounded-lg border text-left transition-all ${
                      chunksParallel
                        ? 'border-amber-500 bg-amber-50/60 dark:bg-amber-900/20'
                        : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[12px] font-bold ${chunksParallel ? 'text-amber-700 dark:text-amber-300' : 'text-zinc-700 dark:text-zinc-300'}`}>
                        ⚡ Song song
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-500 leading-relaxed">
                      Tất cả arcs cùng lúc. Nhanh hơn nhưng tốn token gấp ~2x
                      (không cache giữa arcs).
                    </div>
                  </button>
                </div>
              </div>

              {/* Bước 3 mode */}
              <div className="col-span-full pt-2 border-t border-zinc-200 dark:border-zinc-800">
                <label className="text-[11px] font-semibold text-zinc-600 dark:text-zinc-400 uppercase tracking-wider block mb-2">
                  Bước 3 — Gán speaker
                </label>
                <div className="grid grid-cols-[1fr_1fr_140px] gap-2 items-stretch">
                  <button
                    onClick={() => setSpeakerParallel(true)}
                    className={`p-2.5 rounded-lg border text-left transition-all ${
                      speakerParallel
                        ? 'border-amber-500 bg-amber-50/60 dark:bg-amber-900/20'
                        : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[12px] font-bold ${speakerParallel ? 'text-amber-700 dark:text-amber-300' : 'text-zinc-700 dark:text-zinc-300'}`}>
                        ⚡ Song song (khuyến nghị)
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-500 leading-relaxed">
                      25 chunks chạy {concurrency} song song. Nhanh, mỗi chunk có cache prefix Bible riêng.
                    </div>
                  </button>
                  <button
                    onClick={() => setSpeakerParallel(false)}
                    className={`p-2.5 rounded-lg border text-left transition-all ${
                      !speakerParallel
                        ? 'border-blue-500 bg-blue-50/60 dark:bg-blue-900/20'
                        : 'border-zinc-200 dark:border-zinc-700 hover:border-zinc-300'
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span className={`text-[12px] font-bold ${!speakerParallel ? 'text-blue-700 dark:text-blue-300' : 'text-zinc-700 dark:text-zinc-300'}`}>
                        🔁 Tuần tự
                      </span>
                    </div>
                    <div className="text-[10px] text-zinc-500 leading-relaxed">
                      Cache Bible giữa chunks tốt hơn. Chậm hơn ~3x. Chỉ dùng khi quota hạn chế.
                    </div>
                  </button>
                  <div>
                    <label className="text-[10px] text-zinc-500 block mb-1">
                      Context window (dòng)
                    </label>
                    <input
                      type="number"
                      value={speakerContextWindow}
                      onChange={e => setSpeakerContextWindow(Math.max(0, Math.min(50, parseInt(e.target.value) || 20)))}
                      className="input w-full"
                      min="0"
                      max="50"
                    />
                    <div className="text-[9px] text-zinc-400 mt-0.5 leading-tight">
                      Mặc định 20. Dòng trước/sau chunk làm context.
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </details>
        </div>

        {/* Footer — actions */}
        <div className="px-5 py-4 border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-950">
          <div className="flex items-center gap-2 mb-3">
            <button onClick={handleStart} className="btn-primary flex-1 py-2">
              ▶ Bắt đầu toàn bộ pipeline ({stage0Enabled ? '5' : '4'} stage)
            </button>
            <button
              onClick={handleSave}
              className="px-4 py-2 rounded-lg border border-zinc-300 dark:border-zinc-700 hover:bg-white dark:hover:bg-zinc-900 text-[13px] font-medium text-zinc-700 dark:text-zinc-300 relative min-w-[110px]"
            >
              {savedTick > 0 ? (
                <span className="text-emerald-600 dark:text-emerald-400">✓ Đã lưu</span>
              ) : (
                <span>💾 Lưu cấu hình</span>
              )}
            </button>
          </div>

          <div className="text-[10px] text-zinc-400 text-center mb-3 italic">
            Cấu hình tự lưu vào trình duyệt mỗi khi bạn thay đổi. Nút "Lưu" để xác nhận thủ công.
          </div>

          <div className="text-[11px] font-semibold text-zinc-400 uppercase tracking-widest mb-2">
            Hoặc chạy 1 stage cụ thể (resume / debug)
          </div>
          <div className="grid grid-cols-6 gap-2">
            <StageButton onClick={() => handleRunStage('normalize')} done={hasNormalized}>0. Chuẩn hóa</StageButton>
            <StageButton onClick={() => handleRunStage('bible')} done={hasBible}>1. Bible</StageButton>
            <StageButton onClick={() => handleRunStage('chunks')} done={hasChunks} disabled={!hasBible}>2. Chunks</StageButton>
            <StageButton onClick={() => handleRunStage('speaker')} done={hasSpeaker} disabled={!hasChunks}>3. Speaker</StageButton>
            <StageButton onClick={() => handleRunStage('translate')} done={hasTranslated} disabled={!hasChunks}>4. Translate</StageButton>
            <StageButton onClick={() => handleRunStage('polish')} disabled={!hasBible}>5. Retry</StageButton>
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

// ─── StageModelCard — UI v3.5 ─────────────────────────────────────────────
// 1 card per Stage. Title TO + ĐẬM ở trên, mô tả nhỏ ở dưới, dropdown rộng,
// thinking toggle. Card Stage 4 có viền nổi bật vì là task chính.

function StageModelCard({
  stage, provider, value, onChange, thinking, onThinkingChange,
}: {
  stage: StageDef
  provider: 'gemini' | 'openai' | 'deepseek'
  value: string
  onChange: (v: string) => void
  thinking: boolean
  onThinkingChange: (v: boolean) => void
}) {
  const options = MODELS[provider] || []
  const known = options.find(m => m.id === value)
  const [customMode, setCustomMode] = React.useState(!known && !!value)

  React.useEffect(() => {
    if (options.find(m => m.id === value)) setCustomMode(false)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, provider])

  // Thinking hỗ trợ: Gemini 2.5+/3.x, GPT-5/o-series, DeepSeek V4 Pro/Flash
  // v3.7.4: thêm DeepSeek V4 (hỗ trợ thinking mode official)
  const thinkingSupported =
    value.startsWith('gemini-2.5') ||
    value.startsWith('gemini-3') ||
    value.startsWith('o1') || value.startsWith('o3') || value.startsWith('o4') ||
    value.startsWith('gpt-5') ||
    value.startsWith('deepseek-v4') ||
    value.startsWith('deepseek-reasoner')

  // Card viền nổi bật cho Stage 4 (task chính)
  const containerClass = stage.isMain
    ? 'border-2 border-rose-300 dark:border-rose-700 rounded-xl p-3 bg-rose-50/50 dark:bg-rose-950/20 shadow-sm'
    : 'border border-zinc-200 dark:border-zinc-700 rounded-xl p-3 bg-white dark:bg-zinc-900/40'

  return (
    <div className={containerClass}>
      {/* Header: badge + title to + desc */}
      <div className="flex items-start gap-2 mb-2">
        <span className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase tracking-wide whitespace-nowrap mt-0.5 ${stage.badgeColor}`}>
          {stage.key === 'retranslate' ? 'Editor' : stage.key.replace('stage', 'S')}
        </span>
        <div className="flex-1 min-w-0">
          <div className={`text-[14px] font-bold text-zinc-900 dark:text-zinc-100 leading-tight ${stage.isMain ? 'text-rose-700 dark:text-rose-300' : ''}`}>
            {stage.title}
          </div>
          <div className="text-[11px] text-zinc-500 dark:text-zinc-400 leading-snug mt-0.5">
            {stage.desc}
          </div>
        </div>
        <button
          type="button"
          onClick={() => setCustomMode(c => !c)}
          className="text-[10px] text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-300 underline whitespace-nowrap"
        >
          {customMode ? '← Dropdown' : '✎ Gõ tay'}
        </button>
      </div>

      {/* Model selector */}
      {customMode ? (
        <input
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder={stage.allowEmpty ? "(trống = dùng mặc định)" : "Tên model (vd: gemini-2.5-pro)"}
          className="input w-full text-[12px] font-mono"
        />
      ) : (
        <>
          <select
            value={value}
            onChange={e => onChange(e.target.value)}
            className="input w-full text-[12px]"
          >
            {stage.allowEmpty && (
              <option value="">{stage.emptyLabel || '↪ Dùng mặc định'}</option>
            )}
            {options.map(m => (
              <option key={m.id} value={m.id}>
                {m.label}  ·  ${m.priceIn}/${m.priceOut} per 1M
              </option>
            ))}
          </select>
          {known && (
            <div className="text-[10px] text-zinc-500 mt-1 leading-snug">
              {known.desc}
            </div>
          )}
          {!known && !value && stage.allowEmpty && (
            <div className="text-[10px] text-zinc-500 mt-1 leading-snug">
              Đang dùng model mặc định. Tiết kiệm, đủ cho task này.
            </div>
          )}
        </>
      )}

      {/* Thinking toggle */}
      <div className="mt-2 pt-2 border-t border-zinc-200 dark:border-zinc-700 flex items-center gap-2">
        <label className="flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={thinking}
            onChange={e => onThinkingChange(e.target.checked)}
            disabled={!thinkingSupported}
            className="w-3.5 h-3.5"
          />
          <span className={`text-[11px] font-medium ${
            thinkingSupported ? 'text-zinc-700 dark:text-zinc-300' : 'text-zinc-400'
          }`}>
            🧠 Thinking {thinking ? 'BẬT' : 'TẮT'}
          </span>
        </label>
        <span className="text-[10px] text-zinc-500 leading-snug flex-1">
          {!thinkingSupported
            ? '(không hỗ trợ với model này)'
            : stage.thinkingHint}
        </span>
      </div>
    </div>
  )
}

// ─── ModelSelector (legacy) — giữ để các nơi khác (nếu có) vẫn import được ────

function ModelSelector({ tier, stages, provider, value, onChange, allowEmpty, emptyLabel,
                        thinking, onThinkingChange, thinkingHint }: {
  tier: string
  stages: string
  provider: 'gemini' | 'openai' | 'deepseek'
  value: string
  onChange: (v: string) => void
  allowEmpty?: boolean
  emptyLabel?: string
  thinking?: boolean
  onThinkingChange?: (v: boolean) => void
  thinkingHint?: string
}) {
  const options = MODELS[provider] || []
  const known = options.find(m => m.id === value)
  const [customMode, setCustomMode] = React.useState(!known && !!value)

  React.useEffect(() => {
    if (options.find(m => m.id === value)) {
      setCustomMode(false)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, provider])

  const tierColor =
    tier === 'Heavy' ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
    : tier === 'Translate' ? 'bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300'
    : tier === 'Medium' ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300'
    : tier === 'Light' ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300'
    : 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300'

  const thinkingSupported = thinking !== undefined && (
    value.startsWith('gemini-2.5') ||
    value.startsWith('gemini-3') ||
    value.startsWith('o1') || value.startsWith('o3') || value.startsWith('o4') ||
    value.startsWith('gpt-5') ||
    value.startsWith('deepseek-v4') ||
    value.startsWith('deepseek-reasoner')
  )

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
          placeholder={allowEmpty ? "(trống = dùng Light)" : "Tên model (vd: gemini-2.5-pro)"}
          className="input w-full text-[12px] font-mono"
        />
      ) : (
        <>
          <select
            value={value}
            onChange={e => onChange(e.target.value)}
            className="input w-full text-[12px]"
          >
            {allowEmpty && (
              <option value="">{emptyLabel || '↪ Dùng Light (mặc định)'}</option>
            )}
            {options.map(m => (
              <option key={m.id} value={m.id}>
                {m.label}  ·  ${m.priceIn}/${m.priceOut} per 1M
              </option>
            ))}
          </select>
          {known && (
            <div className="text-[10px] text-zinc-500 mt-1 leading-snug">
              {known.desc}
            </div>
          )}
          {!known && !value && allowEmpty && (
            <div className="text-[10px] text-zinc-500 mt-1 leading-snug">
              Đang dùng model Light. Tiết kiệm, đủ cho tác vụ phân tích noise.
            </div>
          )}
        </>
      )}

      {thinking !== undefined && onThinkingChange && (
        <div className="mt-2 pt-2 border-t border-zinc-200 dark:border-zinc-700 flex items-center gap-2">
          <label className="flex items-center gap-1.5 cursor-pointer select-none">
            <input
              type="checkbox"
              checked={thinking}
              onChange={e => onThinkingChange(e.target.checked)}
              disabled={!thinkingSupported}
              className="w-3.5 h-3.5"
            />
            <span className={`text-[11px] font-medium ${
              thinkingSupported ? 'text-zinc-700 dark:text-zinc-300' : 'text-zinc-400'
            }`}>
              🧠 Thinking {thinking ? 'BẬT' : 'TẮT'}
            </span>
          </label>
          <span className="text-[10px] text-zinc-500 leading-snug flex-1">
            {!thinkingSupported
              ? '(không hỗ trợ với model này)'
              : (thinkingHint || (thinking
                  ? 'Chậm + tốn output token hơn, chất lượng cao hơn'
                  : 'Nhanh + rẻ, hợp task JSON đơn giản'))}
          </span>
        </div>
      )}
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

function VariantOption({ active, onClick, title, desc }: {
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
      <div className="text-[11px] text-zinc-500 mt-0.5 leading-snug">{desc}</div>
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