/**
 * UserMenu — dropdown user info ở header (đổi pass, logout, link admin).
 */
import React, { useState, useRef, useEffect } from 'react'
import { authApi, User } from './authApi'

interface Props {
  user: User
  onLogout: () => void
  onOpenAdmin?: () => void
  onChangedPassword: () => void
}

export default function UserMenu({ user, onLogout, onOpenAdmin, onChangedPassword }: Props) {
  const [open, setOpen] = useState(false)
  const [showPassDialog, setShowPassDialog] = useState(false)
  const dropRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (dropRef.current && !dropRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [open])

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } catch {}
    onLogout()
  }

  return (
    <>
      <div className="relative" ref={dropRef}>
        <button
          onClick={() => setOpen(!open)}
          className="flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-zinc-100 dark:hover:bg-zinc-800 text-[13px]"
        >
          <span className="w-7 h-7 rounded-full bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 flex items-center justify-center font-semibold text-[12px]">
            {(user.display_name || user.username).charAt(0).toUpperCase()}
          </span>
          <span className="hidden sm:block">{user.display_name || user.username}</span>
          {user.is_admin && (
            <span className="text-[10px] px-1.5 py-0.5 rounded bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300 font-medium">
              ADMIN
            </span>
          )}
          <span className="text-zinc-400 text-[10px]">▾</span>
        </button>

        {open && (
          <div className="absolute right-0 top-full mt-1 w-56 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-md shadow-lg z-50 py-1 text-[13px]">
            <div className="px-3 py-2 border-b border-zinc-100 dark:border-zinc-800">
              <div className="font-medium truncate">{user.display_name || user.username}</div>
              <div className="text-[11px] text-zinc-500">@{user.username}</div>
            </div>

            {user.is_admin && onOpenAdmin && (
              <button onClick={() => { setOpen(false); onOpenAdmin() }}
                className="w-full text-left px-3 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800">
                ⚙ Quản trị
              </button>
            )}

            <button onClick={() => { setOpen(false); setShowPassDialog(true) }}
              className="w-full text-left px-3 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800">
              🔑 Đổi mật khẩu
            </button>

            <div className="border-t border-zinc-100 dark:border-zinc-800 my-1"></div>

            <button onClick={handleLogout}
              className="w-full text-left px-3 py-1.5 hover:bg-zinc-100 dark:hover:bg-zinc-800 text-red-600">
              ↪ Đăng xuất
            </button>
          </div>
        )}
      </div>

      {showPassDialog && (
        <ChangePasswordDialog
          onClose={() => setShowPassDialog(false)}
          onChanged={() => {
            setShowPassDialog(false)
            onChangedPassword()
          }}
        />
      )}
    </>
  )
}


function ChangePasswordDialog({ onClose, onChanged }: { onClose: () => void; onChanged: () => void }) {
  const [oldPwd, setOldPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!oldPwd || !newPwd) { setErr('Vui lòng điền đủ thông tin'); return }
    if (newPwd.length < 4) { setErr('Mật khẩu mới tối thiểu 4 ký tự'); return }
    if (newPwd !== confirmPwd) { setErr('Mật khẩu xác nhận không khớp'); return }
    setLoading(true); setErr(null)
    try {
      await authApi.changePassword(oldPwd, newPwd)
      alert('Đổi mật khẩu thành công. Vui lòng đăng nhập lại.')
      onChanged()
    } catch (e: any) {
      setErr(e?.response?.data?.detail || e?.message || 'Đổi thất bại')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[100]" onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-lg max-w-sm w-full mx-4 shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
          <h2 className="text-[14px] font-semibold">🔑 Đổi mật khẩu</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-900 text-[16px] w-6 h-6">✕</button>
        </div>
        <form onSubmit={handleSubmit} className="p-5 space-y-3">
          <div>
            <label className="block text-[12px] font-medium mb-1">Mật khẩu hiện tại</label>
            <input type="password" autoFocus value={oldPwd}
              onChange={e => setOldPwd(e.target.value)} disabled={loading}
              className="input w-full text-[13px]" />
          </div>
          <div>
            <label className="block text-[12px] font-medium mb-1">Mật khẩu mới</label>
            <input type="password" value={newPwd}
              onChange={e => setNewPwd(e.target.value)} disabled={loading}
              className="input w-full text-[13px]" />
          </div>
          <div>
            <label className="block text-[12px] font-medium mb-1">Xác nhận mật khẩu mới</label>
            <input type="password" value={confirmPwd}
              onChange={e => setConfirmPwd(e.target.value)} disabled={loading}
              className="input w-full text-[13px]" />
          </div>
          {err && <div className="text-[12px] text-red-700 bg-red-50 dark:bg-red-950/40 rounded p-2">{err}</div>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} disabled={loading} className="btn text-[12px]">Hủy</button>
            <button type="submit" disabled={loading} className="btn btn-primary text-[12px]">
              {loading ? '⏳ ...' : 'Đổi mật khẩu'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
