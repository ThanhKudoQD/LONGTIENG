/**
 * AdminPage — quản trị tổng hợp (CRUD users + filter projects).
 */
import React, { useState } from 'react'
import { User } from '../auth/authApi'
import AdminUsers from './AdminUsers'
import AdminProjects from './AdminProjects'

interface Props {
  currentUser: User
  onBack: () => void
}

type Tab = 'users' | 'projects'

export default function AdminPage({ currentUser, onBack }: Props) {
  const [tab, setTab] = useState<Tab>('users')

  return (
    <div className="fixed inset-0 flex flex-col bg-zinc-50 dark:bg-zinc-950 overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex-shrink-0">
        <button onClick={onBack} className="btn text-[13px]">← Quay lại</button>
        <div className="font-semibold text-[14px]">⚙ Quản trị</div>
        <span className="text-zinc-400">·</span>
        <span className="text-[12px] text-zinc-500">{currentUser.display_name || currentUser.username}</span>
      </header>

      {/* Tab nav */}
      <nav className="flex border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex-shrink-0">
        {([
          { key: 'users' as const, label: 'Người dùng', icon: '👥' },
          { key: 'projects' as const, label: 'Dự án', icon: '📂' },
        ]).map(t => {
          const isActive = t.key === tab
          return (
            <button key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-2 px-5 py-3 border-b-2 text-[13px] font-medium transition-colors ${
                isActive
                  ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                  : 'border-transparent text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100'
              }`}
            >
              <span>{t.icon}</span>
              {t.label}
            </button>
          )
        })}
      </nav>

      {/* Body */}
      <div className="flex-1 overflow-y-auto p-5">
        {tab === 'users' && <AdminUsers currentUser={currentUser} />}
        {tab === 'projects' && <AdminProjects />}
      </div>
    </div>
  )
}
