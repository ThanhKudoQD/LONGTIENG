// ─── Model catalog ───────────────────────────────────────────────────────────
// Catalog model cho 3 providers — dùng trong ConfigPanel.
// Cập nhật khi có model mới. Giá theo công bố mới nhất (USD per 1M tokens).

import type { ModelOption, Provider } from './types'

export const MODELS: Record<Provider, ModelOption[]> = {
  gemini: [
    {
      id: 'gemini-3.1-pro',
      label: 'Gemini 3.1 Pro',
      price_in_per_1m_usd: 2.00,
      price_out_per_1m_usd: 12.00,
      context_window: 2_000_000,
      desc: 'Mạnh nhất Gemini, hiểu context dài',
      tier: 'top',
    },
    {
      id: 'gemini-3.1-flash-lite',
      label: 'Gemini 3.1 Flash-Lite',
      price_in_per_1m_usd: 0.50,
      price_out_per_1m_usd: 3.00,
      context_window: 1_000_000,
      desc: 'Nhanh + thông minh, cân bằng',
      tier: 'balanced',
    },
    {
      id: 'gemini-2.5-pro',
      label: 'Gemini 2.5 Pro',
      price_in_per_1m_usd: 1.25,
      price_out_per_1m_usd: 10.00,
      context_window: 2_000_000,
      desc: 'Khuyên dùng cho task khó',
      tier: 'top',
    },
    {
      id: 'gemini-2.5-flash',
      label: 'Gemini 2.5 Flash',
      price_in_per_1m_usd: 0.30,
      price_out_per_1m_usd: 2.50,
      context_window: 1_000_000,
      desc: 'Nhanh, rẻ',
      tier: 'balanced',
    },
    {
      id: 'gemini-2.5-flash-lite',
      label: 'Gemini 2.5 Flash-Lite',
      price_in_per_1m_usd: 0.10,
      price_out_per_1m_usd: 0.40,
      context_window: 1_000_000,
      desc: 'Rẻ nhất Gemini',
      tier: 'fast',
    },
  ],
  openai: [
    {
      id: 'gpt-5',
      label: 'GPT-5',
      price_in_per_1m_usd: 1.25,
      price_out_per_1m_usd: 10.00,
      context_window: 400_000,
      desc: 'Top model OpenAI',
      tier: 'top',
    },
    {
      id: 'gpt-5-mini',
      label: 'GPT-5 Mini',
      price_in_per_1m_usd: 0.25,
      price_out_per_1m_usd: 2.00,
      context_window: 400_000,
      desc: 'Cân bằng',
      tier: 'balanced',
    },
    {
      id: 'gpt-5-nano',
      label: 'GPT-5 Nano',
      price_in_per_1m_usd: 0.05,
      price_out_per_1m_usd: 0.40,
      context_window: 400_000,
      desc: 'Rẻ nhất OpenAI',
      tier: 'fast',
    },
    {
      id: 'gpt-4o',
      label: 'GPT-4o',
      price_in_per_1m_usd: 2.50,
      price_out_per_1m_usd: 10.00,
      context_window: 128_000,
      desc: 'Gen cũ, vẫn tốt',
      tier: 'top',
    },
    {
      id: 'gpt-4o-mini',
      label: 'GPT-4o Mini',
      price_in_per_1m_usd: 0.15,
      price_out_per_1m_usd: 0.60,
      context_window: 128_000,
      desc: 'Nhanh, không reasoning, JSON gọn — khuyên dùng cho dịch',
      tier: 'balanced',
    },
  ],
  deepseek: [
    {
      id: 'deepseek-v4-flash',
      label: 'DeepSeek V4 Flash',
      price_in_per_1m_usd: 0.14,
      price_out_per_1m_usd: 0.28,
      context_window: 1_000_000,
      desc: 'Rẻ nhất tổng thể. Cache hit $0.0028/1M',
      tier: 'fast',
    },
    {
      id: 'deepseek-v4-pro',
      label: 'DeepSeek V4 Pro',
      price_in_per_1m_usd: 0.435,
      price_out_per_1m_usd: 0.87,
      context_window: 1_000_000,
      desc: 'Top model DeepSeek',
      tier: 'top',
    },
  ],
}

// Mặc định cho 4 task — tối ưu chi phí/chất lượng
export const DEFAULT_TASK_MODELS: Record<'bible' | 'translate' | 'repair' | 'qa', { provider: Provider; model: string; thinking: boolean }> = {
  bible:     { provider: 'gemini', model: 'gemini-2.5-pro',         thinking: true  },
  translate: { provider: 'gemini', model: 'gemini-2.5-pro',         thinking: true  },
  repair:    { provider: 'gemini', model: 'gemini-2.5-flash',       thinking: false },
  qa:        { provider: 'gemini', model: 'gemini-2.5-flash',       thinking: false },
}

export const PROVIDER_LABELS: Record<Provider, string> = {
  gemini:   'Google Gemini',
  openai:   'OpenAI',
  deepseek: 'DeepSeek',
}

export const TASK_LABELS: Record<'bible' | 'translate' | 'repair' | 'qa', { title: string; desc: string }> = {
  bible: {
    title: 'I · Bible',
    desc: 'Trích nhân vật, quan hệ, thuật ngữ. Cần model mạnh + thinking.',
  },
  translate: {
    title: 'II · Dịch batch',
    desc: 'Task chính. Quyết định chất lượng cuối cùng — khuyên dùng model mạnh.',
  },
  repair: {
    title: 'IV · Repair',
    desc: 'Sửa lỗi đã phát hiện. Model nhẹ là đủ vì input đã rõ ràng.',
  },
  qa: {
    title: 'IV · QA',
    desc: 'Rà soát đoạn dài, tìm lỗi semantic. Optional.',
  },
}
