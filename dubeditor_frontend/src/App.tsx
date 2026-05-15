import React, { useState, useEffect, useCallback } from 'react'
import ProjectList from './components/ProjectList'
import Editor from './components/Editor'
import TranslatePage from './components/TranslatePage'
import LicenseGate, { LicenseStatus } from './components/LicenseGate'
import api from './api'

type View =
  | { page: 'list' }
  | { page: 'editor';    projectId: number }
  | { page: 'translate'; projectId: number }

export default function App() {
  const [view, setView] = useState<View>({ page: 'list' })

  // License state
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null)
  const [loading, setLoading] = useState(true)

  const checkLicense = useCallback(async () => {
    try {
      const r = await api.get('/license/status')
      setLicenseStatus(r.data)
    } catch (e) {
      // Nếu API license cũng fail → coi như no_license
      setLicenseStatus({ valid: false, reason: 'no_license', machine_id: 'unknown' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    checkLicense()
  }, [checkLicense])

  // Re-check license mỗi 1h (đề phòng hết hạn giữa session)
  useEffect(() => {
    const id = setInterval(checkLicense, 60 * 60 * 1000)
    return () => clearInterval(id)
  }, [checkLicense])

  // Đang loading lần đầu
  if (loading) {
    return (
      <div className="fixed inset-0 flex items-center justify-center bg-zinc-50 dark:bg-zinc-950">
        <div className="text-zinc-400 text-[14px]">⏳ Đang kiểm tra license...</div>
      </div>
    )
  }

  // License invalid → khóa toàn bộ app
  if (!licenseStatus || !licenseStatus.valid) {
    return (
      <LicenseGate
        status={licenseStatus!}
        onActivated={checkLicense}
      />
    )
  }

  // ─── App bình thường (đã có license valid) ───
  if (view.page === 'editor') {
    return (
      <Editor
        projectId={view.projectId}
        onBack={() => setView({ page: 'list' })}
        onTranslate={() => setView({ page: 'translate', projectId: view.projectId })}
      />
    )
  }

  if (view.page === 'translate') {
    return (
      <TranslatePage
        projectId={view.projectId}
        onBack={() => setView({ page: 'editor', projectId: view.projectId })}
      />
    )
  }

  return <ProjectList onOpen={id => setView({ page: 'editor', projectId: id })} />
}
