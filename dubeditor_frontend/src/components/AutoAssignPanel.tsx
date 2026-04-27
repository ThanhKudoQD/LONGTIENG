import React, { useState, useRef, useEffect } from 'react'
import useStore from '../store'
import api from '../api'

interface Cluster {
  cluster_id: string
  line_count: number
  subtitle_ids: number[]
  high_count: number
  medium_count: number
  low_count: number
  sample_texts: string[]
  sample_starts: number[]
  thumbnail: string | null
  _assigned?: boolean
  _charName?: string
  _charColor?: string
}

interface Props {
  projectId: number
  onClose: () => void
}

type Step = 'setup' | 'running' | 'review'

export default function AutoAssignPanel({ projectId, onClose }: Props) {
  const { characters, updateSubtitle, setCharacters } = useStore()
  const [step, setStep] = useState<Step>('setup')
  const [progress, setProgress] = useState(0)
  const [stepMsg, setStepMsg] = useState('')
  const [logs, setLogs] = useState<string[]>([])
  const [clusters, setClusters] = useState<Cluster[]>([])
  const [reviewIdx, setReviewIdx] = useState(0)
  const [selectedCharId, setSelectedCharId] = useState<number | null>(null)
  const [confirming, setConfirming] = useState(false)
  const [applying, setApplying] = useState(false)
  const [minSpk, setMinSpk] = useState(2)
  const [maxSpk, setMaxSpk] = useState(15)
  const logRef = useRef<HTMLDivElement>(null)

  const addLog = (msg: string) => {
    const ts = new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
    setLogs(prev => [...prev, `${ts} — ${msg}`])
    setTimeout(() => logRef.current?.scrollTo(0, logRef.current.scrollHeight), 50)
  }

  // Nhận event từ WebSocket forward
  useEffect(() => {
    const onProg = (e: any) => {
      setProgress(e.detail.pct); setStepMsg(e.detail.step); addLog(e.detail.step)
    }
    const onDone = (e: any) => {
      setClusters(e.detail.clusters || [])
      setReviewIdx(0); setSelectedCharId(null); setStep('review')
      addLog(`✓ Hoàn thành! ${(e.detail.clusters||[]).length} nhóm giọng.`)
    }
    const onErr = (e: any) => {
      addLog('❌ ' + e.detail.error); setStep('setup')
    }
    window.addEventListener('aa_progress', onProg)
    window.addEventListener('aa_done', onDone)
    window.addEventListener('aa_error', onErr)
    return () => {
      window.removeEventListener('aa_progress', onProg)
      window.removeEventListener('aa_done', onDone)
      window.removeEventListener('aa_error', onErr)
    }
  }, [])

  // Poll fallback
  const pollStatus = async () => {
    while (true) {
      await new Promise(r => setTimeout(r, 2000))
      try {
        const res = await api.get(`/projects/${projectId}/auto-assign/status`)
        const job = res.data
        if (job.progress) { setProgress(job.progress); setStepMsg(job.step || ''); addLog(job.step || '') }
        if (job.status === 'done') {
          setClusters(job.result?.clusters || [])
          setReviewIdx(0); setSelectedCharId(null); setStep('review')
          break
        }
        if (job.status === 'error') { addLog('❌ ' + job.error); setStep('setup'); break }
      } catch {}
    }
  }

  const start = async () => {
    setStep('running'); setProgress(0); setLogs([])
    addLog('Bắt đầu pipeline...')
    try {
      await api.post(`/projects/${projectId}/auto-assign/start`, {
        project_id: projectId, min_speakers: minSpk, max_speakers: maxSpk
      })
      addLog('Pipeline đã bắt đầu — đang chờ kết quả...')
      pollStatus()
    } catch (err: any) {
      addLog('❌ ' + (err.response?.data?.detail || err.message))
      setStep('setup')
    }
  }

  const confirm = async () => {
    if (!selectedCharId) return
    const cluster = clusters[reviewIdx]; if (!cluster) return
    const char = characters.find(c => c.id === selectedCharId); if (!char) return
    setConfirming(true)
    try {
      await api.post(`/projects/${projectId}/auto-assign/confirm-group`, {
        project_id: projectId, cluster_id: cluster.cluster_id, character_id: selectedCharId
      })
      cluster.subtitle_ids.forEach(sid => updateSubtitle(sid, { character_id: selectedCharId, character: char }))
      const updated = [...clusters]
      updated[reviewIdx] = { ...cluster, _assigned: true, _charName: char.name, _charColor: char.color }
      setClusters(updated)
      if (reviewIdx < clusters.length - 1) { setReviewIdx(i => i + 1); setSelectedCharId(null) }
    } finally { setConfirming(false) }
  }

  const skip = () => {
    if (reviewIdx < clusters.length - 1) { setReviewIdx(i => i + 1); setSelectedCharId(null) }
  }

  const autoApply = async () => {
    setApplying(true)
    try {
      const res = await api.post(`/projects/${projectId}/auto-assign/auto-apply`)
      const subsRes = await api.get(`/subtitles/project/${projectId}`)
      useStore.getState().setSubtitles(subsRes.data)
      const charsRes = await api.get(`/characters/project/${projectId}`)
      useStore.getState().setCharacters(charsRes.data)
      addLog(`✓ Tạo ${res.data.created} nhân vật, gán ${res.data.assigned} dòng`)
      onClose()
    } catch(err: any) {
      addLog('❌ ' + (err.response?.data?.detail || err.message))
    } finally { setApplying(false) }
  }

  const applyAll = async () => {
    setApplying(true)
    try {
      const res = await api.post(`/projects/${projectId}/auto-assign/apply-all`)
      const subsRes = await api.get(`/subtitles/project/${projectId}`)
      useStore.getState().setSubtitles(subsRes.data)
      addLog(`✓ Apply ${res.data.applied} dòng High confidence`)
    } finally { setApplying(false) }
  }

  const circ = 2 * Math.PI * 30

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-black/80 backdrop-blur-sm">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 h-11 bg-zinc-900 border-b border-zinc-800 flex-shrink-0">
        <div className="w-5 h-5 rounded-full bg-purple-600 flex items-center justify-center flex-shrink-0">
          <svg width="10" height="10" viewBox="0 0 12 12" fill="none">
            <circle cx="6" cy="6" r="5" stroke="white" strokeWidth="1.2"/>
            <path d="M4 6l1.5 1.5L8 4" stroke="white" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
        <span className="text-[13px] font-semibold text-white flex-1">Tự động gán nhân vật — AI Pipeline</span>
        {step === 'review' && (
          <span className="text-[11px] text-zinc-500 font-mono">
            {clusters.filter(c => c._assigned).length}/{clusters.length} đã xác nhận
          </span>
        )}
        <button onClick={onClose} className="w-7 h-7 rounded-lg flex items-center justify-center text-zinc-400 hover:bg-zinc-800 hover:text-white transition-colors text-[12px]">✕</button>
      </div>

      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* LEFT */}
        <div className="flex-1 flex flex-col overflow-hidden min-h-0">

          {/* SETUP */}
          {step === 'setup' && (
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              <p className="text-[14px] font-semibold text-white">Phân tích video để tự động gán nhân vật</p>
              <p className="text-[12px] text-zinc-400 leading-relaxed">
                Pipeline: <span className="text-zinc-200">Demucs</span> tách giọng →{' '}
                <span className="text-zinc-200">Pyannote</span> phân tách speaker →{' '}
                <span className="text-zinc-200">InsightFace</span> verify khẩu hình →{' '}
                Tính confidence
              </p>
              <div className="flex gap-2 p-3 bg-amber-950/40 border border-amber-800/50 rounded-lg">
                <span className="text-amber-400 text-[15px] flex-shrink-0 mt-0.5">⚡</span>
                <p className="text-[11px] text-amber-300 leading-relaxed">
                  <b>VoxCPM2 sẽ bị tạm dừng</b> trong quá trình phân tích để giải phóng VRAM.
                  TTS không khả dụng cho đến khi hoàn thành.
                </p>
              </div>
              <div className="space-y-3">
                <p className="text-[10px] text-zinc-500 uppercase tracking-wide font-medium">Cài đặt</p>
                <div className="flex items-center gap-3">
                  <span className="text-[12px] text-zinc-400 w-28">Min speakers</span>
                  <input type="range" min={1} max={8} value={minSpk} onChange={e => setMinSpk(+e.target.value)} className="flex-1 accent-purple-500" />
                  <span className="text-[11px] text-purple-400 font-mono w-6">{minSpk}</span>
                </div>
                <div className="flex items-center gap-3">
                  <span className="text-[12px] text-zinc-400 w-28">Max speakers</span>
                  <input type="range" min={2} max={20} value={maxSpk} onChange={e => setMaxSpk(+e.target.value)} className="flex-1 accent-purple-500" />
                  <span className="text-[11px] text-purple-400 font-mono w-6">{maxSpk}</span>
                </div>
              </div>
              <button onClick={start}
                className="flex items-center gap-2 px-5 py-2.5 bg-purple-600 hover:bg-purple-500 text-white text-[13px] font-semibold rounded-lg transition-colors">
                <svg width="12" height="12" viewBox="0 0 14 14" fill="none"><polygon points="3,1 13,7 3,13" fill="currentColor"/></svg>
                Bắt đầu phân tích
              </button>
            </div>
          )}

          {/* RUNNING */}
          {step === 'running' && (
            <div className="flex-1 flex flex-col items-center justify-center gap-4 p-6">
              <div className="relative w-20 h-20">
                <svg width="80" height="80" viewBox="0 0 80 80" style={{ transform: 'rotate(-90deg)' }}>
                  <circle cx="40" cy="40" r="30" fill="none" stroke="#3f3f46" strokeWidth="6"/>
                  <circle cx="40" cy="40" r="30" fill="none" stroke="#9333ea" strokeWidth="6"
                    strokeDasharray={circ} strokeDashoffset={circ * (1 - progress / 100)}
                    strokeLinecap="round" style={{ transition: 'stroke-dashoffset 0.5s' }}/>
                </svg>
                <div className="absolute inset-0 flex items-center justify-center">
                  <span className="text-[15px] font-bold text-white font-mono">{progress}%</span>
                </div>
              </div>
              <p className="text-[12px] text-zinc-300 text-center max-w-xs leading-relaxed">{stepMsg}</p>
              <div ref={logRef} className="w-full max-w-sm bg-zinc-900 rounded-lg p-2.5 text-[10px] font-mono text-zinc-500 max-h-28 overflow-y-auto space-y-0.5">
                {logs.map((l, i) => <div key={i}>{l}</div>)}
              </div>
            </div>
          )}

          {/* REVIEW */}
          {step === 'review' && (
            <div className="flex-1 flex flex-col overflow-hidden min-h-0">
              <div className="flex items-center gap-3 px-4 py-2 border-b border-zinc-800 flex-shrink-0 bg-zinc-900/50">
                <span className="text-[12px] font-semibold text-white flex-1">Review nhóm giọng</span>
                <span className="text-[11px] text-zinc-500 font-mono">{reviewIdx + 1} / {clusters.length}</span>
              <button onClick={autoApply} disabled={applying}
                className="px-3 py-1 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-[11px] font-semibold rounded-lg transition-colors">
                {applying ? '...' : '⚡ Tự động gán tất cả'}
              </button>
              </div>
              <div className="flex-1 overflow-y-auto p-3 space-y-2">
                {clusters.map((c, i) => (
                  <div key={c.cluster_id}
                    className={`rounded-lg border overflow-hidden cursor-pointer transition-all ${i === reviewIdx ? 'border-blue-600 bg-zinc-800/60' : c._assigned ? 'border-zinc-700 bg-zinc-900/20' : 'border-zinc-800 bg-zinc-900/10'}`}
                    onClick={() => { setReviewIdx(i); setSelectedCharId((c as any)._charId || null) }}>
                    <div className="flex items-center gap-2 px-3 py-2 bg-zinc-800/40">
                      {c.thumbnail
                        ? <img src={c.thumbnail} className="w-7 h-9 rounded object-cover object-top flex-shrink-0" alt="" />
                        : <div className="w-7 h-9 rounded bg-zinc-700 flex items-center justify-center text-[11px] flex-shrink-0 text-zinc-400">🎤</div>}
                      <span className="text-[11px] text-zinc-400 font-mono flex-1">{c.cluster_id}</span>
                      <span className="text-[11px] text-zinc-500 font-mono">{c.line_count}d</span>
                      <div className="flex gap-1">
                        {c.high_count > 0 && <span className="text-[9px] px-1.5 py-0.5 rounded bg-emerald-950 text-emerald-400 font-mono">{c.high_count}✓</span>}
                        {c.medium_count > 0 && <span className="text-[9px] px-1.5 py-0.5 rounded bg-amber-950 text-amber-400 font-mono">{c.medium_count}~</span>}
                        {c.low_count > 0 && <span className="text-[9px] px-1.5 py-0.5 rounded bg-red-950 text-red-400 font-mono">{c.low_count}!</span>}
                      </div>
                      {c._assigned && (
                        <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full"
                          style={{ background: (c._charColor || '#185FA5') + '25', color: c._charColor || '#185FA5' }}>
                          {c._charName}
                        </span>
                      )}
                    </div>
                    {i === reviewIdx && (
                      <div className="px-3 py-1.5 space-y-1">
                        {c.sample_texts.slice(0, 3).map((txt, j) => (
                          <div key={j} className="flex items-center gap-2 text-[11px] hover:opacity-75 cursor-pointer"
                            onClick={e => { e.stopPropagation(); window.dispatchEvent(new CustomEvent('seek_video', { detail: c.sample_starts[j] || 0 })) }}>
                            <span className="text-zinc-600 font-mono text-[10px] flex-shrink-0">
                              {Math.floor((c.sample_starts[j]||0)/60).toString().padStart(2,'0')}:{Math.floor((c.sample_starts[j]||0)%60).toString().padStart(2,'0')}
                            </span>
                            <span className="text-zinc-300 truncate">{txt}</span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT: char selection */}
        <div className="w-52 flex-shrink-0 border-l border-zinc-800 flex flex-col bg-zinc-900/50 min-h-0">
          <div className="flex-1 overflow-y-auto p-3 min-h-0">
            <p className="text-[9px] text-zinc-500 uppercase tracking-wide font-medium mb-2">
              {step === 'setup' ? 'Nhân vật trong project' : `Gán nhóm vào nhân vật`}
            </p>
            <div className="space-y-1.5">
              {characters.map(c => (
                <button key={c.id} onClick={() => setSelectedCharId(c.id)}
                  className={`flex items-center gap-2 w-full px-2.5 py-2 rounded-lg border text-left transition-all ${selectedCharId === c.id ? 'border-blue-500 bg-blue-950/40' : 'border-zinc-700 bg-zinc-800/40 hover:border-zinc-600'}`}>
                  <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: c.color }}/>
                  <span className="text-[12px] font-medium text-zinc-200 flex-1 truncate">{c.name}</span>
                  {selectedCharId === c.id && <span className="text-blue-400 text-[10px]">✓</span>}
                </button>
              ))}
            </div>
          </div>

          {step === 'review' && (
            <div className="p-3 border-t border-zinc-800 space-y-2 flex-shrink-0">
              <button onClick={confirm} disabled={!selectedCharId || confirming}
                className="w-full py-2 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-[12px] font-semibold rounded-lg transition-colors">
                {confirming ? '...' : '✓ Xác nhận & tiếp'}
              </button>
              <button onClick={skip} disabled={reviewIdx >= clusters.length - 1}
                className="w-full py-2 border border-zinc-700 text-zinc-400 hover:border-zinc-500 hover:text-zinc-300 disabled:opacity-30 text-[12px] rounded-lg transition-colors">
                Bỏ qua →
              </button>
              <div className="h-px bg-zinc-800"/>
              <button onClick={applyAll} disabled={applying}
                className="w-full py-2 bg-blue-700 hover:bg-blue-600 disabled:opacity-40 text-white text-[12px] font-semibold rounded-lg transition-colors">
                {applying ? '...' : '⚡ Apply tất cả High'}
              </button>
              <p className="text-[9px] text-zinc-600 text-center leading-tight">Apply tự động dòng confidence cao</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}