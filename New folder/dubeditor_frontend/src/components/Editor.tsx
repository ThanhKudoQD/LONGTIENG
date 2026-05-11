import React, { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import useStore, { usePlayTimeStore } from '../store'
import api from '../api'
import CharSidebar from './CharSidebar'
import SubtitleList from './SubtitleList'
import EditPanel from './EditPanel'
import AudioList from './AudioList'
import VideoPlayer from './VideoPlayer'
import DetailPanel from './DetailPanel'
import { useProjectWS } from '../hooks/useProjectWS'
import { parseShortcutFromEvent, formatShortcut } from '../utils/shortcuts'
import AutoAssignPanel from './AutoAssignPanel'
import AutoFixOverlapModal from './AutoFixOverlapModal'
import BulkTTSProgress from './BulkTTSProgress'
import ChapterSelector from './ChapterSelector'
import ChaptersModal from './ChaptersModal'

interface Props { projectId: number; onBack: () => void }

export default function Editor({ projectId, onBack }: Props) {
  // PERF: selectors riêng — KHÔNG destructure
  const project = useStore(s => s.project)
  const subtitles = useStore(s => s.subtitles)
  const characters = useStore(s => s.characters)
  const autoTTS = useStore(s => s.autoTTS)
  const setAutoTTS = useStore(s => s.setAutoTTS)
  const activeSubId = useStore(s => s.activeSubId)
  const loadProject = useStore(s => s.loadProject)
  const setActiveSubId = useStore(s => s.setActiveSubId)
  const updateSubtitle = useStore(s => s.updateSubtitle)
  const [sidebarVisible, setSidebarVisible] = useState(true)
  const [filter, setFilter] = useState('')
  const [filterNoChar, setFilterNoChar] = useState(false)
  const [filterNoTTS, setFilterNoTTS] = useState(false)
  const [filterOverlap, setFilterOverlap] = useState(false)
  const [filterCharId, setFilterCharId]   = useState<number | null>(null)
  const [swapFrom, setSwapFrom]           = useState<number | null>(null)
  const [swapTo, setSwapTo]               = useState<number | null>(null)
  const [swapping, setSwapping]           = useState(false)
  const [showAutoAssign, setShowAutoAssign] = useState(false)
  const [showAutoFix, setShowAutoFix] = useState(false)
  const [showChapters, setShowChapters] = useState(false)

  // Chapters local state — dùng để render trong SubtitleList với collapse + statistics
  // Auto TTS — gom các sub vừa gán vào microtask batch, gọi 1 request enqueue
  const autoTTSBatchRef = useRef<Set<number>>(new Set())
  const autoTTSScheduledRef = useRef(false)

  const triggerAutoTTS = useCallback((subIds: number[]) => {
    if (!useStore.getState().autoTTS) return
    if (!subIds.length) return
    for (const id of subIds) autoTTSBatchRef.current.add(id)
    if (autoTTSScheduledRef.current) return
    autoTTSScheduledRef.current = true
    Promise.resolve().then(async () => {
      autoTTSScheduledRef.current = false
      const ids = Array.from(autoTTSBatchRef.current)
      autoTTSBatchRef.current.clear()
      if (!ids.length) return
      try {
        await api.post('/tts/queue/enqueue', { subtitle_ids: ids, priority: 'normal' })
      } catch (err) {
        console.error('[AutoTTS] enqueue failed:', err)
      }
    })
  }, [])

  // Custom event — các component khác (CharSidebar, SubtitleList drop) trigger gán
  // có thể dispatch event 'subs_assigned' với detail = list ids
  useEffect(() => {
    const onAssigned = (e: Event) => {
      const ids = (e as CustomEvent).detail?.subtitle_ids || []
      triggerAutoTTS(ids)
    }
    window.addEventListener('subs_assigned', onAssigned)
    return () => window.removeEventListener('subs_assigned', onAssigned)
  }, [triggerAutoTTS])

  // ─── Insert sub tại playhead ────────────────────────────────────────────
  const [inserting, setInserting] = useState(false)

  const insertSubAtPlayhead = useCallback(async () => {
    if (!project || inserting) return
    const currentTime = usePlayTimeStore.getState().playTime
    setInserting(true)
    try {
      const res = await api.post(`/subtitles/project/${project.id}/insert`, {
        start_time: currentTime,
      })
      const newSub = res.data
      // Reload toàn bộ subtitles vì index đã re-number
      const allRes = await api.get(`/subtitles/project/${project.id}`)
      useStore.getState().setSubtitles(allRes.data)
      // Focus vào sub mới
      useStore.getState().setActiveSubId(newSub.id)
    } catch (err) {
      console.error('[insertSub] failed:', err)
    } finally {
      setInserting(false)
    }
  }, [project, inserting])

  const [chapters, setChapters] = useState<any[]>([])
  const reloadChapters = useCallback(async () => {
    try {
      const r = await api.get(`/chapters/project/${projectId}`)
      setChapters(r.data)
    } catch {}
  }, [projectId])

  useEffect(() => { reloadChapters() }, [reloadChapters])

  // Listen event chapters changed (từ ChaptersModal hoặc ChapterSelector)
  useEffect(() => {
    const onChange = () => reloadChapters()
    window.addEventListener('chapters_changed', onChange)
    return () => window.removeEventListener('chapters_changed', onChange)
  }, [reloadChapters])

  // Toggle collapse 1 đoạn
  const handleToggleChapter = useCallback(async (chapterId: number) => {
    const ch = chapters.find(c => c.id === chapterId)
    if (!ch) return
    const newCollapsed = ch.collapsed ? 0 : 1
    // Optimistic update local
    setChapters(prev => prev.map(c => c.id === chapterId ? { ...c, collapsed: newCollapsed } : c))
    try {
      await api.patch(`/chapters/${chapterId}`, { collapsed: newCollapsed })
    } catch {
      // Rollback nếu lỗi
      setChapters(prev => prev.map(c => c.id === chapterId ? { ...c, collapsed: ch.collapsed } : c))
    }
  }, [chapters])

  // Khi user click chuyển chapter (từ modal stats): expand chapter đó nếu đang collapsed
  useEffect(() => {
    const onJump = (e: Event) => {
      const chapterId = (e as CustomEvent).detail?.chapter_id
      if (!chapterId) return
      const ch = chapters.find(c => c.id === chapterId)
      if (ch && ch.collapsed) {
        handleToggleChapter(chapterId)
      }
    }
    window.addEventListener('chapter_jump', onJump)
    return () => window.removeEventListener('chapter_jump', onJump)
  }, [chapters, handleToggleChapter])
  const [modelStatus, setModelStatus] = useState<'unknown'|'loaded'|'loading'|'unloaded'>('unknown')

  // Poll model status
  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch('/api/model/status')
        const d = await res.json()
        setModelStatus(d.loading ? 'loading' : d.loaded ? 'loaded' : 'unloaded')
      } catch { setModelStatus('unknown') }
    }
    check()
    const id = setInterval(check, 5000)
    return () => clearInterval(id)
  }, [])

  const toggleModel = async () => {
    if (modelStatus === 'loading') return
    if (modelStatus === 'loaded') {
      await fetch('/api/model/unload', { method: 'POST' })
      setModelStatus('unloaded')
    } else {
      setModelStatus('loading')
      await fetch('/api/model/load', { method: 'POST' })
    }
  }

  const [overlapMinCount, setOverlapMinCount] = useState(2)
  const [overlapMinSec, setOverlapMinSec] = useState(0.01)
  const [overlapIdx, setOverlapIdx] = useState(0)
  const [uploading, setUploading] = useState(false)
  const [uploadMsg, setUploadMsg] = useState('')
  const [uploadPct, setUploadPct] = useState(-1)

  const [col2Width, setCol2Width] = useState(1000)
  const hDragRef = useRef<{ startX: number; startW: number } | null>(null)
  const [videoHeight, setVideoHeight] = useState<number | null>(null)
  const vDragRef = useRef<{ startY: number; startH: number } | null>(null)
  const col2Ref = useRef<HTMLDivElement>(null)

  useProjectWS(projectId)
  useEffect(() => { loadProject(projectId) }, [projectId])

  // Khi subtitles đã load xong, tự scroll đến chapter đang làm dở (current_chapter_id)
  // hoặc chapter pending đầu tiên
  const didAutoJumpRef = useRef(false)
  useEffect(() => {
    if (didAutoJumpRef.current) return
    if (!project || !subtitles.length) return
    didAutoJumpRef.current = true

    // Async load chapters và jump
    ;(async () => {
      try {
        const r = await api.get(`/chapters/project/${projectId}`)
        const chapters: any[] = r.data
        if (!chapters.length) return
        const target =
          chapters.find(c => c.id === project.current_chapter_id) ||
          chapters.find(c => c.status === 'in_progress') ||
          chapters.find(c => c.status === 'pending')
        if (!target) return
        const sub = subtitles.find(s => s.index === target.start_sub_index)
        if (sub) setActiveSubId(sub.id)
      } catch {}
    })()
  }, [project?.id, subtitles.length, projectId])

  useEffect(() => {
    const onUpload = (e: any) => {
      const { status, msg, pct } = e.detail
      setUploadMsg(msg)
      if (pct !== undefined) setUploadPct(pct)
      if (status === 'done') {
        setUploading(false)
        setUploadPct(-1)
        loadProject(projectId)
        setTimeout(() => setUploadMsg(''), 3000)
      }
    }
    window.addEventListener('video_upload', onUpload)
    return () => window.removeEventListener('video_upload', onUpload)
  }, [projectId])

  // Forward WS auto-assign events từ useProjectWS → AutoAssignPanel
  useEffect(() => {
    const onWSMsg = (e: any) => {
      const msg = e.detail
      if (msg.type === 'auto_assign_progress') {
        window.dispatchEvent(new CustomEvent('aa_progress', { detail: { pct: msg.pct, step: msg.step } }))
      } else if (msg.type === 'auto_assign_done') {
        window.dispatchEvent(new CustomEvent('aa_done', { detail: msg }))
      } else if (msg.type === 'auto_assign_error') {
        window.dispatchEvent(new CustomEvent('aa_error', { detail: msg }))
      }
    }
    window.addEventListener('ws_message', onWSMsg)
    return () => window.removeEventListener('ws_message', onWSMsg)
  }, [])

  // Seek video từ AutoAssignPanel (click sample text)
  useEffect(() => {
    const onSeek = (e: any) => {
      const video = document.querySelector('video') as HTMLVideoElement | null
      if (video) video.currentTime = e.detail
    }
    window.addEventListener('seek_video', onSeek)
    return () => window.removeEventListener('seek_video', onSeek)
  }, [])

  const onHDividerDown = (e: React.MouseEvent) => {
    e.preventDefault()
    hDragRef.current = { startX: e.clientX, startW: col2Width }
    const onMove = (ev: MouseEvent) => {
      if (!hDragRef.current) return
      setCol2Width(Math.max(280, Math.min(1400, hDragRef.current.startW + ev.clientX - hDragRef.current.startX)))
    }
    const onUp = () => { hDragRef.current = null; document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  const onVDividerDown = (e: React.MouseEvent) => {
    e.preventDefault()
    const col2 = col2Ref.current; if (!col2) return
    const currentVideoH = videoHeight ?? col2.clientHeight * 0.6
    vDragRef.current = { startY: e.clientY, startH: currentVideoH }
    const onMove = (ev: MouseEvent) => {
      if (!vDragRef.current || !col2Ref.current) return
      const totalH = col2Ref.current.clientHeight
      const newH = vDragRef.current.startH + ev.clientY - vDragRef.current.startY
      setVideoHeight(Math.max(120, Math.min(totalH - 200, newH)))
    }
    const onUp = () => { vDragRef.current = null; document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement).tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return
      // Bỏ qua nếu đang ở chế độ recording shortcut (data-recording-shortcut)
      if (document.querySelector('[data-recording-shortcut="1"]')) return

      if (e.code === 'ArrowDown') {
        e.preventDefault()
        const { subtitles: subs, activeSubId: cur } = useStore.getState()
        const idx = subs.findIndex(s => s.id === cur)
        if (idx < subs.length - 1) setActiveSubId(subs[idx + 1].id)
      }
      if (e.code === 'ArrowUp') {
        e.preventDefault()
        const { subtitles: subs, activeSubId: cur } = useStore.getState()
        const idx = subs.findIndex(s => s.id === cur)
        if (idx > 0) setActiveSubId(subs[idx - 1].id)
      }

      // Phím N: tạo sub mới tại vị trí playhead
      if (e.key === 'n' || e.key === 'N') {
        e.preventDefault()
        insertSubAtPlayhead()
        return
      }

      // Match phím tắt với character — dùng shortcut_key thay vì index 1-9
      // Bỏ qua Ctrl+T (handler riêng)
      if (e.ctrlKey && e.key === 't') return
      const shortcut = parseShortcutFromEvent(e)
      if (shortcut) {
        const char = characters.find(c => c.shortcut_key === shortcut)
        if (char) {
          e.preventDefault()
          const { selectedIds: selIds } = useStore.getState()
          const ids = selIds.size > 0 ? Array.from(selIds) : (activeSubId ? [activeSubId] : [])
          if (ids.length > 0) {
            api.post('/subtitles/bulk-assign', { subtitle_ids: ids, character_id: char.id })
            ids.forEach(id => updateSubtitle(id, { character_id: char.id, character: char }))
            triggerAutoTTS(ids)
          }
        }
      }

      if (e.ctrlKey && e.key === 't' && activeSubId) {
        e.preventDefault()
        const sub = subtitles.find(s => s.id === activeSubId)
        if (sub) {
          api.post('/tts/generate', { subtitle_id: sub.id })
            .then(res => updateSubtitle(sub.id, { tts_done: true, audio_path: res.data.audio_path }))
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [subtitles, activeSubId, characters, insertSubAtPlayhead])

  const swapCharacter = async () => {
    if (!swapFrom || !swapTo || swapFrom === swapTo) return
    setSwapping(true)
    try {
      const ids = subtitles.filter(s => s.character_id === swapFrom).map(s => s.id)
      if (!ids.length) { alert('Không có phụ đề nào của nhân vật này'); return }
      const charTo = characters.find(c => c.id === swapTo)
      await api.post('/subtitles/bulk-assign', { subtitle_ids: ids, character_id: swapTo })
      ids.forEach(id => updateSubtitle(id, { character_id: swapTo, character: charTo }))
      triggerAutoTTS(ids)
      setSwapFrom(null); setSwapTo(null)
    } finally { setSwapping(false) }
  }

  const uploadVideo = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return
    setUploading(true)
    const form = new FormData(); form.append('file', file)
    await api.post(`/projects/${projectId}/upload-video`, form)
    await loadProject(projectId); setUploading(false)
  }

  const importSRT = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]; if (!file) return
    const form = new FormData(); form.append('file', file)
    await api.post(`/projects/${projectId}/import-srt`, form)
    await loadProject(projectId)
  }

  // Tính overlap chains — chuỗi audio liên tiếp chồng nhau
  const overlapGroups = useMemo(() => {
    const withAudio = subtitles.filter(s => s.tts_done && s.audio_path)
    if (!withAudio.length) return []

    const sorted = [...withAudio].sort((a, b) =>
      (a.start_time + (a.audio_offset||0)) - (b.start_time + (b.audio_offset||0))
    )

    const getStart = (s: any) => s.start_time + (s.audio_offset || 0)
    const getEnd   = (s: any) => getStart(s) + (s.wav_duration ?? (s.end_time - s.start_time))

    // PERF: track chainMaxEnd inline thay vì Math.max(...chain.map(...)) mỗi vòng
    const chains: number[][] = []
    let currentChain: any[] = []
    let chainMaxEnd = 0

    for (let i = 0; i < sorted.length; i++) {
      const cur = sorted[i]
      if (currentChain.length === 0) {
        currentChain = [cur]
        chainMaxEnd = getEnd(cur)
        continue
      }
      const nextStart = getStart(cur)

      if (nextStart < chainMaxEnd - overlapMinSec) {
        currentChain.push(cur)
        const ce = getEnd(cur)
        if (ce > chainMaxEnd) chainMaxEnd = ce
      } else {
        if (currentChain.length >= overlapMinCount) {
          chains.push(currentChain.map(s => s.id))
        }
        currentChain = [cur]
        chainMaxEnd = getEnd(cur)
      }
    }
    if (currentChain.length >= overlapMinCount) {
      chains.push(currentChain.map(s => s.id))
    }

    return chains
  }, [subtitles, overlapMinCount, overlapMinSec])

  const overlapSubIds = useMemo(() => new Set(overlapGroups.flat()), [overlapGroups])

  // PERF: memo visibleCount — trước đây chạy filter trên 6000 items mỗi render
  const visibleCount = useMemo(() => {
    const f = filter.toLowerCase()
    let n = 0
    for (const s of subtitles) {
      if (f && !s.text.toLowerCase().includes(f)) continue
      if (filterNoChar && s.character_id) continue
      if (filterNoTTS && s.tts_done) continue
      if (filterOverlap && !overlapSubIds.has(s.id)) continue
      if (filterCharId !== null && s.character_id !== filterCharId) continue
      n++
    }
    return n
  }, [subtitles, filter, filterNoChar, filterNoTTS, filterOverlap, overlapSubIds, filterCharId])

  // PERF: memo done count
  const done = useMemo(() => {
    let n = 0
    for (const s of subtitles) if (s.tts_done) n++
    return n
  }, [subtitles])

  return (
    <div className="flex flex-col h-screen bg-zinc-100 dark:bg-zinc-950 overflow-hidden text-zinc-900 dark:text-zinc-100">

      {/* Upload progress bar */}
      {uploadPct >= 0 && (
        <div className="flex-shrink-0" style={{ height: 3, background: '#E5E7EB' }}>
          <div style={{ height: '100%', width: `${uploadPct}%`, background: '#3B82F6', transition: 'width 0.3s' }} />
        </div>
      )}

      <header className="flex items-center gap-2 px-3 h-12 bg-white dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800 flex-shrink-0 z-10">
        <button onClick={() => setSidebarVisible(v => !v)} title="Ẩn/hiện sidebar"
          className={`w-8 h-8 rounded-lg flex items-center justify-center transition-colors ${sidebarVisible ? 'bg-blue-50 text-blue-600 dark:bg-blue-950 dark:text-blue-400' : 'text-zinc-400 hover:bg-zinc-100 dark:hover:bg-zinc-800'}`}>
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
            <rect x="2" y="3" width="4" height="10" rx="1" fill="currentColor" opacity="0.8"/>
            <rect x="7.5" y="4" width="6.5" height="1.5" rx=".75" fill="currentColor"/>
            <rect x="7.5" y="7.25" width="6.5" height="1.5" rx=".75" fill="currentColor"/>
            <rect x="7.5" y="10.5" width="6.5" height="1.5" rx=".75" fill="currentColor"/>
          </svg>
        </button>
        <div className="h-5 w-px bg-zinc-200 dark:bg-zinc-700" />
        <button onClick={onBack} className="btn text-[13px]">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9 2L4 7l5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
          Trang chủ
        </button>
        <div className="h-5 w-px bg-zinc-200 dark:bg-zinc-700" />
        <div className="flex items-center gap-2 flex-1 min-w-0">
          <span className="text-[13px] font-semibold truncate">{project?.name || '...'}</span>
          {project && <span className="text-[11px] text-zinc-300 bg-zinc-100 dark:bg-zinc-800 px-1.5 py-0.5 rounded font-mono flex-shrink-0">#{project.id}</span>}
          <span className="text-[12px] text-zinc-400 flex-shrink-0">{subtitles.length} dòng</span>
          <span className={`text-[12px] flex-shrink-0 ${done === subtitles.length && done > 0 ? 'text-emerald-500' : 'text-zinc-400'}`}>
            · {done}/{subtitles.length} TTS
          </span>
        </div>
        <label className="btn cursor-pointer">
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M6.5 1v8M3 5.5l3.5 3.5L10 5.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M1 10h11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
          {uploading ? (uploadPct >= 0 ? `${uploadPct}%` : 'Uploading...') : 'Video'}
          <input type="file" accept="video/*" onChange={uploadVideo} className="hidden" />
        </label>
        <label className="btn cursor-pointer">
          <svg width="13" height="13" viewBox="0 0 13 13" fill="none"><path d="M6.5 1v8M3 5.5l3.5 3.5L10 5.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M1 10h11" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
          SRT
          <input type="file" accept=".srt,.SRT" onChange={importSRT} className="hidden" />
        </label>
        {/* Model load/unload */}
        <button onClick={toggleModel} disabled={modelStatus==='loading'}
          title={modelStatus==='loaded' ? 'Click để Unload Model (giải phóng VRAM)' : 'Click để Load Model (cần để dùng TTS)'}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[12px] font-medium transition-colors flex-shrink-0 disabled:opacity-60
            ${modelStatus==='loaded'
              ? 'border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 hover:bg-red-50 hover:border-red-300 hover:text-red-500'
              : modelStatus==='loading'
              ? 'border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40 text-amber-600'
              : 'border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-zinc-500 hover:bg-emerald-50 hover:border-emerald-300 hover:text-emerald-600'
            }`}>
          {modelStatus==='loaded' && <><span className="w-1.5 h-1.5 rounded-full bg-emerald-500"/>Model ON</>}
          {modelStatus==='loading' && <><div className="w-3 h-3 rounded-full border-2 border-amber-400 border-t-transparent animate-spin"/>Loading...</>}
          {(modelStatus==='unloaded'||modelStatus==='unknown') && <><span className="w-1.5 h-1.5 rounded-full bg-zinc-400"/>Model OFF</>}
        </button>
        <button onClick={() => setShowAutoAssign(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-purple-300 dark:border-purple-800 bg-purple-50 dark:bg-purple-950/40 text-purple-700 dark:text-purple-400 text-[12px] font-medium hover:bg-purple-100 dark:hover:bg-purple-950 transition-colors flex-shrink-0">
          <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
            <circle cx="6" cy="6" r="5" stroke="currentColor" strokeWidth="1.2"/>
            <path d="M4 6l1.5 1.5L8 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          AI Gán NV
        </button>
      </header>

      <div className="flex flex-1 overflow-hidden">

        <div className="flex-shrink-0 overflow-hidden transition-all duration-400 ease-in-out"
          style={{ width: sidebarVisible ? 240 : 0 }}>
          <CharSidebar visible={sidebarVisible} />
        </div>

        {/* Col 2: Video + AudioList (resize) + EditPanel */}
        <div ref={col2Ref}
          className="flex-shrink-0 flex flex-col border-r border-zinc-200 dark:border-zinc-800 overflow-hidden"
          style={{ width: col2Width }}>

          {/* Video — chiều cao cố định hoặc flex */}
          <div style={{
            height: videoHeight ?? undefined,
            flex: videoHeight ? 'none' : '1 1 0',
            minHeight: 120,
            display: 'flex',
            flexDirection: 'column',
            overflow: 'hidden'
          }}>
            <VideoPlayer />
          </div>

          {/* AudioList — tự quản lý height, có resize handle ở trên */}
          <AudioList />

          {/* Divider kéo video/editpanel */}
          <div onMouseDown={onVDividerDown}
            className="h-1.5 flex-shrink-0 cursor-row-resize bg-zinc-200 dark:bg-zinc-800 hover:bg-blue-400 dark:hover:bg-blue-600 transition-colors relative"
            title="Kéo để thay đổi chiều cao video">
            <div className="absolute inset-0 flex items-center justify-center pointer-events-none">
              <div className="flex gap-0.5">
                {[0,1,2].map(i => <div key={i} className="w-4 h-0.5 rounded-full bg-zinc-400 dark:bg-zinc-600" />)}
              </div>
            </div>
          </div>

          {/* EditPanel */}
          <div style={{ flex: '0 0 auto', minHeight: 120, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}
            className="bg-white dark:bg-zinc-900">
            <div className="flex-1 overflow-y-auto min-h-0">
              <EditPanel />
            </div>
          </div>
        </div>

        {/* Divider ngang col2/col3 */}
        <div onMouseDown={onHDividerDown}
          className="w-1.5 flex-shrink-0 cursor-col-resize bg-zinc-200 dark:bg-zinc-800 hover:bg-blue-400 dark:hover:bg-blue-600 transition-colors relative">
          <div className="absolute inset-y-0 -left-1 -right-1" />
        </div>

        {/* Col 3: Subtitle list */}
        <div className="flex-1 flex flex-col overflow-hidden bg-white dark:bg-zinc-900 min-w-0">
          <div className="flex items-center gap-2 px-3 py-2 border-b border-zinc-100 dark:border-zinc-800 flex-shrink-0">
            <ChapterSelector projectId={projectId} onOpenManage={() => setShowChapters(true)} />

            {/* Nút tạo sub tại playhead */}
            <button
              onClick={insertSubAtPlayhead}
              disabled={inserting}
              title="Tạo phụ đề tại vị trí playhead (phím N)"
              className="flex-shrink-0 w-8 h-8 rounded-lg border border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 disabled:opacity-40 disabled:cursor-not-allowed flex items-center justify-center font-bold text-[16px] transition-all">
              {inserting ? (
                <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeOpacity="0.25"/>
                  <path d="M22 12a10 10 0 0 0-10-10" stroke="currentColor" strokeWidth="3" strokeLinecap="round"/>
                </svg>
              ) : '+'}
            </button>

            <div className="relative flex-1">
              <svg className="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-400" width="13" height="13" viewBox="0 0 13 13" fill="none">
                <circle cx="5.5" cy="5.5" r="4" stroke="currentColor" strokeWidth="1.5"/>
                <path d="M9 9l2.5 2.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
              </svg>
              <input placeholder="Tìm phụ đề..." value={filter} onChange={e => setFilter(e.target.value)}
                className="input w-full pl-8 text-[13px]" />
            </div>
            <button onClick={() => setFilterNoChar(v => !v)}
              className={`flex-shrink-0 px-2.5 py-1.5 text-[12px] rounded-lg border transition-all font-medium ${filterNoChar ? 'bg-amber-50 text-amber-700 border-amber-300' : 'btn'}`}>
              ? char
            </button>
            <button onClick={() => setFilterNoTTS(v => !v)}
              className={`flex-shrink-0 px-2.5 py-1.5 text-[12px] rounded-lg border transition-all font-medium ${filterNoTTS ? 'bg-blue-50 text-blue-700 border-blue-300' : 'btn'}`}>
              no TTS
            </button>

            {/* Overlap navigator */}
            <div className="flex items-center gap-1 flex-shrink-0">
              <button onClick={() => { setFilterOverlap(v => !v); setOverlapIdx(0) }}
                className={`px-2.5 py-1.5 text-[12px] rounded-lg border transition-all font-medium ${filterOverlap ? 'bg-red-50 text-red-700 border-red-300 dark:bg-red-950 dark:text-red-400 dark:border-red-800' : 'btn'}`}>
                ⚠{overlapGroups.length > 0 ? ` ${overlapGroups.length}` : ''}
              </button>

              {/* Auto Fix Overlap button */}
              <button onClick={() => setShowAutoFix(true)}
                disabled={overlapGroups.length === 0}
                title={overlapGroups.length > 0 ? `Tự động fix ${overlapGroups.length} chuỗi đè` : 'Không có chuỗi đè'}
                className="px-2.5 py-1.5 text-[12px] rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 hover:bg-amber-100 dark:hover:bg-amber-950 transition-all font-medium disabled:opacity-40 disabled:cursor-not-allowed">
                ⚡ Auto fix
              </button>

              {/* Auto TTS toggle */}
              <button onClick={() => setAutoTTS(!autoTTS)}
                title={autoTTS ? 'Auto TTS đang BẬT — gán nhân vật xong tự tạo TTS' : 'Auto TTS đang TẮT — bấm để bật'}
                className={`px-2.5 py-1.5 text-[12px] rounded-lg border font-medium transition-all flex items-center gap-1 ${
                  autoTTS
                    ? 'border-emerald-400 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 shadow-sm'
                    : 'border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100'
                }`}>
                <span>{autoTTS ? '🟢' : '⚪'}</span>
                <span>Auto TTS</span>
              </button>
              {filterOverlap && (
                <>
                  {/* Min count input */}
                  <input type="number" min={2} max={10} value={overlapMinCount}
                    onChange={e => { setOverlapMinCount(parseInt(e.target.value)||2); setOverlapIdx(0) }}
                    className="input w-10 text-[12px] text-center px-1 py-1"
                    title="Số audio chồng tối thiểu" />
                  {/* Min sec input */}
                  <input type="number" min={0} max={5} step={0.1} value={overlapMinSec}
                    onChange={e => { setOverlapMinSec(parseFloat(e.target.value)||0.01); setOverlapIdx(0) }}
                    className="input w-14 text-[12px] text-center px-1 py-1"
                    title="Chồng tối thiểu bao nhiêu giây" />
                  <span className="text-[10px] text-zinc-400">s</span>
                  {overlapGroups.length > 0 ? (
                    <>
                      <button onClick={() => {
                        const idx = Math.max(0, overlapIdx - 1)
                        setOverlapIdx(idx)
                        const sub = subtitles.find(s => s.id === overlapGroups[idx]?.[0])
                        if (sub) setActiveSubId(sub.id)
                      }} disabled={overlapIdx === 0}
                        className="w-6 h-7 rounded border border-zinc-200 text-zinc-500 hover:bg-zinc-100 disabled:opacity-30 text-[11px] flex items-center justify-center">‹</button>
                      <span className="text-[11px] text-zinc-500 tabular-nums whitespace-nowrap">
                        {overlapIdx + 1}/{overlapGroups.length}
                      </span>
                      <button onClick={() => {
                        const idx = Math.min(overlapGroups.length - 1, overlapIdx + 1)
                        setOverlapIdx(idx)
                        const sub = subtitles.find(s => s.id === overlapGroups[idx]?.[0])
                        if (sub) setActiveSubId(sub.id)
                      }} disabled={overlapIdx === overlapGroups.length - 1}
                        className="w-6 h-7 rounded border border-zinc-200 text-zinc-500 hover:bg-zinc-100 disabled:opacity-30 text-[11px] flex items-center justify-center">›</button>
                    </>
                  ) : (
                    <span className="text-[11px] text-zinc-400">không có</span>
                  )}
                </>
              )}
            </div>

            {/* Chọn tất cả visible */}
            <button
              onClick={() => {
                const { subtitles: subs } = useStore.getState()
                const visibleIds = subs.filter(s => {
                  if (filter && !s.text.toLowerCase().includes(filter.toLowerCase())) return false
                  if (filterNoChar && s.character_id) return false
                  if (filterNoTTS && s.tts_done) return false
                  if (filterOverlap && !overlapSubIds.has(s.id)) return false
                  if (filterCharId !== null && s.character_id !== filterCharId) return false
                  return true
                }).map(s => s.id)
                const { selectedIds } = useStore.getState()
                // Toggle: nếu đã chọn hết thì bỏ chọn, chưa thì chọn tất cả
                const allSelected = visibleIds.every(id => selectedIds.has(id))
                if (allSelected) {
                  useStore.setState({ selectedIds: new Set() })
                } else {
                  useStore.setState({ selectedIds: new Set(visibleIds) })
                }
              }}
              className="flex-shrink-0 px-2 py-1.5 text-[11px] rounded-lg border border-zinc-200 dark:border-zinc-700 text-zinc-500 hover:bg-zinc-100 dark:hover:bg-zinc-800 transition-colors font-medium"
              title="Chọn/bỏ chọn tất cả đang hiển thị">
              ☑
            </button>
            <span className="text-[12px] text-zinc-400 tabular-nums flex-shrink-0 min-w-[24px] text-right">{visibleCount}</span>
          </div>

          {/* Character strip */}
          {characters.length > 0 && (
            <div className="flex flex-col border-b border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 flex-shrink-0">
              {/* Row 1: Gán nhanh + Filter theo nhân vật */}
              <div className="flex items-center gap-1.5 px-3 py-1.5 overflow-x-auto">
                <span className="text-[11px] text-zinc-400 flex-shrink-0">Gán:</span>
                {characters.map(c => (
                  <button key={c.id}
                    onClick={() => {
                      const { selectedIds, updateSubtitle: upd } = useStore.getState()
                      if (!selectedIds.size) return
                      const ids = Array.from(selectedIds)
                      ids.forEach(id => { api.patch(`/subtitles/${id}`, { character_id: c.id }); upd(id, { character_id: c.id, character: c }) })
                      triggerAutoTTS(ids)
                    }}
                    title={c.shortcut_key ? `Phím tắt: ${formatShortcut(c.shortcut_key)}` : 'Chưa đặt phím tắt'}
                    className="flex-shrink-0 px-2.5 py-0.5 rounded-full text-[12px] font-medium border transition-all hover:opacity-90 active:scale-95 inline-flex items-center gap-1"
                    style={{ background: c.color + '18', color: c.color, borderColor: c.color + '40' }}>
                    {c.shortcut_key && (
                      <span className="text-[10px] font-mono opacity-70">{formatShortcut(c.shortcut_key)}</span>
                    )}
                    {c.name}
                  </button>
                ))}
                <div className="w-px h-4 bg-zinc-200 dark:bg-zinc-700 flex-shrink-0 mx-1" />
                {/* Filter theo nhân vật */}
                <span className="text-[11px] text-zinc-400 flex-shrink-0">Lọc:</span>
                <button onClick={() => setFilterCharId(null)}
                  className={`flex-shrink-0 px-2 py-0.5 rounded-full text-[11px] font-medium border transition-all ${filterCharId === null ? 'bg-zinc-200 dark:bg-zinc-700 text-zinc-700 dark:text-zinc-200 border-zinc-300' : 'btn'}`}>
                  Tất cả
                </button>
                {characters.map(c => (
                  <button key={c.id} onClick={() => setFilterCharId(filterCharId === c.id ? null : c.id)}
                    className="flex-shrink-0 px-2 py-0.5 rounded-full text-[11px] font-medium border transition-all"
                    style={{
                      background: filterCharId === c.id ? c.color : c.color + '12',
                      color: filterCharId === c.id ? '#fff' : c.color,
                      borderColor: c.color + '60',
                    }}>
                    {c.name}
                  </button>
                ))}
              </div>
              {/* Row 2: Đổi nhân vật hàng loạt */}
              <div className="flex items-center gap-1.5 px-3 py-1 overflow-x-auto">
                <span className="text-[11px] text-zinc-400 flex-shrink-0">Đổi:</span>
                <select value={swapFrom ?? ''} onChange={e => setSwapFrom(e.target.value ? parseInt(e.target.value) : null)}
                  className="input text-[11px] py-0.5 px-2 h-6">
                  <option value="">-- Từ nhân vật --</option>
                  {characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                <span className="text-[11px] text-zinc-400">→</span>
                <select value={swapTo ?? ''} onChange={e => setSwapTo(e.target.value ? parseInt(e.target.value) : null)}
                  className="input text-[11px] py-0.5 px-2 h-6">
                  <option value="">-- Sang nhân vật --</option>
                  {characters.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                </select>
                <button onClick={swapCharacter} disabled={!swapFrom || !swapTo || swapFrom === swapTo || swapping}
                  className="flex-shrink-0 px-2.5 py-0.5 rounded-lg text-[11px] font-medium bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-40 transition-colors">
                  {swapping ? '...' : 'Đổi'}
                </button>
              </div>
            </div>
          )}

          <SubtitleList
            filter={filter}
            filterNoChar={filterNoChar}
            filterNoTTS={filterNoTTS}
            overlapSubIds={filterOverlap ? overlapSubIds : undefined}
            filterCharId={filterCharId}
            chapters={chapters}
            onToggleChapter={handleToggleChapter}
          />
        </div>

        <DetailPanel />
      </div>

      {showAutoAssign && (
        <AutoAssignPanel
          projectId={projectId}
          onClose={() => setShowAutoAssign(false)}
        />
      )}

      {showAutoFix && (
        <AutoFixOverlapModal
          projectId={projectId}
          onClose={() => setShowAutoFix(false)}
        />
      )}

      {showChapters && (
        <ChaptersModal
          projectId={projectId}
          onClose={() => setShowChapters(false)}
          onChaptersChanged={() => window.dispatchEvent(new Event('chapters_changed'))}
        />
      )}

      {/* Sticky toast tiến trình bulk TTS */}
      <BulkTTSProgress projectId={projectId} />
    </div>
  )
}