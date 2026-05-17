/**
 * RetranslateModal v3 — dịch lại 1 dòng phụ đề.
 *
 * Backend luôn trả 2 bản:
 * - new_text_v1: sát nghĩa (cho subtitle)
 * - new_text_v2: thoát ý (cho lồng tiếng)
 * 
 * User chọn 1 bản để apply (lưu vào text active). Backend tự lưu cả 2 vào DB.
 */
import React, { useState } from 'react'
import { translateApi } from '../api'

interface Props {
  projectId: number
  subtitleId: number
  originalText: string
  currentText: string
  onClose: () => void
  onApply: (params: {
    text: string
    variant: 1 | 2
    text_v1: string
    text_v2: string | null
  }) => void
}

interface StoredSettings {
  api_key: string
  provider: 'gemini' | 'openai' | 'deepseek'
  model: string
}

const STORAGE_KEY = 'translate_config_v3'
const RT_THINKING_KEY = 'retranslate_thinking_v1'   // toggle riêng cho modal Dịch lại

function loadSettings(): StoredSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const s = JSON.parse(raw)
      return {
        api_key: s.api_key || '',
        provider: s.provider || 'gemini',
        model: s.model_medium || s.model_heavy || 'gemini-2.5-flash',
      }
    }
  } catch {}
  return { api_key: '', provider: 'gemini', model: 'gemini-2.5-flash' }
}

function loadThinking(): boolean {
  try {
    const raw = localStorage.getItem(RT_THINKING_KEY)
    if (raw === 'true') return true
    if (raw === 'false') return false
  } catch {}
  return false   // mặc định TẮT — nhanh + rẻ, hợp dịch lại 1 dòng
}

function saveThinking(v: boolean) {
  try { localStorage.setItem(RT_THINKING_KEY, String(v)) } catch {}
}

