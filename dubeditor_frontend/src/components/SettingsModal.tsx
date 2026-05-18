import React, { useEffect, useState } from 'react'
import { settingsApi } from '../api'
import type { ApiKeys, ModelPreset } from '../types'

/**
 * Modal quản lý cài đặt global của app:
 *   1. 3 API keys (Gemini / OpenAI / DeepSeek)
 *   2. CRUD Model Presets — preset chứa model cho 6 stage + retranslate
 *
 * Mở bằng nút "⚙ Cài đặt" ở ProjectList hoặc TranslatePage.
 */
export default function SettingsModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab] = useState<'keys' | 'presets'>('keys')

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-xl w-[800px] max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b">
          <h2 className="text-lg font-semibold">⚙ Cài đặt</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-700 text-xl">
            ✕
          </button>
        </div>

        {/* Tabs */}
        <div className="flex border-b">
          <button
            onClick={() => setTab('keys')}
            className={`px-4 py-2 text-sm ${tab === 'keys' ? 'border-b-2 border-blue-500 text-blue-600 font-medium' : 'text-zinc-600'}`}
          >
            🔑 API Keys
          </button>
          <button
            onClick={() => setTab('presets')}
            className={`px-4 py-2 text-sm ${tab === 'presets' ? 'border-b-2 border-blue-500 text-blue-600 font-medium' : 'text-zinc-600'}`}
          >
            🎛 Preset Model
          </button>
        </div>

        {/* Body */}
        <div className="p-4 overflow-y-auto flex-1">
          {tab === 'keys' ? <KeysTab /> : <PresetsTab />}
        </div>
      </div>
    </div>
  )
}


// ─── Tab 1: API Keys ────────────────────────────────────────────────

