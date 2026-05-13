/**
 * RetranslateModal v2 — dịch lại 1 dòng phụ đề với hint từ user.
 *
 * Dùng Bible đã lưu trong DB làm context, có ngữ cảnh 3 dòng trước/sau.
 * Cho phép 1-3 variants, user chọn 1 để áp dụng.
 */
import React, { useState, useEffect } from 'react'
import { translateApi } from '../api'

interface Props {
  projectId: number
  subtitleId: number
  originalText: string
  currentText: string
  onClose: () => void
  onApply: (newText: string) => void
}

interface StoredSettings {
  api_key: string
  provider: 'gemini' | 'openai' | 'deepseek'
  model: string
}

const STORAGE_KEY = 'translate_config_v2'

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

export default function RetranslateModal({
  projectId, subtitleId, originalText, currentText, onClose, onApply,
}: Props) {
  const [hint, setHint] = useState('')
  const [variants, setVariants] = useState(2)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [results, setResults] = useState<string[]>([])
  const [tokens, setTokens] = useState<{ in: number; out: number } | null>(null)

  async function handleRun() {
    setErr(''); setResults([])
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
        variants,
      })
      setResults(r.variants || [])
      setTokens({ in: r.tokens_in, out: r.tokens_out })
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Lỗi không rõ')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4"
         onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-auto"
           onClick={e => e.stopPropagation()}>

        <div className="px-5 py-4 border-b border-zinc-200 dark:border-zinc-800 flex items-center">
          <h2 className="text-base font-semibold text-zinc-800 dark:text-zinc-100">
            🔄 Dịch lại
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

          {/* Variants */}
          <div className="flex items-center gap-3">
            <label className="text-[12px] text-zinc-600 dark:text-zinc-400">Số phương án:</label>
            <div className="flex gap-1">
              {[1, 2, 3].map(n => (
                <button
                  key={n}
                  onClick={() => setVariants(n)}
                  className={`px-3 py-1.5 rounded text-[12px] font-medium ${
                    variants === n
                      ? 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300'
                      : 'bg-zinc-100 dark:bg-zinc-800 text-zinc-600'
                  }`}
                >
                  {n}
                </button>
              ))}
            </div>
            <div className="flex-1" />
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
          {results.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold text-zinc-500 uppercase tracking-widest mb-2">
                Phương án mới {tokens && <span className="text-zinc-400 normal-case font-normal">· {tokens.in}/{tokens.out} tokens</span>}
              </div>
              <div className="space-y-2">
                {results.map((text, i) => (
                  <div
                    key={i}
                    className="px-3 py-2 rounded-lg border border-zinc-200 dark:border-zinc-700 hover:border-blue-400 dark:hover:border-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 cursor-pointer transition-colors group"
                    onClick={() => onApply(text)}
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] text-zinc-500">#{i + 1}</span>
                      <span className="flex-1 text-sm text-zinc-800 dark:text-zinc-100">{text}</span>
                      <button className="btn-primary text-[11px] opacity-0 group-hover:opacity-100 transition-opacity">
                        Chọn
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
