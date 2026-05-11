/**
 * RetranslateModal.tsx
 * Modal dịch lại 1 dòng phụ đề — AI trả 2 bản dịch, user chọn 1.
 *
 * Dùng context từ Bible (đã lưu trong project.bible_json) để dịch
 * chính xác hơn (biết nhân vật, xưng hô, thuật ngữ).
 */

import React, { useState, useEffect } from 'react'
import api from '../api'
import type { Subtitle } from '../types'

interface Props {
  subtitle: Subtitle
  projectId: number
  onApply: (newText: string) => void
  onClose: () => void
}

function loadTranslateSettings(): { api_key: string; model_pass3: string } {
  try {
    const raw = localStorage.getItem('translate_settings')
    if (raw) {
      const s = JSON.parse(raw)
      return { api_key: s.api_key || '', model_pass3: s.model_pass3 || 'gemini-2.5-flash' }
    }
  } catch {}
  return { api_key: '', model_pass3: 'gemini-2.5-flash' }
}

interface AltResult {
  text: string
  note?: string
}

export default function RetranslateModal({ subtitle, projectId, onApply, onClose }: Props) {
  const [loading, setLoading] = useState(false)
  const [alts, setAlts] = useState<AltResult[]>([])
  const [selected, setSelected] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [customText, setCustomText] = useState(subtitle.text)
  const [mode, setMode] = useState<'ai' | 'manual'>('ai')

  useEffect(() => {
    // Auto-fetch khi mở
    if (subtitle.original_text) {
      fetchAlts()
    }
  }, [])

  const fetchAlts = async () => {
    setLoading(true)
    setError('')
    setAlts([])
    setSelected(null)
    try {
      const { api_key, model_pass3 } = loadTranslateSettings()
      const res = await api.post(`/projects/${projectId}/translate/retranslate`, {
        subtitle_id: subtitle.id,
        original_text: subtitle.original_text || subtitle.text,
        current_text: subtitle.text,
        variants: 2,
        api_key,
        model: model_pass3,
      })
      setAlts(res.data.alternatives || [])
      if (res.data.alternatives?.length) setSelected(0)
    } catch (err: any) {
      setError(err?.response?.data?.detail || err?.message || 'Lỗi dịch lại')
    } finally {
      setLoading(false)
    }
  }

  const handleApply = () => {
    if (mode === 'manual') {
      onApply(customText)
    } else if (selected !== null && alts[selected]) {
      onApply(alts[selected].text)
    }
    onClose()
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center" style={{ zIndex: 99999 }}>
      {/* Backdrop */}
      <div onClick={onClose} className="absolute inset-0 bg-black/60 backdrop-blur-sm" />

      {/* Modal */}
      <div className="relative z-10 flex flex-col bg-white dark:bg-zinc-900 rounded-2xl border border-zinc-200 dark:border-zinc-700 shadow-2xl overflow-hidden"
        style={{ width: 520, animation: 'popIn .18s ease' }}>

        {/* Header */}
        <div className="flex items-start gap-3 px-4 py-3 border-b border-zinc-200 dark:border-zinc-700">
          <div className="flex-1 min-w-0">
            <div className="text-[13px] font-bold text-zinc-800 dark:text-zinc-100">
              Dịch lại phụ đề #{subtitle.index}
            </div>
            {subtitle.original_text && (
              <div className="mt-1.5 px-2.5 py-1.5 rounded-lg bg-zinc-100 dark:bg-zinc-800 text-[12px] font-mono text-zinc-500 dark:text-zinc-400 truncate">
                {subtitle.original_text}
              </div>
            )}
          </div>
          <button onClick={onClose}
            className="w-7 h-7 flex items-center justify-center rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-400 hover:text-zinc-600 bg-white dark:bg-zinc-800 text-[15px] flex-shrink-0 transition-colors">
            ×
          </button>
        </div>

        {/* Mode tabs */}
        <div className="flex border-b border-zinc-200 dark:border-zinc-700">
          {([['ai', '✨ AI gợi ý'], ['manual', '✏️ Tự nhập']] as const).map(([k, label]) => (
            <button key={k} onClick={() => setMode(k)}
              className={`flex-1 py-2.5 text-[12px] font-semibold border-b-2 transition-all ${
                mode === k
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400 bg-blue-50 dark:bg-blue-950/20'
                  : 'border-transparent text-zinc-400 dark:text-zinc-500 bg-transparent hover:text-zinc-600'
              }`}>
              {label}
            </button>
          ))}
        </div>

        {/* Body */}
        <div className="px-4 py-4 flex flex-col gap-3" style={{ minHeight: 180 }}>

          {/* Current text */}
          <div>
            <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest mb-1.5">Hiện tại</div>
            <div className="px-3 py-2 rounded-lg bg-zinc-100 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 text-[13px] text-zinc-600 dark:text-zinc-300">
              {subtitle.text}
            </div>
          </div>

          {/* AI mode */}
          {mode === 'ai' && (
            <>
              <div className="flex items-center justify-between">
                <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Bản dịch AI</div>
                <button onClick={fetchAlts} disabled={loading}
                  className="text-[11px] px-2.5 py-1 rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-500 dark:text-zinc-400 bg-white dark:bg-zinc-800 hover:bg-zinc-50 disabled:opacity-50 transition-colors">
                  {loading ? '...' : '🔄 Tạo lại'}
                </button>
              </div>

              {loading && (
                <div className="flex items-center gap-3 text-[12px] text-blue-500 py-4">
                  <div className="w-4 h-4 rounded-full border-2 border-blue-500 border-t-transparent animate-spin flex-shrink-0" />
                  Đang dịch với context Bible...
                </div>
              )}

              {error && (
                <div className="px-3 py-2.5 rounded-lg bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-[12px] text-red-500">
                  ❌ {error}
                </div>
              )}

              {!loading && alts.length > 0 && (
                <div className="flex flex-col gap-2">
                  {alts.map((alt, i) => (
                    <div key={i} onClick={() => setSelected(i)}
                      className={`px-3 py-2.5 rounded-xl cursor-pointer border-[1.5px] transition-all ${
                        selected === i
                          ? 'border-blue-500 bg-blue-50 dark:bg-blue-950/20'
                          : 'border-zinc-200 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800/60 hover:border-zinc-300'
                      }`}>
                      <div className="flex items-start gap-2.5">
                        <div className={`w-4 h-4 rounded-full flex-shrink-0 mt-0.5 border-2 transition-all ${
                          selected === i ? 'border-[5px] border-blue-500' : 'border-zinc-300 dark:border-zinc-600'
                        }`} />
                        <div className="flex-1 min-w-0">
                          <div className="text-[13px] leading-snug text-zinc-800 dark:text-zinc-100 font-medium">
                            {alt.text}
                          </div>
                          {alt.note && (
                            <div className="text-[11px] text-zinc-400 mt-1">💡 {alt.note}</div>
                          )}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {!loading && !error && alts.length === 0 && !subtitle.original_text && (
                <div className="text-center py-6 text-[12px] text-zinc-400">
                  Phụ đề này chưa có văn bản gốc tiếng Trung.<br />
                  <span className="text-[11px]">Hãy nhập thủ công hoặc dùng tab "Tự nhập".</span>
                </div>
              )}
            </>
          )}

          {/* Manual mode */}
          {mode === 'manual' && (
            <div className="flex flex-col gap-2">
              <div className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">Bản dịch mới</div>
              <textarea
                value={customText}
                onChange={e => setCustomText(e.target.value)}
                rows={4}
                autoFocus
                className="input w-full text-[13px] resize-y leading-relaxed"
              />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex gap-2 px-4 py-3 border-t border-zinc-200 dark:border-zinc-700">
          <button onClick={onClose} className="btn flex-shrink-0">Huỷ</button>
          <button
            onClick={handleApply}
            disabled={mode === 'ai' ? (loading || selected === null || alts.length === 0) : !customText.trim()}
            className="btn-primary flex-1 justify-center disabled:opacity-50">
            ✓ Áp dụng bản dịch này
          </button>
        </div>
      </div>

      <style>{`
        @keyframes popIn {
          from { transform: scale(.95); opacity: 0 }
          to   { transform: scale(1);   opacity: 1 }
        }
        @keyframes spin { to { transform: rotate(360deg) } }
      `}</style>
    </div>
  )
}