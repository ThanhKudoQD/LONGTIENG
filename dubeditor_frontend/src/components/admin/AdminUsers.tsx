/**
 * AdminUsers — CRUD users page.
 */
import React, { useState, useEffect } from 'react'
import { adminApi, User, UserWithCount } from '../auth/authApi'

interface Props {
  currentUser: User
}

export default function AdminUsers({ currentUser }: Props) {
  const [users, setUsers] = useState<UserWithCount[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [editingUser, setEditingUser] = useState<UserWithCount | null>(null)
  const [resetPwdUser, setResetPwdUser] = useState<UserWithCount | null>(null)

  const load = async () => {
    setLoading(true); setErr(null)
    try {
      const list = await adminApi.listUsers()
      setUsers(list)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Tải danh sách thất bại')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const handleDelete = async (u: UserWithCount) => {
    if (u.id === currentUser.id) {
      alert('Không thể xóa chính mình')
      return
    }
    const projectWarning = u.project_count > 0
      ? `\n\nUser này có ${u.project_count} project. Project sẽ thành "mồ côi" (admin có thể xử lý ở tab Dự án).`
      : ''
    if (!confirm(`Xóa user "${u.username}"?${projectWarning}`)) return
    try {
      const r = await adminApi.deleteUser(u.id)
      if (r.orphaned_projects > 0) alert(r.message)
      load()
    } catch (e: any) {
      alert('Xóa thất bại: ' + (e?.response?.data?.detail || ''))
    }
  }

  const handleToggleAdmin = async (u: UserWithCount) => {
    if (u.id === currentUser.id) {
      alert('Không thể đổi quyền admin của chính mình')
      return
    }
    if (!confirm(`Đổi quyền admin cho user "${u.username}"?`)) return
    try {
      await adminApi.updateUser(u.id, { is_admin: !u.is_admin })
      load()
    } catch (e: any) {
      alert('Thất bại: ' + (e?.response?.data?.detail || ''))
    }
  }

  const handleToggleActive = async (u: UserWithCount) => {
    if (u.id === currentUser.id) {
      alert('Không thể deactivate chính mình')
      return
    }
    const action = u.is_active ? 'KHÓA' : 'mở khóa'
    if (!confirm(`${action} tài khoản "${u.username}"?`)) return
    try {
      await adminApi.updateUser(u.id, { is_active: !u.is_active })
      load()
    } catch (e: any) {
      alert('Thất bại: ' + (e?.response?.data?.detail || ''))
    }
  }

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-[18px] font-semibold">Người dùng ({users.length})</h2>
        <button onClick={() => setShowCreate(true)} className="btn btn-primary text-[13px]">
          + Thêm người dùng
        </button>
      </div>

      {err && <div className="text-[12px] text-red-700 bg-red-50 rounded p-2 mb-3">{err}</div>}
      {loading && <div className="text-[13px] text-zinc-500">Đang tải...</div>}

      {!loading && (
        <div className="bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden">
          <table className="w-full text-[13px]">
            <thead className="bg-zinc-50 dark:bg-zinc-800 text-[11px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="px-3 py-2 text-left">#</th>
                <th className="px-3 py-2 text-left">Username</th>
                <th className="px-3 py-2 text-left">Tên hiển thị</th>
                <th className="px-3 py-2 text-center">Quyền</th>
                <th className="px-3 py-2 text-center">Trạng thái</th>
                <th className="px-3 py-2 text-center">Project</th>
                <th className="px-3 py-2 text-left">Lần login cuối</th>
                <th className="px-3 py-2 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.id} className="border-t border-zinc-100 dark:border-zinc-800">
                  <td className="px-3 py-2 text-zinc-500">{u.id}</td>
                  <td className="px-3 py-2 font-medium">
                    {u.username}
                    {u.id === currentUser.id && <span className="ml-1 text-[10px] text-blue-600">(bạn)</span>}
                  </td>
                  <td className="px-3 py-2">{u.display_name || '—'}</td>
                  <td className="px-3 py-2 text-center">
                    <button onClick={() => handleToggleAdmin(u)}
                      className={`text-[11px] px-2 py-0.5 rounded ${
                        u.is_admin
                          ? 'bg-amber-100 text-amber-700 dark:bg-amber-900/40'
                          : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800'
                      }`}>
                      {u.is_admin ? '👑 Admin' : 'User'}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-center">
                    <button onClick={() => handleToggleActive(u)}
                      className={`text-[11px] px-2 py-0.5 rounded ${
                        u.is_active
                          ? 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40'
                          : 'bg-red-100 text-red-700 dark:bg-red-900/40'
                      }`}>
                      {u.is_active ? '✓ Hoạt động' : '🔒 Đã khóa'}
                    </button>
                  </td>
                  <td className="px-3 py-2 text-center font-mono text-zinc-600">{u.project_count}</td>
                  <td className="px-3 py-2 text-[11px] text-zinc-500">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : 'Chưa từng'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <div className="flex gap-1 justify-end">
                      <button onClick={() => setEditingUser(u)}
                        className="text-[11px] px-2 py-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded" title="Sửa">✏️</button>
                      <button onClick={() => setResetPwdUser(u)}
                        className="text-[11px] px-2 py-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded" title="Reset password">🔑</button>
                      {u.id !== currentUser.id && (
                        <button onClick={() => handleDelete(u)}
                          className="text-[11px] px-2 py-1 hover:bg-red-50 dark:hover:bg-red-950 text-red-600 rounded" title="Xóa">🗑</button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showCreate && (
        <CreateUserDialog
          onClose={() => setShowCreate(false)}
          onCreated={() => { setShowCreate(false); load() }}
        />
      )}

      {editingUser && (
        <EditUserDialog
          user={editingUser}
          onClose={() => setEditingUser(null)}
          onSaved={() => { setEditingUser(null); load() }}
        />
      )}

      {resetPwdUser && (
        <ResetPasswordDialog
          user={resetPwdUser}
          onClose={() => setResetPwdUser(null)}
          onDone={() => setResetPwdUser(null)}
        />
      )}
    </div>
  )
}


// ─── Dialogs ────────────────────────────────────────────────────────────────

function CreateUserDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [username, setUsername] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [password, setPassword] = useState('')
  const [isAdmin, setIsAdmin] = useState(false)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) { setErr('Điền đủ thông tin'); return }
    if (password.length < 4) { setErr('Password tối thiểu 4 ký tự'); return }
    setLoading(true); setErr(null)
    try {
      await adminApi.createUser({
        username: username.trim(),
        password,
        display_name: displayName.trim() || undefined,
        is_admin: isAdmin,
      })
      onCreated()
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Tạo thất bại')
    } finally {
      setLoading(false)
    }
  }

  return (
    <DialogShell title="+ Thêm người dùng" onClose={onClose}>
      <form onSubmit={submit} className="p-5 space-y-3">
        <div>
          <label className="block text-[12px] font-medium mb-1">Username</label>
          <input type="text" autoFocus value={username}
            onChange={e => setUsername(e.target.value)} disabled={loading}
            placeholder="vd: user1" className="input w-full text-[13px]" />
        </div>
        <div>
          <label className="block text-[12px] font-medium mb-1">Tên hiển thị (tùy chọn)</label>
          <input type="text" value={displayName}
            onChange={e => setDisplayName(e.target.value)} disabled={loading}
            placeholder="vd: Nguyễn Văn A" className="input w-full text-[13px]" />
        </div>
        <div>
          <label className="block text-[12px] font-medium mb-1">Mật khẩu</label>
          <input type="password" value={password}
            onChange={e => setPassword(e.target.value)} disabled={loading}
            className="input w-full text-[13px]" />
        </div>
        <label className="flex items-center gap-2 text-[13px] cursor-pointer">
          <input type="checkbox" checked={isAdmin} onChange={e => setIsAdmin(e.target.checked)}
            className="w-4 h-4" disabled={loading} />
          👑 Quyền admin
        </label>
        {err && <div className="text-[12px] text-red-700 bg-red-50 rounded p-2">{err}</div>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} disabled={loading} className="btn text-[12px]">Hủy</button>
          <button type="submit" disabled={loading} className="btn btn-primary text-[12px]">
            {loading ? '⏳ ...' : 'Tạo'}
          </button>
        </div>
      </form>
    </DialogShell>
  )
}


function EditUserDialog({ user, onClose, onSaved }: { user: UserWithCount; onClose: () => void; onSaved: () => void }) {
  const [displayName, setDisplayName] = useState(user.display_name || '')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true); setErr(null)
    try {
      await adminApi.updateUser(user.id, { display_name: displayName.trim() })
      onSaved()
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Lưu thất bại')
    } finally {
      setLoading(false)
    }
  }

  return (
    <DialogShell title={`Sửa ${user.username}`} onClose={onClose}>
      <form onSubmit={submit} className="p-5 space-y-3">
        <div>
          <label className="block text-[12px] font-medium mb-1">Tên hiển thị</label>
          <input type="text" autoFocus value={displayName}
            onChange={e => setDisplayName(e.target.value)} disabled={loading}
            className="input w-full text-[13px]" />
        </div>
        {err && <div className="text-[12px] text-red-700 bg-red-50 rounded p-2">{err}</div>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} disabled={loading} className="btn text-[12px]">Hủy</button>
          <button type="submit" disabled={loading} className="btn btn-primary text-[12px]">Lưu</button>
        </div>
      </form>
    </DialogShell>
  )
}


