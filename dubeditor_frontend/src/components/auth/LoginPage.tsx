/**
 * LoginPage — form đăng nhập.
 */
import React, { useState } from 'react'
import { authApi, User } from './authApi'

interface Props {
  onLogin: (user: User) => void
}

export default function LoginPage({ onLogin }: Props) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) {
      setError('Vui lòng nhập đầy đủ thông tin')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const r = await authApi.login(username.trim(), password)
      onLogin(r.user)
    } catch (e: any) {
      setError(e?.response?.data?.detail || e?.message || 'Đăng nhập thất bại')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center bg-gradient-to-br from-zinc-100 to-zinc-200 dark:from-zinc-950 dark:to-zinc-900 p-4">
      <div className="bg-white dark:bg-zinc-900 rounded-2xl shadow-2xl w-full max-w-sm p-8">
        {/* Logo */}
        <div className="text-center mb-6">
          <div className="text-3xl mb-2">🎬</div>
          <h1 className="text-[20px] font-bold text-zinc-900 dark:text-zinc-100">Nano</h1>
          <div className="text-[12px] text-zinc-500 mt-1">Dubbing & Video Tool</div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-[12px] font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
              Tên đăng nhập
            </label>
            <input
              type="text" autoComplete="username" autoFocus
              value={username}
              onChange={e => setUsername(e.target.value)}
              disabled={loading}
              placeholder="admin"
              className="input w-full text-[14px]"
            />
          </div>
          <div>
            <label className="block text-[12px] font-medium text-zinc-700 dark:text-zinc-300 mb-1.5">
              Mật khẩu
            </label>
            <input
              type="password" autoComplete="current-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              disabled={loading}
              placeholder="••••••••"
              className="input w-full text-[14px]"
            />
          </div>

          {error && (
            <div className="text-[12px] text-red-700 bg-red-50 dark:bg-red-950/40 rounded p-2 border border-red-200 dark:border-red-900">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="btn btn-primary w-full text-[13px] py-2.5"
          >
            {loading ? '⏳ Đang đăng nhập...' : 'Đăng nhập'}
          </button>
        </form>

        <div className="text-center mt-5 text-[11px] text-zinc-500">
          Quên mật khẩu? Liên hệ admin
        </div>
      </div>
    </div>
  )
}
