import React from 'react'

interface Props {
  open: boolean
  title?: string
  message: string
  variant?: 'success' | 'error' | 'info' | 'warning'
  okText?: string
  onClose: () => void
}

/**
 * Dialog thông báo đẹp thay cho window.alert().
 * Chỉ có 1 nút OK để đóng.
 */
export default function InfoDialog({
  open, title, message, variant = 'info', okText = 'OK', onClose,
}: Props) {
  if (!open) return null

  const variantStyles = {
    info:    { iconBg: 'bg-blue-100 dark:bg-blue-950',   iconColor: 'text-blue-600',   btn: 'bg-blue-600 hover:bg-blue-700',   icon: 'ⓘ', defaultTitle: 'Thông báo' },
    success: { iconBg: 'bg-emerald-100 dark:bg-emerald-950', iconColor: 'text-emerald-600', btn: 'bg-emerald-600 hover:bg-emerald-700', icon: '✓', defaultTitle: 'Thành công' },
    warning: { iconBg: 'bg-amber-100 dark:bg-amber-950', iconColor: 'text-amber-600', btn: 'bg-amber-600 hover:bg-amber-700', icon: '⚠', defaultTitle: 'Cảnh báo' },
    error:   { iconBg: 'bg-red-100 dark:bg-red-950',     iconColor: 'text-red-600',     btn: 'bg-red-600 hover:bg-red-700',     icon: '✕', defaultTitle: 'Lỗi' },
  }
  const v = variantStyles[variant]
  const finalTitle = title || v.defaultTitle

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50" onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="px-5 py-4 flex items-start gap-3">
          <div className={`w-10 h-10 rounded-full ${v.iconBg} ${v.iconColor} flex items-center justify-center text-xl flex-shrink-0`}>
            {v.icon}
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 mb-1">{finalTitle}</h3>
            <p className="text-[13px] text-zinc-600 dark:text-zinc-400 whitespace-pre-line">{message}</p>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-3 bg-zinc-50 dark:bg-zinc-800/40 border-t border-zinc-200 dark:border-zinc-700 flex items-center justify-end">
          <button onClick={onClose}
            className={`px-5 py-1.5 text-[13px] rounded-lg ${v.btn} text-white font-semibold shadow-sm`}>
            {okText}
          </button>
        </div>
      </div>
    </div>
  )
}
