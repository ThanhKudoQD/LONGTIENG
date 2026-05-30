import React, { useState, useEffect, useCallback } from 'react'
import ProjectList from './components/ProjectList'
import Editor from './components/Editor'
import TranslatePageSimple from './components/translate/simple/TranslatePageSimple'
import ExportPage from './components/export/ExportPage'
import LicenseGate, { LicenseStatus } from './components/LicenseGate'
import LoginPage from './components/auth/LoginPage'
import { authApi, User } from './components/auth/authApi'
import AdminPage from './components/admin/AdminPage'
import api from './api'

type View =
  | { page: 'list' }
  | { page: 'editor';    projectId: number }
  | { page: 'translate'; projectId: number }
  | { page: 'export';    projectId: number }
  | { page: 'admin' }

export default function App() {
  const [view, setView] = useState<View>({ page: 'list' })

  // License state
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null)
  const [licLoading, setLicLoading] = useState(true)

  // Auth state
  const [user, setUser] = useState<User | null>(null)
  const [authChecking, setAuthChecking] = useState(true)

  // ─── License check ────────────────────────────────────────────────
  const checkLicense = useCallback(async () => {
    try {
      const r = await api.get('/license/status')
      setLicenseStatus(r.data)
    } catch (e) {
      setLicenseStatus({ valid: false, reason: 'no_license', machine_id: 'unknown' })
    } finally {
      setLicLoading(false)
    }
  }, [])

  useEffect(() => { checkLicense() }, [checkLicense])
  useEffect(() => {
    const id = setInterval(checkLicense, 60 * 60 * 1000)
    return () => clearInterval(id)
  }, [checkLicense])

  // ─── Auth check on mount ──────────────────────────────────────────
  const checkAuth = useCallback(async () => {
    try {
      const r = await authApi.me()
      setUser(r.user)
    } catch {
      setUser(null)
    } finally {
      setAuthChecking(false)
    }
  }, [])

  useEffect(() => { checkAuth() }, [checkAuth])

  // Axios interceptor: bắt 401 → log out user (sẽ redirect login)
  useEffect(() => {
    const id = api.interceptors.response.use(
      (r) => r,
      (err) => {
        if (err?.response?.status === 401) {
          setUser(null)
          setView({ page: 'list' })
        }
        return Promise.reject(err)
      }
    )
    return () => api.interceptors.response.eject(id)
  }, [])

  // ─── Render flow ──────────────────────────────────────────────────
  if (licLoading || authChecking) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <div className="text-zinc-400 text-[14px]">⏳ Đang khởi tạo...</div>
      </div>
    )
  }

  // License invalid → khóa toàn bộ app
  if (!licenseStatus || !licenseStatus.valid) {
    return <LicenseGate status={licenseStatus!} onActivated={checkLicense} />
  }

  // Chưa login → LoginPage
  if (!user) {
    return <LoginPage onLogin={(u) => { setUser(u); setView({ page: 'list' }) }} />
  }

  // ─── Logged in views ──────────────────────────────────────────────
  const handleLogout = () => {
    setUser(null)
    setView({ page: 'list' })
  }
  const handlePasswordChanged = () => {
    setUser(null)
    setView({ page: 'list' })
  }

  if (view.page === 'admin') {
    if (!user.is_admin) {
      // User thường lén vào admin → redirect list
      setView({ page: 'list' })
      return null
    }
    return <AdminPage currentUser={user} onBack={() => setView({ page: 'list' })} />
  }

  if (view.page === 'editor') {
    return (
      <Editor
        projectId={view.projectId}
        onBack={() => setView({ page: 'list' })}
        onTranslate={() => setView({ page: 'translate', projectId: view.projectId })}
        onExport={() => setView({ page: 'export', projectId: view.projectId })}
      />
    )
  }

  if (view.page === 'export') {
    return (
      <ExportPage
        projectId={view.projectId}
        onBack={() => setView({ page: 'editor', projectId: view.projectId })}
      />
    )
  }

  if (view.page === 'translate') {
    return (
      <TranslatePageSimple
        projectId={view.projectId}
        onBack={() => setView({ page: 'editor', projectId: view.projectId })}
      />
    )
  }

  return (
    <ProjectList
      onOpen={id => setView({ page: 'editor', projectId: id })}
      currentUser={user}
      onLogout={handleLogout}
      onOpenAdmin={user.is_admin ? () => setView({ page: 'admin' }) : undefined}
      onChangedPassword={handlePasswordChanged}
    />
  )
}
