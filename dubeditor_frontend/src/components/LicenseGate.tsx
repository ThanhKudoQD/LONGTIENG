import React, { useState, useEffect, useCallback } from 'react'
import api from '../api'

export interface LicenseStatus {
  valid: boolean
  reason?: 'no_license' | 'invalid' | 'expired' | 'machine_mismatch'
  machine_id: string
  expires_at?: number
  expires_in_days?: number
  note?: string
}

interface Props {
  status: LicenseStatus
  onActivated: () => void
}

/**
 * Màn hình kích hoạt license — hiện khi chưa có license hoặc hết hạn.
 * Khóa toàn bộ app, user phải nhập key hợp lệ mới vào được.
 */
export default function LicenseGate({ status, onActivated }: Props) {
  const [keyInput, setKeyInput] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  const copyMachineId = useCallback(() => {
    navigator.clipboard.writeText(status.machine_id)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [status.machine_id])

  const activate = async () => {
    if (!keyInput.trim()) {
      setError('Vui lòng dán license key')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await api.post('/license/activate', { key: keyInput.trim() })
      onActivated()
    } catch (e: any) {
      setError(e?.response?.data?.detail || 'Kích hoạt thất bại')
    } finally {
      setSubmitting(false)
    }
  }

  const reasonText: Record<string, string> = {
    no_license: 'Phần mềm chưa được kích hoạt. Vui lòng nhập license key.',
    invalid: 'License key không hợp lệ. Vui lòng nhập key đúng.',
    expired: 'License đã hết hạn. Vui lòng liên hệ admin để gia hạn.',
    machine_mismatch: 'License không khớp với máy này. Mỗi key chỉ dùng được 1 máy.',
  }

  return (
    <div className="fixed inset-0 z-[9999] flex items-center justify-center bg-gradient-to-br from-zinc-50 to-zinc-100 dark:from-zinc-950 dark:to-zinc-900">
      <div className="bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl p-8 max-w-lg w-full mx-4 border border-zinc-200 dark:border-zinc-800">

        {/* Header */}
        <div className="text-center mb-6">
          <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-500 to-indigo-600 flex items-center justify-center text-white text-3xl mx-auto mb-3">
            🔒
          </div>
          <h2 className="text-2xl font-bold text-zinc-900 dark:text-zinc-100">BAN2_DICH</h2>
          <p className="text-[13px] text-zinc-500 dark:text-zinc-400 mt-1">
            Phần mềm dịch C-drama + Lồng tiếng
          </p>
        </div>

        {/* Status message */}
        <div className={`rounded-lg p-3 mb-4 text-[13px] flex items-start gap-2
          ${status.reason === 'expired'
            ? 'bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 text-red-700 dark:text-red-400'
            : status.reason === 'no_license'
            ? 'bg-blue-50 dark:bg-blue-950/30 border border-blue-200 dark:border-blue-900 text-blue-700 dark:text-blue-400'
            : 'bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-900 text-amber-700 dark:text-amber-400'
          }`}>
          <span className="text-base flex-shrink-0">
            {status.reason === 'expired' ? '⏰' : status.reason === 'no_license' ? 'ℹ️' : '⚠️'}
          </span>
          <span>{reasonText[status.reason || 'no_license']}</span>
        </div>

        {/* Machine ID */}
        <div className="mb-4">
          <label className="block text-[11px] font-bold uppercase tracking-wider text-zinc-500 mb-1.5">
            Machine ID của bạn
          </label>
          <div className="bg-zinc-50 dark:bg-zinc-800 border border-zinc-200 dark:border-zinc-700 rounded-lg p-2.5 flex items-center gap-2">
            <code className="text-[12px] font-mono select-all flex-1 break-all text-zinc-700 dark:text-zinc-300">
              {status.machine_id}
            </code>
            <button onClick={copyMachineId}
              className="text-[11px] px-2 py-1 rounded border border-zinc-300 dark:border-zinc-700 hover:bg-white dark:hover:bg-zinc-900 font-medium flex-shrink-0">
              {copied ? '✓ Đã copy' : '📋 Copy'}
            </button>
          </div>
          <p className="text-[11px] text-zinc-500 mt-1.5">
            Gửi Machine ID này cho admin để nhận license key.
          </p>
        </div>

        {/* Key input */}
        <div className="mb-4">
          <label className="block text-[11px] font-bold uppercase tracking-wider text-zinc-500 mb-1.5">
            License Key
          </label>
          <textarea
            value={keyInput}
            onChange={e => setKeyInput(e.target.value)}
            placeholder="Dán license key vào đây..."
            rows={4}
            className="w-full border border-zinc-200 dark:border-zinc-700 rounded-lg p-3 text-[12px] font-mono bg-white dark:bg-zinc-800 focus:outline-none focus:border-blue-500 dark:focus:border-blue-400 resize-none"
            disabled={submitting}
          />
        </div>

        {error && (
          <div className="bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-900 text-red-700 dark:text-red-400 rounded-lg p-2.5 text-[12px] mb-3">
            ✕ {error}
          </div>
        )}

        <button onClick={activate} disabled={submitting || !keyInput.trim()}
          className="w-full py-3 rounded-lg bg-blue-600 hover:bg-blue-700 text-white font-semibold disabled:opacity-50 disabled:cursor-not-allowed transition-colors">
          {submitting ? '⏳ Đang kích hoạt...' : '✓ Kích hoạt'}
        </button>

        {/* Contact info */}
        <div className="mt-5 pt-4 border-t border-zinc-200 dark:border-zinc-800 text-center">
          <p className="text-[12px] text-zinc-500">
            Chưa có key? Liên hệ admin:
          </p>
          <p className="text-[13px] font-medium text-zinc-700 dark:text-zinc-300 mt-0.5">
            📱 Telegram: <span className="font-mono">@your_admin</span>
          </p>
        </div>
      </div>
    </div>
  )
}


// ─────────────────────────────────────────────────────────────
// LicenseChip — hiển thị trạng thái license ở header
// ─────────────────────────────────────────────────────────────

interface ChipProps {
  status: LicenseStatus
  onChange: () => void  // Callback khi user click "Đổi key" / "Deactivate"
}

/**
 * Hook đếm ngược real-time đến expire_at timestamp.
 * Update mỗi giây.
 */
function useCountdown(expiresAt: number | undefined) {
  const [now, setNow] = useState(() => Math.floor(Date.now() / 1000))

  useEffect(() => {
    const id = setInterval(() => {
      setNow(Math.floor(Date.now() / 1000))
    }, 1000)
    return () => clearInterval(id)
  }, [])

  if (!expiresAt) return null
  const diff = expiresAt - now
  if (diff <= 0) return { expired: true, days: 0, hours: 0, minutes: 0, seconds: 0, total: 0 }

  const days = Math.floor(diff / 86400)
  const hours = Math.floor((diff % 86400) / 3600)
  const minutes = Math.floor((diff % 3600) / 60)
  const seconds = diff % 60

  return { expired: false, days, hours, minutes, seconds, total: diff }
}

export function LicenseChip({ status, onChange }: ChipProps) {
  const [showDetail, setShowDetail] = useState(false)
  const [deactivating, setDeactivating] = useState(false)

  const countdown = useCountdown(status.expires_at)

  if (!status.valid) return null

  const days = countdown?.days ?? 0
  const hours = countdown?.hours ?? 0
  const minutes = countdown?.minutes ?? 0
  const seconds = countdown?.seconds ?? 0

  const warning = days < 7
  const critical = days < 3 || (days === 0 && hours < 24)

  const expireDate = status.expires_at
    ? new Date(status.expires_at * 1000).toLocaleString('vi-VN', {
        day: '2-digit', month: '2-digit', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    : '—'

  // Label gọn cho chip (ưu tiên đơn vị lớn nhất còn ý nghĩa)
  let chipLabel: string
  if (days > 0) {
    chipLabel = `${days} ngày`
  } else if (hours > 0) {
    chipLabel = `${hours}h ${minutes}m`
  } else if (minutes > 0) {
    chipLabel = `${minutes}m ${seconds}s`
  } else {
    chipLabel = `${seconds}s`
  }

  const handleDeactivate = async () => {
    if (!confirm('Bỏ kích hoạt license? Bạn sẽ cần nhập key mới để dùng tiếp.')) return
    setDeactivating(true)
    try {
      await api.post('/license/deactivate')
      onChange()
    } catch (e) {
      console.error(e)
    } finally {
      setDeactivating(false)
    }
  }

  return (
    <>
      <button onClick={() => setShowDetail(true)}
        title={`License hết hạn ${expireDate}`}
        className={`flex-shrink-0 text-[11px] px-2 py-1 rounded-lg border font-medium flex items-center gap-1 tabular-nums
          ${critical
            ? 'border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400'
            : warning
            ? 'border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400'
            : 'border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400'
          }`}>
        <span>🔑</span>
        <span>{chipLabel}</span>
      </button>

      {showDetail && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50"
          onClick={() => setShowDetail(false)}>
          <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl p-5 max-w-sm w-full mx-4"
            onClick={e => e.stopPropagation()}>
            <h3 className="text-base font-bold mb-3">🔑 Thông tin License</h3>

            <div className="space-y-2 text-[13px]">
              <div className="flex justify-between">
                <span className="text-zinc-500">Trạng thái</span>
                <span className="font-semibold text-emerald-600">✓ Đang hoạt động</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Hết hạn</span>
                <span className="font-medium tabular-nums">{expireDate}</span>
              </div>

              {/* Countdown chi tiết — 4 box */}
              <div>
                <p className="text-zinc-500 mb-1.5">Còn lại</p>
                <div className="grid grid-cols-4 gap-1.5">
                  <CountdownBox value={days} label="Ngày" critical={critical} warning={warning} />
                  <CountdownBox value={hours} label="Giờ" critical={critical} warning={warning} />
                  <CountdownBox value={minutes} label="Phút" critical={critical} warning={warning} />
                  <CountdownBox value={seconds} label="Giây" critical={critical} warning={warning} />
                </div>
              </div>

              {status.note && (
                <div className="flex justify-between pt-1">
                  <span className="text-zinc-500">Ghi chú</span>
                  <span className="font-medium truncate ml-2">{status.note}</span>
                </div>
              )}
              <div className="pt-2 border-t border-zinc-200 dark:border-zinc-700">
                <p className="text-[11px] text-zinc-500 mb-1">Machine ID</p>
                <code className="text-[11px] font-mono break-all">{status.machine_id}</code>
              </div>
            </div>

            <div className="mt-4 flex gap-2">
              <button onClick={() => setShowDetail(false)}
                className="flex-1 py-1.5 rounded-lg border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-50 dark:hover:bg-zinc-800 text-[12px] font-medium">
                Đóng
              </button>
              <button onClick={handleDeactivate} disabled={deactivating}
                className="flex-1 py-1.5 rounded-lg border border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 hover:bg-red-100 text-red-700 dark:text-red-400 text-[12px] font-medium disabled:opacity-50">
                {deactivating ? '...' : 'Đổi key'}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// Box hiển thị 1 đơn vị countdown
function CountdownBox({ value, label, critical, warning }: {
  value: number; label: string; critical: boolean; warning: boolean
}) {
  const color = critical
    ? 'border-red-300 dark:border-red-800 bg-red-50 dark:bg-red-950/40 text-red-700 dark:text-red-400'
    : warning
    ? 'border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400'
    : 'border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400'

  return (
    <div className={`rounded-lg border p-1.5 text-center ${color}`}>
      <div className="text-[16px] font-bold tabular-nums leading-tight">
        {String(value).padStart(2, '0')}
      </div>
      <div className="text-[9px] uppercase tracking-wider opacity-70">{label}</div>
    </div>
  )
}
