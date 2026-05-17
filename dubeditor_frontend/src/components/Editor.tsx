import React, { useEffect, useState, useRef, useMemo, useCallback } from 'react'
import useStore, { usePlayTimeStore, filterVisible } from '../store'
import api from '../api'
import CharSidebar from './CharSidebar'
import SubtitleList from './SubtitleList'
import EditPanel from './EditPanel'
import AudioList from './AudioList'
import VideoPlayer from './VideoPlayer'
import DetailPanel from './DetailPanel'
import { useProjectWS } from '../hooks/useProjectWS'
import { parseShortcutFromEvent, formatShortcut } from '../utils/shortcuts'
import AutoFixOverlapModal from './AutoFixOverlapModal'
import BulkTTSProgress from './BulkTTSProgress'
import ChapterSelector from './ChapterSelector'
import ChaptersModal from './ChaptersModal'
import ChapterFilterDropdown from './ChapterFilterDropdown'
import CharacterFilterDropdown from './CharacterFilterDropdown'
import SwapCharacterModal from './SwapCharacterModal'
import ConfirmModal from './ConfirmModal'
import { LicenseChip, LicenseStatus } from './LicenseGate'

interface Props { projectId: number; onBack: () => void; onTranslate: () => void }

export default function Editor({ projectId, onBack, onTranslate }: Props) {
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
  // v3.4: filter state đã chuyển sang Zustand store. Đọc state + setters trực tiếp.
  const filter = useStore(s => s.filterText)
  const setFilter = useStore(s => s.setFilterText)
  const filterNoChar = useStore(s => s.filterNoChar)
  const setFilterNoChar = useStore(s => s.setFilterNoChar)
  const filterNoTTS = useStore(s => s.filterNoTTS)
  const setFilterNoTTS = useStore(s => s.setFilterNoTTS)
  const filterOverlap = useStore(s => s.filterOverlap)
  const setFilterOverlap = useStore(s => s.setFilterOverlap)
  const filterCharIds = useStore(s => s.filterCharIds)
  const setFilterCharIds = useStore(s => s.setFilterCharIds)
  const filterChapterIds = useStore(s => s.filterChapterIds)
  const setFilterChapterIds = useStore(s => s.setFilterChapterIds)
  const setChaptersInStore = useStore(s => s.setChapters)
  const setOverlapSubIdsInStore = useStore(s => s.setOverlapSubIds)
  const [showSwapModal, setShowSwapModal] = useState(false)
  const [swapping, setSwapping]           = useState(false)
  const [showAutoFix, setShowAutoFix] = useState(false)
  const [showChapters, setShowChapters] = useState(false)

  // Dialog xác nhận khi user import SRT không phải tiếng Trung
  // → hỏi có muốn import như SRT tiếng Việt (đã dịch sẵn) không
  const [nonChineseDialog, setNonChineseDialog] = useState<null | {
    file: File
    cjkRatio: number
    encoding: string
  }>(null)
  const [importingVi, setImportingVi] = useState(false)

  // License chip — fetch status
  const [licenseStatus, setLicenseStatus] = useState<LicenseStatus | null>(null)
  const fetchLicenseStatus = useCallback(async () => {
    try {
      const r = await api.get('/license/status')
      setLicenseStatus(r.data)
    } catch {}
  }, [])
  useEffect(() => { fetchLicenseStatus() }, [fetchLicenseStatus])
  // Re-fetch sau khi deactivate (LicenseChip emit event)
  const handleLicenseChange = useCallback(() => {
    window.location.reload()
  }, [])

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
      // v3.4: sync vào store để filter helpers tính range được
      setChaptersInStore(r.data || [])
    } catch {}
  }, [projectId, setChaptersInStore])

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

  // ── Emotion voice toggle (v3) ────────────────────────────────────────────
  // OFF: tất cả TTS dùng mode "normal"
  // ON:  TTS dùng mode theo emotion (qua emotion_to_mode), có thể override per-line
  const [emotionVoiceOn, setEmotionVoiceOn] = useState(false)
  useEffect(() => {
    if (project && typeof project.use_emotion_voice === 'boolean') {
      setEmotionVoiceOn(project.use_emotion_voice)
    }
  }, [project?.id, project?.use_emotion_voice])

  const toggleEmotionVoice = async () => {
    if (!project) return
    const next = !emotionVoiceOn
    setEmotionVoiceOn(next)   // optimistic
    try {
      await api.patch(`/projects/${project.id}`, { use_emotion_voice: next })
    } catch (e: any) {
      setEmotionVoiceOn(!next)   // revert
      alert('Lưu thất bại: ' + (e?.message || ''))
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

  const swapCharacter = async (fromId: number, toId: number) => {
    if (!fromId || !toId || fromId === toId) return
    setSwapping(true)
    try {
      // v3.4: nếu có filter đang bật → chỉ swap subs nằm trong visible
      // (đoạn đang lọc / NV đang lọc / text đang lọc). Không filter → toàn phim như cũ.
      const baseList = hasActiveFilter ? subtitles.filter(s => visibleIdsSet.has(s.id)) : subtitles
      const ids = baseList.filter(s => s.character_id === fromId).map(s => s.id)
      if (!ids.length) return
      const charTo = characters.find(c => c.id === toId)
      await api.post('/subtitles/bulk-assign', { subtitle_ids: ids, character_id: toId })
      ids.forEach(id => updateSubtitle(id, { character_id: toId, character: charTo }))
      triggerAutoTTS(ids)
      setShowSwapModal(false)
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
    try {
      const res = await api.post(`/projects/${projectId}/import-srt`, form)
      const data = res.data || {}
      if (data.detected_chinese) {
        console.log(`[Import] OK ${data.imported} dòng tiếng Trung (encoding: ${data.encoding})`)
      }
      await loadProject(projectId)
    } catch (err: any) {
      const detail = err?.response?.data?.detail
      // Backend trả error có code 'DETECTED_NON_CHINESE' → mở dialog hỏi user
      // có muốn import như SRT tiếng Việt không
      if (detail?.code === 'DETECTED_NON_CHINESE') {
        setNonChineseDialog({
          file,
          cjkRatio: detail.cjk_ratio || 0,
          encoding: detail.encoding || 'unknown',
        })
      } else {
        alert(`Import fail: ${typeof detail === 'string' ? detail : (detail?.message || err?.message || 'Unknown')}`)
      }
    } finally {
      e.target.value = ''  // reset input để có thể chọn lại cùng file
    }
  }

  // User xác nhận: import file đó như SRT tiếng Việt (đã dịch sẵn)
  const confirmImportVi = async () => {
    if (!nonChineseDialog) return
    setImportingVi(true)
    try {
      const form = new FormData(); form.append('file', nonChineseDialog.file)
      await api.post(
        `/projects/${projectId}/import-srt?lang_override=vi`,
        form,
      )
      await loadProject(projectId)
      setNonChineseDialog(null)
    } catch (err2: any) {
      alert(`Import fail: ${err2?.response?.data?.detail?.message || err2?.message || 'Unknown'}`)
    } finally {
      setImportingVi(false)
    }
  }

  // v3.4: overlapGroups TÁCH thành 2 view:
  //  - overlapGroupsAll: full project — cần cho filter checkbox "Lọc đè" + AudioList
  //  - overlapGroups: chỉ chuỗi đè TRONG đoạn đang lọc — số hiển thị ở nút Auto fix
  // Khi user lọc đoạn 9 dòng, nút "Auto fix (N)" phải show N theo đoạn đó.
  const overlapGroupsAll = useMemo(() => {
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

  const overlapSubIds = useMemo(() => new Set(overlapGroupsAll.flat()), [overlapGroupsAll])

  // Sync overlapSubIds vào store để filter helpers + checkbox "Lọc đè" dùng được
  useEffect(() => { setOverlapSubIdsInStore(overlapSubIds) }, [overlapSubIds, setOverlapSubIdsInStore])

  // v3.4: visibleIdsSet — Set id subtitle đang visible theo filter (chapter+char+text+...)
  // Dùng cho: visibleCount, nút ☑ select all, overlapGroups scoped, topbar done counter
  const visibleIdsSet = useMemo(() => {
    const f = filter.toLowerCase()
    const chapterRanges: [number, number][] = (filterChapterIds.length > 0)
      ? chapters
          .filter(c => filterChapterIds.includes(c.id))
          .map(c => [c.start_sub_index, c.end_sub_index] as [number, number])
      : []
    const ids = new Set<number>()
    for (const s of subtitles) {
      if (f && !s.text.toLowerCase().includes(f) &&
          !(s.character?.name.toLowerCase().includes(f))) continue
      if (filterNoChar && s.character_id) continue
      if (filterNoTTS && s.tts_done) continue
      if (filterOverlap && !overlapSubIds.has(s.id)) continue
      if (filterCharIds.length > 0 &&
          (!s.character_id || !filterCharIds.includes(s.character_id))) continue
      if (chapterRanges.length > 0) {
        let inAny = false
        for (const [a, b] of chapterRanges) {
          if (s.index >= a && s.index <= b) { inAny = true; break }
        }
        if (!inAny) continue
      }
      ids.add(s.id)
    }
    return ids
  }, [subtitles, filter, filterNoChar, filterNoTTS, filterOverlap, overlapSubIds, filterCharIds, filterChapterIds, chapters])

  const hasActiveFilter = !!filter || filterNoChar || filterNoTTS || filterOverlap ||
    filterCharIds.length > 0 || filterChapterIds.length > 0

  // overlapGroups giới hạn trong đoạn đang lọc — chỉ giữ chain nào TOÀN BỘ id thuộc visible
  // (an toàn: không auto-fix chuỗi đè nửa trong nửa ngoài đoạn)
  const overlapGroups = useMemo(() => {
    if (!hasActiveFilter) return overlapGroupsAll
    return overlapGroupsAll.filter(chain => chain.every(id => visibleIdsSet.has(id)))
  }, [overlapGroupsAll, visibleIdsSet, hasActiveFilter])

  // PERF: memo visibleCount — số dòng đang hiển thị theo filter
  const visibleCount = visibleIdsSet.size

  // PERF: memo done count — theo filter: nếu có lọc thì đếm trong đoạn, không lọc thì cả phim
  const done = useMemo(() => {
    if (hasActiveFilter) {
      let n = 0
      for (const s of subtitles) if (visibleIdsSet.has(s.id) && s.tts_done) n++
      return n
    }
    let n = 0
    for (const s of subtitles) if (s.tts_done) n++
    return n
  }, [subtitles, visibleIdsSet, hasActiveFilter])

  return (
    <div className="flex flex-col h-screen bg-zinc-100 dark:bg-zinc-950 overflow-hidden text-zinc-900 dark:text-zinc-100">

      {/* Upload progress bar */}
      {uploadPct >= 0 && (
        <div className="flex-shrink-0" style={{ height: 3, background: '#E5E7EB' }}>
          <div style={{ height: '100%', width: `${uploadPct}%`, background: '#3B82F6', transition: 'width 0.3s' }} />
        </div>
      )}

      <header className="flex items-center gap-2 px-3 h-12 bg-white dark:bg-zinc-900 border-b border-zinc-200 dark:border-zinc-800 flex-shrink-0 z-10 overflow-x-auto"
        style={{ scrollbarWidth: 'thin' }}>
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
          {hasActiveFilter ? (
            <>
              <span className="text-[12px] text-blue-500 flex-shrink-0" title="Đang lọc — số đếm chỉ trong đoạn đang lọc">
                {visibleCount} dòng (lọc)
              </span>
              <span className={`text-[12px] flex-shrink-0 ${done === visibleCount && done > 0 ? 'text-emerald-500' : 'text-zinc-400'}`}>
                · {done}/{visibleCount} TTS
              </span>
            </>
          ) : (
            <>
              <span className="text-[12px] text-zinc-400 flex-shrink-0">{subtitles.length} dòng</span>
              <span className={`text-[12px] flex-shrink-0 ${done === subtitles.length && done > 0 ? 'text-emerald-500' : 'text-zinc-400'}`}>
                · {done}/{subtitles.length} TTS
              </span>
            </>
          )}
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

        {/* ━━━ Filter group: Đoạn / Lọc đoạn (chỉ chapter — NV ở character strip dưới) ━━━ */}
        <div className="h-5 w-px bg-zinc-200 dark:bg-zinc-700 flex-shrink-0" />

        <ChapterSelector projectId={projectId} onOpenManage={() => setShowChapters(true)} />
        <ChapterFilterDropdown
          projectId={projectId}
          chapters={chapters}
          selectedIds={filterChapterIds}
          onChange={setFilterChapterIds}
        />

        <div className="h-5 w-px bg-zinc-200 dark:bg-zinc-700 flex-shrink-0" />

        {/* Emotion Voice toggle — v3 (3 mode: BT / Buồn / Giận)
            OFF → tất cả TTS dùng mode "Bình thường"
            ON  → TTS dùng mode theo cảm xúc của mỗi dòng (qua emotion_to_mode) */}
        <button
          onClick={toggleEmotionVoice}
          disabled={!project}
          title={emotionVoiceOn
            ? "TTS theo mode cảm xúc của từng câu (BT/Buồn/Giận). Click để tắt → tất cả dùng BT."
            : "TTS luôn dùng mode Bình thường. Click để bật theo cảm xúc câu."}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[12px] font-medium transition-colors flex-shrink-0 disabled:opacity-50
            ${emotionVoiceOn
              ? 'border-fuchsia-300 dark:border-fuchsia-700 bg-fuchsia-50 dark:bg-fuchsia-950/40 text-fuchsia-700 dark:text-fuchsia-400 hover:bg-fuchsia-100'
              : 'border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-800 text-zinc-500 hover:bg-fuchsia-50 hover:border-fuchsia-300 hover:text-fuchsia-600'
            }`}>
          <span>🎭</span>
          {emotionVoiceOn ? 'Mode cảm xúc ON' : 'Mode cảm xúc OFF'}
        </button>

        {/* Auto Fix Overlap button — số chuỗi đè theo đoạn đang lọc */}
        <button onClick={() => setShowAutoFix(true)}
          disabled={overlapGroups.length === 0}
          title={overlapGroups.length > 0
            ? `Tự động fix ${overlapGroups.length} chuỗi đè${hasActiveFilter ? ' (trong đoạn đang lọc)' : ''}`
            : 'Không có chuỗi đè'}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[12px] font-medium transition-colors flex-shrink-0 border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400 hover:bg-amber-100 dark:hover:bg-amber-950 disabled:opacity-40 disabled:cursor-not-allowed">
          <span>⚡</span>
          Auto fix{overlapGroups.length > 0 ? ` (${overlapGroups.length})` : ''}
        </button>

        {/* Auto TTS toggle */}
        <button onClick={() => setAutoTTS(!autoTTS)}
          title={autoTTS ? 'Auto TTS đang BẬT — gán nhân vật xong tự tạo TTS' : 'Auto TTS đang TẮT — bấm để bật'}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[12px] font-medium transition-colors flex-shrink-0
            ${autoTTS
              ? 'border-emerald-400 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-400 hover:bg-emerald-100 shadow-sm'
              : 'border-zinc-300 dark:border-zinc-700 bg-white dark:bg-zinc-800 text-zinc-500 dark:text-zinc-400 hover:bg-zinc-100'
            }`}>
          <span>{autoTTS ? '🟢' : '⚪'}</span>
          <span>Auto TTS {autoTTS ? 'ON' : 'OFF'}</span>
        </button>

        <button onClick={onTranslate}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-[12px] font-medium transition-colors flex-shrink-0"
          style={{ borderColor: '#7c3aed', background: 'linear-gradient(135deg,#7c3aed18,#4f46e518)', color: '#7c3aed' }}>
          <svg width="12" height="12" viewBox="0 0 14 14" fill="none">
            <path d="M1 3h6M4 1v2M2 3c0 3 2 5 4 6M7 3c0 1-.3 2.3-1 3" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
            <path d="M8 8h5M10 7v1M9 8c0 2 1.5 4 3.5 5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
          </svg>
          🌐 Dịch
        </button>

        {/* License chip — hiện số ngày còn lại */}
        {licenseStatus && (
          <LicenseChip status={licenseStatus} onChange={handleLicenseChange} />
        )}

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
            <button onClick={() => setFilterNoChar(!filterNoChar)}
              className={`flex-shrink-0 px-2.5 py-1.5 text-[12px] rounded-lg border transition-all font-medium ${filterNoChar ? 'bg-amber-50 text-amber-700 border-amber-300' : 'btn'}`}>
              ? char
            </button>
            <button onClick={() => setFilterNoTTS(!filterNoTTS)}
              className={`flex-shrink-0 px-2.5 py-1.5 text-[12px] rounded-lg border transition-all font-medium ${filterNoTTS ? 'bg-blue-50 text-blue-700 border-blue-300' : 'btn'}`}>
              no TTS
            </button>

            {/* Overlap navigator */}
            <div className="flex items-center gap-1 flex-shrink-0">
              <button onClick={() => { setFilterOverlap(!filterOverlap); setOverlapIdx(0) }}
                className={`px-2.5 py-1.5 text-[12px] rounded-lg border transition-all font-medium ${filterOverlap ? 'bg-red-50 text-red-700 border-red-300 dark:bg-red-950 dark:text-red-400 dark:border-red-800' : 'btn'}`}>
                ⚠{overlapGroups.length > 0 ? ` ${overlapGroups.length}` : ''}
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

            {/* Chọn tất cả visible — theo filter đoạn/NV/text đang lọc */}
            <button
              onClick={() => {
                const visibleIds = Array.from(visibleIdsSet)
                const { selectedIds } = useStore.getState()
                // Toggle: nếu đã chọn hết thì bỏ chọn, chưa thì chọn tất cả visible
                const allSelected = visibleIds.length > 0 && visibleIds.every(id => selectedIds.has(id))
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

          {/* Character strip — Filter NV + Đổi NV */}
          {characters.length > 0 && (
            <div className="flex items-center gap-2 px-3 py-1.5 border-b border-zinc-100 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-800/40 flex-shrink-0">
              <CharacterFilterDropdown
                characters={characters}
                subtitles={subtitles}
                selectedIds={filterCharIds}
                onChange={setFilterCharIds}
              />

              <button
                onClick={() => setShowSwapModal(true)}
                disabled={swapping}
                title="Đổi nhân vật hàng loạt (A → B)"
                className="px-2.5 py-1 text-[12px] rounded-lg border border-indigo-300 dark:border-indigo-700 bg-indigo-50 dark:bg-indigo-950/40 text-indigo-700 dark:text-indigo-400 hover:bg-indigo-100 dark:hover:bg-indigo-950/60 font-medium flex items-center gap-1.5 disabled:opacity-40"
              >
                🔄 <span>Đổi NV</span>
              </button>

              {filterCharIds.length > 0 && (
                <button
                  onClick={() => setFilterCharIds([])}
                  className="ml-auto text-[11px] text-zinc-500 hover:text-zinc-700 dark:hover:text-zinc-300 px-2 py-0.5 rounded hover:bg-zinc-100 dark:hover:bg-zinc-700/50"
                >
                  Xóa lọc NV ✕
                </button>
              )}
            </div>
          )}

          {/* Modal đổi NV (A → B) */}
          <SwapCharacterModal
            open={showSwapModal}
            characters={characters}
            subtitles={subtitles}
            onCancel={() => setShowSwapModal(false)}
            onConfirm={swapCharacter}
          />

          <SubtitleList
            filter={filter}
            filterNoChar={filterNoChar}
            filterNoTTS={filterNoTTS}
            overlapSubIds={filterOverlap ? overlapSubIds : undefined}
            filterCharIds={filterCharIds}
            chapters={chapters}
            onToggleChapter={handleToggleChapter}
            filterChapterIds={filterChapterIds}
          />
        </div>

        <DetailPanel />
      </div>


      {showAutoFix && (
        <AutoFixOverlapModal
          projectId={projectId}
          // v3.4: khi có filter — chỉ fix trong đoạn đang lọc
          subtitleIdsFilter={hasActiveFilter ? Array.from(visibleIdsSet) : undefined}
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

      {/* Dialog xác nhận import SRT tiếng Việt khi detect không phải tiếng Trung */}
      <ConfirmModal
        open={!!nonChineseDialog}
        variant="warning"
        title="File này không phải SRT tiếng Trung"
        message={
          nonChineseDialog
            ? `Hệ thống chỉ phát hiện ${(nonChineseDialog.cjkRatio * 100).toFixed(1)}% ký tự Trung (cần ≥ 30%).\n` +
              `Encoding: ${nonChineseDialog.encoding}\n\n` +
              `Bạn có muốn import như SRT tiếng Việt (phụ đề đã dịch sẵn) không?`
            : ''
        }
        warnings={[
          'Pipeline dịch Trung→Việt sẽ không khả dụng cho project này',
          'Phụ đề được dùng trực tiếp cho TTS lồng tiếng',
        ]}
        confirmText={importingVi ? 'Đang import...' : 'Import như SRT Việt'}
        cancelText="Hủy"
        onConfirm={confirmImportVi}
        onCancel={() => !importingVi && setNonChineseDialog(null)}
      />

      {/* Sticky toast tiến trình bulk TTS */}
      <BulkTTSProgress projectId={projectId} />
    </div>
  )
}