function KeysTab() {
  const [keys, setKeys] = useState<ApiKeys>({
    api_key_gemini: '',
    api_key_openai: '',
    api_key_deepseek: '',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [show, setShow] = useState({ gemini: false, openai: false, deepseek: false })

  useEffect(() => {
    settingsApi.getApiKeys().then(k => {
      setKeys(k); setLoading(false)
    }).catch(() => setLoading(false))
  }, [])

  async function save() {
    setSaving(true)
    try {
      await settingsApi.putApiKeys(keys)
      alert('Đã lưu API keys')
    } catch (e: any) {
      alert(`Lỗi: ${e?.response?.data?.detail || e.message}`)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="text-zinc-500">Đang tải...</div>

  return (
    <div className="space-y-4">
      <p className="text-sm text-zinc-600">
        Các key này áp dụng cho tất cả project. Pipeline tự pick đúng key theo model
        bạn chọn ở mỗi stage.
      </p>

      <KeyInput
        label="Gemini API Key"
        value={keys.api_key_gemini}
        onChange={v => setKeys({ ...keys, api_key_gemini: v })}
        show={show.gemini}
        onToggleShow={() => setShow(s => ({ ...s, gemini: !s.gemini }))}
        hint="Lấy từ ai.google.dev — dùng cho model gemini-*"
      />
      <KeyInput
        label="OpenAI API Key"
        value={keys.api_key_openai}
        onChange={v => setKeys({ ...keys, api_key_openai: v })}
        show={show.openai}
        onToggleShow={() => setShow(s => ({ ...s, openai: !s.openai }))}
        hint="Lấy từ platform.openai.com — dùng cho model gpt-*, o1-*, o3-*"
      />
      <KeyInput
        label="DeepSeek API Key"
        value={keys.api_key_deepseek}
        onChange={v => setKeys({ ...keys, api_key_deepseek: v })}
        show={show.deepseek}
        onToggleShow={() => setShow(s => ({ ...s, deepseek: !s.deepseek }))}
        hint="Lấy từ platform.deepseek.com — dùng cho model deepseek-*"
      />

      <div className="pt-2">
        <button onClick={save} disabled={saving}
          className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50">
          {saving ? 'Đang lưu...' : '💾 Lưu API keys'}
        </button>
      </div>
    </div>
  )
}

function KeyInput({ label, value, onChange, show, onToggleShow, hint }: {
  label: string; value: string; onChange: (v: string) => void;
  show: boolean; onToggleShow: () => void; hint: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1">{label}</label>
      <div className="flex gap-2">
        <input
          type={show ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value)}
          placeholder="Để trống nếu chưa dùng"
          className="flex-1 border rounded px-3 py-2 text-sm font-mono"
        />
        <button onClick={onToggleShow}
          className="px-3 border rounded text-sm hover:bg-zinc-50"
          title="Hiện/ẩn key">
          {show ? '🙈' : '👁'}
        </button>
      </div>
      <p className="text-xs text-zinc-500 mt-1">{hint}</p>
    </div>
  )
}


// ─── Tab 2: Model Presets ───────────────────────────────────────────

const STAGE_LABELS: Record<string, string> = {
  model_stage0: 'Stage 0 (Chuẩn hóa)',
  model_stage1: 'Stage 1 (Bible)',
  model_stage2: 'Stage 2 (Chunks/Scenes)',
  model_stage3: 'Stage 3 (Speaker)',
  model_stage4: 'Stage 4 (Dịch)',
  model_stage5: 'Stage 5 (Retry)',
  model_retranslate: 'Retranslate (editor)',
}

// Gợi ý nhanh — user vẫn nhập tay được
const COMMON_MODELS = [
  'gemini-2.5-flash',
  'gemini-2.5-pro',
  'gpt-4o',
  'gpt-4o-mini',
  'gpt-5',
  'o3-mini',
  'deepseek-chat',
  'deepseek-reasoner',
  'deepseek-v3',
]

function PresetsTab() {
  const [list, setList] = useState<ModelPreset[]>([])
  const [editing, setEditing] = useState<ModelPreset | null>(null)
  const [loading, setLoading] = useState(true)

  async function reload() {
    setLoading(true)
    try {
      setList(await settingsApi.listPresets())
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { reload() }, [])

  function newPreset() {
    setEditing({
      id: 0, name: '', description: '',
      model_stage0: '', model_stage1: '', model_stage2: '',
      model_stage3: '', model_stage4: '', model_stage5: '',
      model_retranslate: '', is_default: false,
    })
  }

  async function deletePreset(p: ModelPreset) {
    if (!confirm(`Xóa preset "${p.name}"?`)) return
    try {
      await settingsApi.deletePreset(p.id)
      await reload()
    } catch (e: any) {
      alert(`Lỗi: ${e?.response?.data?.detail || e.message}`)
    }
  }

  async function setDefault(p: ModelPreset) {
    try {
      await settingsApi.setDefaultPreset(p.id)
      await reload()
    } catch (e: any) {
      alert(`Lỗi: ${e?.response?.data?.detail || e.message}`)
    }
  }

  if (loading) return <div className="text-zinc-500">Đang tải...</div>

  if (editing) {
    return <PresetEditor
      preset={editing}
      onCancel={() => setEditing(null)}
      onSaved={() => { setEditing(null); reload() }}
    />
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-zinc-600">
          Mỗi preset = 1 combo model cho từng stage. Khi chạy pipeline, chọn preset
          → tự fill 6 ô model.
        </p>
        <button onClick={newPreset}
          className="bg-blue-600 text-white px-3 py-1.5 rounded text-sm hover:bg-blue-700">
          + Tạo preset
        </button>
      </div>

      {list.length === 0 ? (
        <div className="text-zinc-400 text-sm p-8 text-center border border-dashed rounded">
          Chưa có preset nào. Tạo preset đầu tiên để lưu cấu hình model.
        </div>
      ) : (
        <div className="space-y-2">
          {list.map(p => (
            <div key={p.id} className="border rounded p-3 hover:bg-zinc-50">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="font-medium flex items-center gap-2">
                    {p.name}
                    {p.is_default && (
                      <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">
                        Default
                      </span>
                    )}
                  </div>
                  {p.description && (
                    <div className="text-xs text-zinc-500 mt-1">{p.description}</div>
                  )}
                  <div className="text-xs text-zinc-600 mt-2 grid grid-cols-2 gap-x-4 gap-y-1">
                    {Object.entries(STAGE_LABELS).map(([k, label]) => {
                      const v = (p as any)[k]
                      if (!v) return null
                      return (
                        <div key={k}>
                          <span className="text-zinc-400">{label}:</span>{' '}
                          <code className="text-zinc-700">{v}</code>
                        </div>
                      )
                    })}
                  </div>
                </div>
                <div className="flex flex-col gap-1 ml-3">
                  {!p.is_default && (
                    <button onClick={() => setDefault(p)}
                      className="text-xs text-blue-600 hover:underline" title="Đặt làm default">
                      Đặt default
                    </button>
                  )}
                  <button onClick={() => setEditing(p)}
                    className="text-xs text-zinc-600 hover:underline">
                    Sửa
                  </button>
                  <button onClick={() => deletePreset(p)}
                    className="text-xs text-red-600 hover:underline">
                    Xóa
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function PresetEditor({ preset, onCancel, onSaved }: {
  preset: ModelPreset; onCancel: () => void; onSaved: () => void;
}) {
  const [p, setP] = useState<ModelPreset>(preset)
  const [saving, setSaving] = useState(false)

  function setField(key: string, value: string) {
    setP({ ...p, [key]: value })
  }

  async function save() {
    if (!p.name.trim()) { alert('Tên preset không được rỗng'); return }
    setSaving(true)
    try {
      const payload = {
        name: p.name.trim(),
        description: p.description || '',
        model_stage0: p.model_stage0 || '',
        model_stage1: p.model_stage1 || '',
        model_stage2: p.model_stage2 || '',
        model_stage3: p.model_stage3 || '',
        model_stage4: p.model_stage4 || '',
        model_stage5: p.model_stage5 || '',
        model_retranslate: p.model_retranslate || '',
      }
      if (p.id) {
        await settingsApi.updatePreset(p.id, payload)
      } else {
        await settingsApi.createPreset(payload)
      }
      onSaved()
    } catch (e: any) {
      alert(`Lỗi: ${e?.response?.data?.detail || e.message}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <button onClick={onCancel} className="text-sm text-zinc-600 hover:underline">
        ← Quay lại danh sách
      </button>

      <div>
        <label className="block text-sm font-medium mb-1">Tên preset *</label>
        <input value={p.name} onChange={e => setField('name', e.target.value)}
          placeholder="VD: Dịch tối ưu, Dịch nhanh, Tiết kiệm..."
          className="w-full border rounded px-3 py-2 text-sm" />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">Mô tả</label>
        <input value={p.description || ''} onChange={e => setField('description', e.target.value)}
          placeholder="Mô tả ngắn để dễ nhớ"
          className="w-full border rounded px-3 py-2 text-sm" />
      </div>

      <div className="border-t pt-3">
        <p className="text-sm font-medium mb-2">Model cho từng stage</p>
        <p className="text-xs text-zinc-500 mb-3">
          Để trống = dùng model mặc định (heavy/medium/light theo tier).
          Có thể mix Gemini + OpenAI + DeepSeek tự do.
        </p>
        <div className="grid grid-cols-2 gap-3">
          {Object.entries(STAGE_LABELS).map(([key, label]) => (
            <div key={key}>
              <label className="block text-xs text-zinc-600 mb-0.5">{label}</label>
              <input
                value={(p as any)[key] || ''}
                onChange={e => setField(key, e.target.value)}
                placeholder="(để trống = default)"
                list="common-models"
                className="w-full border rounded px-2 py-1 text-sm font-mono"
              />
            </div>
          ))}
        </div>
        <datalist id="common-models">
          {COMMON_MODELS.map(m => <option key={m} value={m} />)}
        </datalist>
      </div>

      <div className="flex gap-2 pt-3 border-t">
        <button onClick={save} disabled={saving}
          className="bg-blue-600 text-white px-4 py-2 rounded text-sm hover:bg-blue-700 disabled:opacity-50">
          {saving ? 'Đang lưu...' : '💾 Lưu preset'}
        </button>
        <button onClick={onCancel}
          className="border px-4 py-2 rounded text-sm hover:bg-zinc-50">
          Hủy
        </button>
      </div>
    </div>
  )
}
