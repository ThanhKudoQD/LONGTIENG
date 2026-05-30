/**
 * StemSeparatorPanel — UI section tách audio từ video gốc thành 3 stem.
 * Render trong Tab Audio của Export.
 *
 * Workflow:
 *   1. Mount → load cache + info
 *   2. Có cache → hiện "✓ Đã có 3 stem, [bấm thêm vào BGM]"
 *   3. Chưa có → "[🎚 Tách audio]"
 *   4. Đang chạy → progress bar realtime qua WS
 *   5. Xong → tự gọi onAddToBgm() để thêm 3 track vào BGM list
 */
import React, { useState, useEffect, useRef, useCallback } from 'react'
import { stemApi, StemInfo, StemJobStatus } from './stemApi'

interface Props {
  projectId: number
  /** Callback khi user xác nhận thêm 3 stem vào BGM list */
  onAddStemsToBgm: (stems: { name: string; url: string; volume: number }[]) => void
}

const STEM_LABELS: Record<string, string> = {
  bass:   '🎸 Bass',
  drums:  '🥁 Drums',
  vocals: '🎤 Vocals',
}

const STEM_VOLUME = 0.3   // 30% mặc định

export default function StemSeparatorPanel({ projectId, onAddStemsToBgm }: Props) {
  const [info, setInfo] = useState<StemInfo | null>(null)
  const [status, setStatus] = useState<StemJobStatus>({
    status: 'idle', progress: 0, message: '', result: null, error: null,
  })
  const [cached, setCached] = useState<Record<string, string> | null>(null)
  const [loading, setLoading] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  // Initial load: info + cache + status
  useEffect(() => {
    let cancelled = false
    Promise.all([
      stemApi.info().catch(() => null),
      stemApi.cache(projectId).catch(() => null),
      stemApi.status(projectId).catch(() => null),
    ]).then(([infoData, cacheData, statusData]) => {
      if (cancelled) return
      setInfo(infoData)
      if (cacheData?.cached) setCached(cacheData.stems)
      if (statusData) setStatus(statusData)
    })
    return () => { cancelled = true }
  }, [projectId])

  // WS subscribe — share connection trong app (đã có ở ExportPage). Ở đây
  // tạo riêng cho đơn giản; có thể refactor sau.
  useEffect(() => {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(`${proto}//${window.location.host}/dub/ws/${projectId}`)
    wsRef.current = ws

    ws.onmessage = (e) => {
      try {
        const msg = JSON.parse(e.data)
        if (msg.type === 'stem_separation' && msg.project_id === projectId) {
          setStatus({
            status: msg.status || 'running',
            progress: msg.progress || 0,
            message: msg.message || '',
            result: msg.result || null,
            error: msg.error || null,
          })
          // Khi done → reload cache
          if (msg.status === 'done' && msg.result) {
            setCached(msg.result)
          }
        }
      } catch {}
    }
    return () => { try { ws.close() } catch {} }
  }, [projectId])

  const handleSeparate = async () => {
    setLoading(true)
    try {
      await stemApi.separate(projectId)
      setStatus({ status: 'pending', progress: 0, message: 'Đang khởi tạo...', result: null, error: null })
    } catch (e: any) {
      alert('Lỗi: ' + (e?.response?.data?.detail || e?.message))
    } finally {
      setLoading(false)
    }
  }

  const handleClearCache = async () => {
    if (!confirm('Xóa cache stem và tách lại từ đầu?')) return
    try {
      await stemApi.clearCache(projectId)
      setCached(null)
      setStatus({ status: 'idle', progress: 0, message: '', result: null, error: null })
    } catch (e: any) {
      alert('Lỗi: ' + (e?.response?.data?.detail || e?.message))
    }
  }

  const handleAddToBgm = useCallback(() => {
    if (!cached) return
    const tracks = Object.entries(cached).map(([name, url]) => ({
      name: `${STEM_LABELS[name] || name} (gốc)`,
      url,
      volume: STEM_VOLUME,
    }))
    onAddStemsToBgm(tracks)
  }, [cached, onAddStemsToBgm])

  const isRunning = status.status === 'running' || status.status === 'pending'
  const hasCache = cached && Object.keys(cached).length === 3

  // ─── Render ────────────────────────────────────────────────────
  return (
    <div className="border border-zinc-200 dark:border-zinc-800 rounded-lg p-4 bg-zinc-50 dark:bg-zinc-900/50">
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <div>
          <h3 className="text-[14px] font-semibold flex items-center gap-2">
            🎚 Tách audio từ video gốc (Demucs)
          </h3>
          <p className="text-[11px] text-zinc-500 mt-0.5">
            Tự động trích 3 stem (bass, drums, vocals) thêm vào BGM với volume 30%
          </p>
        </div>
        {info && (
          <div className="text-[10px] flex flex-col items-end gap-0.5">
            {info.cuda_available ? (
              <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40">
                🚀 GPU (CUDA)
              </span>
            ) : (
              <span className="px-1.5 py-0.5 rounded bg-zinc-100 text-zinc-600 dark:bg-zinc-800">
                CPU (chậm)
              </span>
            )}
            <span className="text-zinc-500">model: {info.model}</span>
          </div>
        )}
      </div>

      {/* Demucs chưa cài */}
      {info && !info.demucs_installed && (
        <div className="text-[12px] text-amber-700 bg-amber-50 dark:bg-amber-950/30 rounded p-2 border border-amber-200 dark:border-amber-900">
          ⚠️ Demucs chưa được cài. Chạy trên server:
          <pre className="mt-1 text-[11px] font-mono bg-white dark:bg-zinc-900 rounded p-2">pip install demucs --break-system-packages</pre>
        </div>
      )}

      {/* Running */}
      {isRunning && (
        <div className="space-y-2 my-3">
          <div className="flex items-center justify-between text-[12px]">
            <span className="text-zinc-700 dark:text-zinc-300">{status.message || 'Đang xử lý...'}</span>
            <span className="font-mono text-zinc-500">{Math.round(status.progress * 100)}%</span>
          </div>
          <div className="h-2 bg-zinc-200 dark:bg-zinc-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-300"
              style={{ width: `${status.progress * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Error */}
      {status.status === 'error' && status.error && (
        <div className="text-[12px] text-red-700 bg-red-50 dark:bg-red-950/30 rounded p-2 my-2">
          ✕ Lỗi: {status.error}
        </div>
      )}

      {/* Cache + add button */}
      {hasCache && !isRunning && (
        <div className="space-y-2 my-3">
          <div className="text-[12px] text-emerald-700 bg-emerald-50 dark:bg-emerald-950/30 rounded p-2 border border-emerald-200 dark:border-emerald-900">
            ✓ Đã tách 3 stem
          </div>
          <div className="grid grid-cols-3 gap-2 text-[11px]">
            {Object.entries(cached).map(([name, url]) => (
              <div key={name} className="border border-zinc-200 dark:border-zinc-700 rounded p-2 bg-white dark:bg-zinc-900">
                <div className="font-medium">{STEM_LABELS[name] || name}</div>
                <audio controls src={url} className="w-full mt-1 h-7" preload="none" />
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center gap-2 mt-3">
        {!hasCache && !isRunning && (
          <button
            onClick={handleSeparate}
            disabled={loading || !info?.demucs_installed}
            className="btn btn-primary text-[13px]"
          >
            {loading ? '⏳ Đang khởi tạo...' : '🎚 Tách audio'}
          </button>
        )}
        {hasCache && !isRunning && (
          <>
            <button
              onClick={handleAddToBgm}
              className="btn btn-primary text-[13px]"
            >
              + Thêm 3 stem vào BGM (30% vol)
            </button>
            <button
              onClick={handleClearCache}
              className="btn text-[12px] text-zinc-600"
              title="Xóa cache và tách lại"
            >
              🔄 Tách lại
            </button>
          </>
        )}
      </div>

      {/* GPU/CPU estimate */}
      {!hasCache && !isRunning && info?.demucs_installed && (
        <div className="text-[10px] text-zinc-500 mt-2">
          Ước tính: {info.cuda_available ? '~10-30 giây' : '~2-4 phút'} cho video 1-3 phút
        </div>
      )}
    </div>
  )
}
