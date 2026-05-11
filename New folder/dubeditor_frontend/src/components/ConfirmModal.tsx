import React from 'react'

interface Props {
  open: boolean
  title: string
  message: string
  warnings?: string[]      // Danh sách warning hiện dạng list ⚠
  confirmText?: string
  cancelText?: string
  variant?: 'default' | 'danger' | 'warning'
  onConfirm: () => void
  onCancel: () => void
}

/**
 * Modal xác nhận đẹp thay cho window.confirm().
 * Hỗ trợ list cảnh báo nhiều dòng.
 */
export default function ConfirmModal({
  open, title, message, warnings = [],
  confirmText = 'Tiếp tục', cancelText = 'Hủy',
  variant = 'default',
  onConfirm, onCancel,
}: Props) {
  if (!open) return null

  const variantStyles = {
    default: { iconBg: 'bg-blue-100 dark:bg-blue-950', iconColor: 'text-blue-600', btn: 'bg-blue-600 hover:bg-blue-700', icon: 'ⓘ' },
    warning: { iconBg: 'bg-amber-100 dark:bg-amber-950', iconColor: 'text-amber-600', btn: 'bg-amber-600 hover:bg-amber-700', icon: '⚠' },
    danger:  { iconBg: 'bg-red-100 dark:bg-red-950', iconColor: 'text-red-600', btn: 'bg-red-600 hover:bg-red-700', icon: '✕' },
  }
  const v = variantStyles[variant]

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50" onClick={onCancel}>
      <div className="bg-white dark:bg-zinc-900 rounded-xl shadow-2xl max-w-md w-full mx-4 overflow-hidden"
        onClick={e => e.stopPropagation()}>

        {/* Header */}
        <div className="px-5 py-4 flex items-start gap-3">
          <div className={`w-10 h-10 rounded-full ${v.iconBg} ${v.iconColor} flex items-center justify-center text-xl flex-shrink-0`}>
            {v.icon}
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-bold text-zinc-900 dark:text-zinc-100 mb-1">{title}</h3>
            <p className="text-[13px] text-zinc-600 dark:text-zinc-400 whitespace-pre-line">{message}</p>
          </div>
        </div>

        {/* Warnings list */}
        {warnings.length > 0 && (
          <div className="mx-5 mb-4 bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-800 rounded-lg p-3">
            <div className="text-[11px] font-bold text-amber-700 dark:text-amber-400 uppercase tracking-wider mb-1.5">⚠ Lưu ý</div>
            <ul className="space-y-1">
              {warnings.map((w, i) => (
                <li key={i} className="text-[12px] text-amber-700 dark:text-amber-400 flex items-start gap-1.5">
                  <span className="text-[10px] mt-0.5">▪</span>
                  <span>{w}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Footer */}
        <div className="px-5 py-3 bg-zinc-50 dark:bg-zinc-800/40 border-t border-zinc-200 dark:border-zinc-700 flex items-center justify-end gap-2">
          <button onClick={onCancel}
            className="px-4 py-1.5 text-[13px] rounded-lg border border-zinc-300 dark:border-zinc-700 hover:bg-zinc-100 dark:hover:bg-zinc-800 font-medium">
            {cancelText}
          </button>
          <button onClick={onConfirm}
            className={`px-4 py-1.5 text-[13px] rounded-lg ${v.btn} text-white font-semibold shadow-sm`}>
            {confirmText}
          </button>
        </div>
      </div>
    </div>
  )
}