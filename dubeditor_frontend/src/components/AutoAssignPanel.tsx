import React, { useState, useRef, useEffect, useCallback } from 'react'
import useStore from '../store'
import api from '../api'

interface Props {
  projectId: number
  onClose: () => void
}

type Status = 'idle' | 'running' | 'done' | 'error' | 'cancelled'

interface JobState {
  status: Status
  progress: number
  total_batches: number
  done_batches: number
  total_lines: number
  done_lines: number
  speaker_count: number
  logs: string[]
  error?: string
  started_at?: string
}

const EMPTY_JOB: JobState = {
  status: 'idle', progress: 0,
  total_batches: 0, done_batches: 0,
  total_lines: 0, done_lines: 0,
  speaker_count: 0, logs: [],
}

export default function AutoAssignPanel({ projectId, onClose }: Props) {
  const characters = useStore(s => s.characters)
  const [job, setJob]         = useState<JobState>(EMPTY_JOB)
  const [batchSize, setBatchSize] = useState(50)
  const [minSpk, setMinSpk]   = useState(5)
  const [useDemucs, setUseDemucs] = useState(false)
  const [maxSpk, setMaxSpk]   = useState(15)
  const [starting, setStarting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const logRef = useRef<HTMLDivElement>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Auto scroll log
  useEffect(() => {
    if (logRef.current)
      logRef.current.scrollTop = logRef.current.scrollHeight
  }, [job.logs])

  // Poll status từ server
  const fetchStatus = useCallback(async () => {
    try {
      const res = await api.get(`/projects/${projectId}/auto-assign/status`)
      const d   = res.data
      setJob({
        status:        d.status,
        progress:      d.progress || 0,
        total_batches: d.total_batches || 0,
        done_batches:  d.done_batches  || 0,
        total_lines:   d.total_lines   || 0,
        done_lines:    d.done_lines    || 0,
        speaker_count: d.speaker_count || 0,
        logs:          d.logs          || [],
        error:         d.error,
        started_at:    d.started_at,
      })
      return d.status
    } catch (err: any) {
      if (err.response?.status === 404) return 'idle'
      return null
    }
  }, [projectId])

  // Khởi tạo: check status ngay khi mở panel
  useEffect(() => {
    fetchStatus().then(status => {
      if (status === 'running') startPolling()
    })
  }, [])

  // WS events
  useEffect(() => {
    const onProg = (e: any) => {
      setJob(prev => ({
        ...prev,
        status:        'running',
        progress:      e.detail.pct       || prev.progress,
        done_batches:  e.detail.done_batches ?? prev.done_batches,
        total_batches: e.detail.total_batches ?? prev.total_batches,
        done_lines:    e.detail.done_lines ?? prev.done_lines,
        total_lines:   e.detail.total_lines ?? prev.total_lines,
        logs:          e.detail.logs || prev.logs,
      }))
    }
    const onBatchDone = async (e: any) => {
      // Reload subtitles + characters sau mỗi batch
      try {
        const [subsRes, charsRes] = await Promise.all([
          api.get(`/subtitles/project/${projectId}`),
          api.get(`/characters/project/${projectId}`),
        ])
        useStore.getState().setSubtitles(subsRes.data)
        useStore.getState().setCharacters(charsRes.data)
      } catch {}
    }
    const onDone = async (e: any) => {
      setJob(prev => ({ ...prev, status: 'done', progress: 100, logs: e.detail.logs || prev.logs }))
      stopPolling()
      // Final reload
      try {
        const [subsRes, charsRes] = await Promise.all([
          api.get(`/subtitles/project/${projectId}`),
          api.get(`/characters/project/${projectId}`),
        ])
        useStore.getState().setSubtitles(subsRes.data)
        useStore.getState().setCharacters(charsRes.data)
      } catch {}
    }
    const onErr = (e: any) => {
      setJob(prev => ({ ...prev, status: 'error', error: e.detail.error }))
      stopPolling()
    }
    window.addEventListener('aa_progress',   onProg)
    window.addEventListener('aa_batch_done', onBatchDone)
    window.addEventListener('aa_done',       onDone)
    window.addEventListener('aa_error',      onErr)
    return () => {
      window.removeEventListener('aa_progress',   onProg)
      window.removeEventListener('aa_batch_done', onBatchDone)
      window.removeEventListener('aa_done',       onDone)
      window.removeEventListener('aa_error',      onErr)
    }
  }, [projectId])

  const startPolling = () => {
    if (pollRef.current) return
    pollRef.current = setInterval(() => fetchStatus(), 3000)
  }
  const stopPolling = () => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null }
  }
  useEffect(() => () => stopPolling(), [])

  const handleStart = async () => {
    setStarting(true)
    try {
      await api.post(`/projects/${projectId}/auto-assign/start`, {
        project_id: projectId,
        batch_size: batchSize,
        min_speakers: minSpk,
        max_speakers: maxSpk,
        match_existing: true,
        use_demucs: useDemucs,
      })
      setJob({ ...EMPTY_JOB, status: 'running' })
      startPolling()
    } catch (err: any) {
      alert(err.response?.data?.detail || err.message)
    } finally { setStarting(false) }
  }

  const handleCancel = async () => {
    setCancelling(true)
    try {
      await api.post(`/projects/${projectId}/auto-assign/cancel`)
      setJob(prev => ({ ...prev, status: 'cancelled' }))
      stopPolling()
    } finally { setCancelling(false) }
  }

  const handleReset = async () => {
    if (!confirm('Xóa toàn bộ kết quả và chạy lại từ đầu?')) return
    await api.delete(`/projects/${projectId}/auto-assign/reset`)
    setJob(EMPTY_JOB)
    stopPolling()
  }

  const isRunning  = job.status === 'running'
  const isDone     = job.status === 'done'
  const isError    = job.status === 'error'
  const isCancelled = job.status === 'cancelled'
  const isIdle     = job.status === 'idle'

  const batchPct = job.total_batches > 0
    ? Math.round(job.done_batches / job.total_batches * 100) : 0
  const circ = 2 * Math.PI * 36

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
      <div className="w-[560px] max-h-[85vh] flex flex-col rounded-2xl bg-zinc-900 border border-zinc-700 shadow-2xl overflow-hidden">

        {/* Header */}
        <div className="flex items-center gap-3 px-5 h-12 border-b border-zinc-800 flex-shrink-0">
          <div className="w-6 h-6 rounded-full bg-purple-600 flex items-center justify-center flex-shrink-0">
            <svg width="11" height="11" viewBox="0 0 14 14" fill="none">
              <polygon points="3,1 13,7 3,13" fill="white"/>
            </svg>
          </div>
          <span className="text-[14px] font-semibold text-white flex-1">AI Gán Nhân Vật Tự Động</span>
          {isRunning && (
            <span className="text-[11px] text-purple-400 font-mono animate-pulse">● Đang chạy</span>
          )}
          <button onClick={onClose}
            className="w-7 h-7 rounded-lg flex items-center justify-center text-zinc-400 hover:bg-zinc-800 hover:text-white transition-colors text-[13px]">
            ✕
          </button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">

          {/* ── SETUP ── */}
          {(isIdle || isCancelled || isError) && (
            <div className="p-5 space-y-5">
              {isError && (
                <div className="flex gap-2 p-3 rounded-lg bg-red-950/50 border border-red-800/60">
                  <span className="text-red-400 text-[13px]">❌</span>
                  <p className="text-[12px] text-red-300">{job.error}</p>
                </div>
              )}
              {isCancelled && (
                <div className="flex gap-2 p-3 rounded-lg bg-zinc-800/60 border border-zinc-700">
                  <span className="text-zinc-400 text-[13px]">⏹</span>
                  <p className="text-[12px] text-zinc-400">Job đã bị hủy. Có thể chạy lại.</p>
                </div>
              )}

              <div>
                <p className="text-[13px] font-semibold text-white mb-1">Pipeline mới</p>
                <p className="text-[11px] text-zinc-500 leading-relaxed">
                  ffmpeg cắt audio toàn bộ → Pyannote diarize 1 lần → Match SRT → Tạo nhân vật → Apply DB
                </p>
              </div>

              <div className="p-3 rounded-lg bg-amber-950/30 border border-amber-800/40">
                <p className="text-[11px] text-amber-300 leading-relaxed">
                  ⚡ <b>VoxCPM2 sẽ tạm dừng</b> trong quá trình phân tích. TTS không khả dụng cho đến khi hoàn thành.
                </p>
              </div>

              {/* Config */}
              <div className="space-y-3">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold">Cài đặt</p>


                <div className="flex items-center gap-3">
                  <span className="text-[12px] text-zinc-400 w-32 flex-shrink-0">Min speakers</span>
                  <input type="range" min={1} max={20} value={minSpk}
                    onChange={e => setMinSpk(+e.target.value)} className="flex-1 accent-purple-500"/>
                  <span className="text-[12px] text-purple-400 font-mono w-8 text-right">{minSpk}</span>
                </div>
                <p className="text-[10px] text-zinc-500">Nếu biết có bao nhiêu nhân vật thì set đúng số đó để Pyannote chính xác hơn</p>
                <div className="flex items-center gap-2 mt-1 cursor-pointer" onClick={() => setUseDemucs(v => !v)}>
                  <div className={`w-4 h-4 rounded border-2 flex items-center justify-center transition-colors ${useDemucs ? 'bg-purple-600 border-purple-600' : 'border-zinc-600'}`}>
                    {useDemucs && <svg width="10" height="10" viewBox="0 0 10 10" fill="none"><path d="M2 5l2 2 4-4" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>}
                  </div>
                  <span className="text-[12px] text-zinc-300">Dùng Demucs tách vocals trước</span>
                  <span className="text-[10px] text-zinc-500">(chính xác hơn nhưng chậm hơn)</span>
                </div>

                <div className="flex items-center gap-2 pt-1">
                  <div className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0"/>
                  <span className="text-[11px] text-zinc-400">
                    Match với <b className="text-zinc-300">{characters.length}</b> nhân vật hiện có
                  </span>
                </div>
              </div>

              <div className="flex gap-2 pt-1">
                <button onClick={handleStart} disabled={starting}
                  className="flex items-center gap-2 px-5 py-2.5 bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-[13px] font-semibold rounded-lg transition-colors">
                  {starting
                    ? <div className="w-4 h-4 rounded-full border-2 border-white border-t-transparent animate-spin"/>
                    : <svg width="12" height="12" viewBox="0 0 14 14" fill="none"><polygon points="2,1 13,7 2,13" fill="currentColor"/></svg>
                  }
                  {starting ? 'Đang khởi động...' : 'Bắt đầu'}
                </button>
                {(isError || isCancelled) && (
                  <button onClick={handleReset}
                    className="px-4 py-2.5 border border-zinc-700 text-zinc-400 hover:border-red-700 hover:text-red-400 text-[12px] rounded-lg transition-colors">
                    Reset & chạy lại
                  </button>
                )}
              </div>
            </div>
          )}

          {/* ── RUNNING ── */}
          {isRunning && (
            <div className="p-5 space-y-5">
              {/* Progress circle + batch info */}
              <div className="flex items-center gap-5">
                <div className="relative w-20 h-20 flex-shrink-0">
                  <svg width="80" height="80" viewBox="0 0 80 80" style={{ transform: 'rotate(-90deg)' }}>
                    <circle cx="40" cy="40" r="36" fill="none" stroke="#27272a" strokeWidth="7"/>
                    <circle cx="40" cy="40" r="36" fill="none" stroke="#9333ea" strokeWidth="7"
                      strokeDasharray={circ}
                      strokeDashoffset={circ * (1 - batchPct / 100)}
                      strokeLinecap="round"
                      style={{ transition: 'stroke-dashoffset 0.6s ease' }}/>
                  </svg>
                  <div className="absolute inset-0 flex flex-col items-center justify-center">
                    <span className="text-[16px] font-bold text-white font-mono">{batchPct}%</span>
                  </div>
                </div>

                <div className="flex-1 space-y-2">
                  <div>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="text-zinc-400">Batch</span>
                      <span className="text-zinc-300 font-mono">{job.done_batches} / {job.total_batches}</span>
                    </div>
                    <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                      <div className="h-full bg-purple-500 rounded-full transition-all duration-500"
                        style={{ width: `${batchPct}%` }}/>
                    </div>
                  </div>
                  <div>
                    <div className="flex justify-between text-[11px] mb-1">
                      <span className="text-zinc-400">Dòng phụ đề</span>
                      <span className="text-zinc-300 font-mono">{job.done_lines} / {job.total_lines}</span>
                    </div>
                    <div className="h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                      <div className="h-full bg-blue-500 rounded-full transition-all duration-500"
                        style={{ width: `${job.total_lines > 0 ? Math.round(job.done_lines/job.total_lines*100) : 0}%` }}/>
                    </div>
                  </div>
                  {job.speaker_count > 0 && (
                    <div className="flex items-center gap-1.5">
                      <div className="w-1.5 h-1.5 rounded-full bg-emerald-500"/>
                      <span className="text-[11px] text-zinc-400">
                        Đã nhận diện <b className="text-emerald-400">{job.speaker_count}</b> nhân vật
                      </span>
                    </div>
                  )}
                </div>
              </div>

              {/* Log */}
              <div>
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold mb-1.5">Log</p>
                <div ref={logRef}
                  className="bg-zinc-950 rounded-lg p-3 h-40 overflow-y-auto space-y-0.5 font-mono text-[11px]">
                  {job.logs.length === 0
                    ? <span className="text-zinc-600">Đang chờ...</span>
                    : job.logs.map((l, i) => (
                      <div key={i} className={`leading-relaxed ${
                        l.includes('LỖI') || l.includes('lỗi') ? 'text-red-400' :
                        l.includes('Hoàn thành') || l.includes('✓') ? 'text-emerald-400' :
                        l.includes('Tạo nhân vật') ? 'text-purple-400' :
                        l.includes('Apply') ? 'text-blue-400' :
                        'text-zinc-400'
                      }`}>{l}</div>
                    ))
                  }
                </div>
              </div>

              <div className="flex items-center gap-3 pt-1">
                <div className="flex items-center gap-2 flex-1">
                  <div className="w-1.5 h-1.5 rounded-full bg-purple-500 animate-pulse"/>
                  <span className="text-[11px] text-zinc-500">Đóng panel — job vẫn tiếp tục chạy</span>
                </div>
                <button onClick={handleCancel} disabled={cancelling}
                  className="px-4 py-2 border border-red-800 text-red-400 hover:bg-red-950 disabled:opacity-50 text-[12px] font-medium rounded-lg transition-colors">
                  {cancelling ? 'Đang hủy...' : '⏹ Hủy'}
                </button>
              </div>
            </div>
          )}

          {/* ── DONE ── */}
          {isDone && (
            <div className="p-5 space-y-4">
              <div className="flex items-center gap-3 p-4 rounded-xl bg-emerald-950/40 border border-emerald-800/50">
                <div className="w-10 h-10 rounded-full bg-emerald-600 flex items-center justify-center flex-shrink-0">
                  <svg width="20" height="20" viewBox="0 0 20 20" fill="none">
                    <path d="M4 10l4 4 8-8" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                </div>
                <div>
                  <p className="text-[14px] font-semibold text-emerald-300">Hoàn thành!</p>
                  <p className="text-[12px] text-emerald-500">
                    {job.done_lines} dòng · {job.speaker_count} nhân vật · {job.done_batches} batch
                  </p>
                </div>
              </div>

              {/* Log */}
              <div>
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold mb-1.5">Log cuối</p>
                <div ref={logRef}
                  className="bg-zinc-950 rounded-lg p-3 h-32 overflow-y-auto space-y-0.5 font-mono text-[11px]">
                  {job.logs.map((l, i) => (
                    <div key={i} className={`leading-relaxed ${
                      l.includes('Hoàn thành') || l.includes('✓') ? 'text-emerald-400' :
                      l.includes('Tạo nhân vật') ? 'text-purple-400' :
                      l.includes('Apply') ? 'text-blue-400' : 'text-zinc-400'
                    }`}>{l}</div>
                  ))}
                </div>
              </div>

              <div className="flex gap-2">
                <button onClick={onClose}
                  className="flex-1 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-[13px] font-semibold rounded-lg transition-colors">
                  Đóng & tiếp tục làm việc
                </button>
                <button onClick={handleReset}
                  className="px-4 py-2.5 border border-zinc-700 text-zinc-400 hover:border-zinc-500 text-[12px] rounded-lg transition-colors">
                  Chạy lại
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}