function ResetPasswordDialog({ user, onClose, onDone }: { user: UserWithCount; onClose: () => void; onDone: () => void }) {
  const [pwd, setPwd] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (pwd.length < 4) { setErr('Tối thiểu 4 ký tự'); return }
    if (pwd !== confirm) { setErr('Không khớp'); return }
    setLoading(true); setErr(null)
    try {
      await adminApi.resetPassword(user.id, pwd)
      alert(`Đã đặt lại mật khẩu cho user "${user.username}".`)
      onDone()
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Lỗi')
    } finally {
      setLoading(false)
    }
  }

  return (
    <DialogShell title={`Reset mật khẩu - ${user.username}`} onClose={onClose}>
      <form onSubmit={submit} className="p-5 space-y-3">
        <div className="text-[12px] text-zinc-500 bg-amber-50 dark:bg-amber-950/30 rounded p-2 border border-amber-200 dark:border-amber-900">
          ⚠️ Sau khi reset, tất cả session của user này sẽ bị đăng xuất.
        </div>
        <div>
          <label className="block text-[12px] font-medium mb-1">Mật khẩu mới</label>
          <input type="password" autoFocus value={pwd}
            onChange={e => setPwd(e.target.value)} disabled={loading}
            className="input w-full text-[13px]" />
        </div>
        <div>
          <label className="block text-[12px] font-medium mb-1">Xác nhận</label>
          <input type="password" value={confirm}
            onChange={e => setConfirm(e.target.value)} disabled={loading}
            className="input w-full text-[13px]" />
        </div>
        {err && <div className="text-[12px] text-red-700 bg-red-50 rounded p-2">{err}</div>}
        <div className="flex justify-end gap-2 pt-1">
          <button type="button" onClick={onClose} disabled={loading} className="btn text-[12px]">Hủy</button>
          <button type="submit" disabled={loading} className="btn btn-primary text-[12px]">Reset</button>
        </div>
      </form>
    </DialogShell>
  )
}


function DialogShell({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[100]" onClick={onClose}>
      <div className="bg-white dark:bg-zinc-900 rounded-lg max-w-sm w-full mx-4 shadow-2xl"
        onClick={e => e.stopPropagation()}>
        <div className="px-5 py-3 border-b border-zinc-200 dark:border-zinc-800 flex items-center justify-between">
          <h2 className="text-[14px] font-semibold">{title}</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-900 text-[16px] w-6 h-6">✕</button>
        </div>
        {children}
      </div>
    </div>
  )
}
