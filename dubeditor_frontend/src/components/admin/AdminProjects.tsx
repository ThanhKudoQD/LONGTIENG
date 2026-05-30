/**
 * AdminProjects — list tất cả project với filter user/ngày/orphan.
 */
import React, { useState, useEffect } from 'react'
import { adminApi, AdminProject, UserWithCount } from '../auth/authApi'

export default function AdminProjects() {
  const [projects, setProjects] = useState<AdminProject[]>([])
  const [users, setUsers] = useState<UserWithCount[]>([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  // Filters
  const [ownerFilter, setOwnerFilter] = useState<string>('')   // '' | 'orphan' | userId string
  const [daysFilter, setDaysFilter] = useState<string>('')     // '' | '7' | '30' | '90'
  const [searchQ, setSearchQ] = useState('')

  const load = async () => {
    setLoading(true); setErr(null)
    try {
      const filters: any = {}
      if (ownerFilter === 'orphan') filters.orphan_only = true
      else if (ownerFilter) filters.owner_id = parseInt(ownerFilter)
      if (daysFilter) filters.days = parseInt(daysFilter)
      if (searchQ.trim()) filters.search = searchQ.trim()
      const list = await adminApi.listProjects(filters)
      setProjects(list)
    } catch (e: any) {
      setErr(e?.response?.data?.detail || 'Tải thất bại')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ownerFilter, daysFilter])

  // Search debounced
  useEffect(() => {
    const id = setTimeout(() => load(), 300)
    return () => clearTimeout(id)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchQ])

  // Load users để filter
  useEffect(() => {
    adminApi.listUsers().then(setUsers).catch(() => {})
  }, [])

  const handleTransfer = async (p: AdminProject) => {
    const userList = users.filter(u => u.is_active).map(u => `${u.id}: ${u.username} ${u.display_name ? '('+u.display_name+')' : ''}`).join('\n')
    const inp = prompt(`Chuyển project "${p.name}" cho user ID nào?\n(để trống = không có owner)\n\n${userList}`,
                        p.owner_id ? String(p.owner_id) : '')
    if (inp === null) return
    const newOwner = inp.trim() === '' ? null : parseInt(inp)
    if (inp.trim() !== '' && (isNaN(newOwner!) || !users.find(u => u.id === newOwner))) {
      alert('User ID không hợp lệ')
      return
    }
    try {
      await adminApi.transferProject(p.id, newOwner)
      load()
    } catch (e: any) {
      alert('Chuyển thất bại: ' + (e?.response?.data?.detail || ''))
    }
  }

  return (
    <div className="max-w-6xl mx-auto">
      <h2 className="text-[18px] font-semibold mb-4">Dự án ({projects.length})</h2>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 mb-4 bg-white dark:bg-zinc-900 border border-zinc-200 dark:border-zinc-800 rounded-lg p-3">
        <div>
          <label className="block text-[10px] text-zinc-500 uppercase mb-1">Owner</label>
          <select value={ownerFilter} onChange={e => setOwnerFilter(e.target.value)}
            className="input text-[12px] min-w-[180px]">
            <option value="">— Tất cả —</option>
            <option value="orphan">🚨 Mồ côi (không owner)</option>
            <optgroup label="Theo user">
              {users.map(u => (
                <option key={u.id} value={u.id}>{u.username} ({u.project_count})</option>
              ))}
            </optgroup>
          </select>
        </div>
        <div>
          <label className="block text-[10px] text-zinc-500 uppercase mb-1">Ngày tạo</label>
          <select value={daysFilter} onChange={e => setDaysFilter(e.target.value)}
            className="input text-[12px]">
            <option value="">— Tất cả —</option>
            <option value="1">Hôm nay</option>
            <option value="7">7 ngày qua</option>
            <option value="30">30 ngày qua</option>
            <option value="90">90 ngày qua</option>
          </select>
        </div>
        <div className="flex-1 min-w-[200px]">
          <label className="block text-[10px] text-zinc-500 uppercase mb-1">Tìm theo tên</label>
          <input type="text" value={searchQ}
            onChange={e => setSearchQ(e.target.value)}
            placeholder="Nhập từ khóa..."
            className="input w-full text-[12px]" />
        </div>
        <div className="self-end">
          <button onClick={load} className="btn text-[12px]">🔄</button>
        </div>
      </div>

      {err && <div className="text-[12px] text-red-700 bg-red-50 rounded p-2 mb-3">{err}</div>}
      {loading && <div className="text-[13px] text-zinc-500">Đang tải...</div>}

      {!loading && projects.length === 0 && (
        <div className="text-center py-10 text-zinc-500 text-[13px]">Không có project nào</div>
      )}

      {!loading && projects.length > 0 && (
        <div className="bg-white dark:bg-zinc-900 rounded-lg border border-zinc-200 dark:border-zinc-800 overflow-hidden">
          <table className="w-full text-[13px]">
            <thead className="bg-zinc-50 dark:bg-zinc-800 text-[11px] uppercase tracking-wider text-zinc-500">
              <tr>
                <th className="px-3 py-2 text-left">#</th>
                <th className="px-3 py-2 text-left">Tên</th>
                <th className="px-3 py-2 text-left">Owner</th>
                <th className="px-3 py-2 text-center">Phụ đề</th>
                <th className="px-3 py-2 text-left">Tạo lúc</th>
                <th className="px-3 py-2 text-right">Thao tác</th>
              </tr>
            </thead>
            <tbody>
              {projects.map(p => (
                <tr key={p.id} className="border-t border-zinc-100 dark:border-zinc-800">
                  <td className="px-3 py-2 text-zinc-500 font-mono">#{p.id}</td>
                  <td className="px-3 py-2 font-medium">{p.name || `Project #${p.id}`}</td>
                  <td className="px-3 py-2">
                    {p.owner_username ? (
                      <span>
                        {p.owner_display_name || p.owner_username}
                        <span className="text-[11px] text-zinc-500 ml-1">@{p.owner_username}</span>
                      </span>
                    ) : (
                      <span className="text-red-600 text-[11px] font-medium">🚨 Mồ côi</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-center text-zinc-600 font-mono">{p.subtitle_count}</td>
                  <td className="px-3 py-2 text-[11px] text-zinc-500">
                    {p.created_at ? new Date(p.created_at).toLocaleString() : '—'}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => handleTransfer(p)}
                      className="text-[11px] px-2 py-1 hover:bg-zinc-100 dark:hover:bg-zinc-800 rounded">
                      🔄 Chuyển owner
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