export default function RetranslateModal({
  projectId, subtitleId, originalText, currentText, onClose, onApply,
}: Props) {
  const [hint, setHint] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [resultV1, setResultV1] = useState<string>('')
  const [resultV2, setResultV2] = useState<string | null>(null)
  const [resultEmotion, setResultEmotion] = useState<string | null>(null)
  const [resultIntensity, setResultIntensity] = useState<number | null>(null)
  const [tokens, setTokens] = useState<{ in: number; out: number } | null>(null)
  // v3.3: toggle thinking — mặc định tắt (nhanh, rẻ); persist localStorage
  const [thinking, setThinking] = useState<boolean>(() => loadThinking())

  async function handleRun() {
    setErr('')
    setResultV1('')
    setResultV2(null)
    setResultEmotion(null)
    setResultIntensity(null)
    setTokens(null)

    const settings = loadSettings()
    if (!settings.api_key) {
      setErr('Chưa có API key. Vào trang Translate → Cấu hình để set.')
      return
    }

    setBusy(true)
    try {
      const r = await translateApi.retranslate(projectId, {
        subtitle_id: subtitleId,
        hint: hint.trim(),
        api_key: settings.api_key,
        provider: settings.provider,
        model: settings.model,
        thinking,
      })
      setResultV1(r.new_text_v1 || '')
      setResultV2(r.new_text_v2 || null)
      setResultEmotion(r.emotion || null)
      setResultIntensity(r.intensity ?? null)
      setTokens({ in: r.tokens_in, out: r.tokens_out })
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Lỗi không rõ')
    } finally {
      setBusy(false)
    }
  }

  function pick(variant: 1 | 2) {
    const text = variant === 1 ? resultV1 : (resultV2 || resultV1)
    onApply({
      text,
      variant,
      text_v1: resultV1,
      text_v2: resultV2,
    })
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-auto"
           onClick={e => e.stopPropagation()}>

        <div className="px-5 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center">
          <h2 className="text-base font-semibold text-zinc-800 dark:text-zinc-100">
            🔄 Dịch lại — 2 phương án
          </h2>
          <div className="flex-1" />
          <button onClick={onClose} className="btn">✕</button>
        </div>

        <div className="p-5 space-y-4">
          {/* Original */}
          <div>
            <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1">
              Nguyên bản (Trung)
            </div>
            <div className="text-sm px-3 py-2 rounded bg-zinc-50 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
              {originalText}
            </div>
          </div>

          {/* Current */}
          <div>
            <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1">
              Bản hiện tại (Việt)
            </div>
            <div className="text-sm px-3 py-2 rounded bg-zinc-50 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300">
              {currentText || <em className="text-zinc-400">(empty)</em>}
            </div>
          </div>

          {/* Hint */}
          <div>
            <label className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-1 block">
              Yêu cầu (tùy chọn)
            </label>
            <textarea
              value={hint}
              onChange={e => setHint(e.target.value)}
              placeholder="VD: 'Tone giận hơn', 'Câu ngắn hơn cho TTS', 'Đổi xưng hô anh-em'..."
              className="input w-full"
              rows={2}
            />
          </div>

          {/* Run button + Thinking toggle */}
          <div className="flex items-center gap-3 flex-wrap">
            <label className="flex items-center gap-2 px-2.5 py-1 rounded-lg border border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/50 cursor-pointer select-none"
              title="Thinking: bật cho chất lượng cao hơn (chậm + tốn token), tắt cho tốc độ + tiết kiệm">
              <input
                type="checkbox"
                checked={thinking}
                onChange={e => { setThinking(e.target.checked); saveThinking(e.target.checked) }}
                className="accent-blue-600 w-3.5 h-3.5"
              />
              <span className="text-[12px] font-medium text-zinc-700 dark:text-zinc-200">
                🧠 Thinking
              </span>
              <span className="text-[10px] text-zinc-400">
                {thinking ? '(chậm, chất lượng cao)' : '(nhanh, rẻ)'}
              </span>
            </label>
            <div className="text-[11px] text-zinc-500 flex-1 min-w-0">
              Tự động trả 2 bản: sát nghĩa (v1) + thoát ý (v2)
            </div>
            <button
              onClick={handleRun}
              disabled={busy}
              className="btn-primary"
            >
              {busy ? '⏳ Đang dịch...' : '⚡ Tạo bản dịch'}
            </button>
          </div>

          {/* Error */}
          {err && (
            <div className="text-[12px] text-red-700 dark:text-red-400 bg-red-50 dark:bg-red-900/20 px-3 py-2 rounded">
              {err}
            </div>
          )}

          {/* Results */}
          {resultV1 && (
            <div>
              <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-2 flex items-center gap-2">
                <span>Kết quả</span>
                {resultEmotion && (
                  <span className="text-zinc-400 normal-case font-normal">
                    · emotion: {resultEmotion}{resultIntensity ? `·${resultIntensity}` : ''}
                  </span>
                )}
                {tokens && (
                  <span className="text-zinc-400 normal-case font-normal ml-auto">
                    {tokens.in}/{tokens.out} tokens
                  </span>
                )}
              </div>

              {/* V1 — sát nghĩa */}
              <div className="px-3 py-3 rounded-lg border-2 border-blue-200 dark:border-blue-900 hover:border-blue-500 dark:hover:border-blue-500 bg-blue-50/30 dark:bg-blue-900/10 cursor-pointer transition-all group mb-2"
                onClick={() => pick(1)}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-[10px] font-bold text-blue-700 dark:text-blue-300 px-1.5 rounded bg-blue-100 dark:bg-blue-900/40">
                    v1 · SÁT NGHĨA
                  </span>
                  <span className="text-[10px] text-zinc-500">Phù hợp subtitle, chính xác cao</span>
                  <div className="flex-1" />
                  <button className="btn-primary text-[11px] opacity-0 group-hover:opacity-100 transition-opacity">
                    Chọn v1
                  </button>
                </div>
                <div className="text-[14px] text-zinc-800 dark:text-zinc-100">
                  {resultV1}
                </div>
              </div>

              {/* V2 — thoát ý (nếu có) */}
              {resultV2 ? (
                <div className="px-3 py-3 rounded-lg border-2 border-purple-200 dark:border-purple-900 hover:border-purple-500 dark:hover:border-purple-500 bg-purple-50/30 dark:bg-purple-900/10 cursor-pointer transition-all group"
                  onClick={() => pick(2)}>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-[10px] font-bold text-purple-700 dark:text-purple-300 px-1.5 rounded bg-purple-100 dark:bg-purple-900/40">
                      v2 · THOÁT Ý
                    </span>
                    <span className="text-[10px] text-zinc-500">Phù hợp lồng tiếng, tự nhiên hơn</span>
                    <div className="flex-1" />
                    <button className="text-[11px] px-2 py-0.5 rounded bg-purple-600 hover:bg-purple-700 text-white opacity-0 group-hover:opacity-100 transition-opacity">
                      Chọn v2
                    </button>
                  </div>
                  <div className="text-[14px] text-zinc-800 dark:text-zinc-100">
                    {resultV2}
                  </div>
                </div>
              ) : (
                <div className="px-3 py-2 rounded-lg border border-dashed border-zinc-300 dark:border-zinc-700 text-[11px] text-zinc-400 italic">
                  AI không tạo bản v2 (dòng đơn giản hoặc chỉ có 1 cách dịch tự nhiên)
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
