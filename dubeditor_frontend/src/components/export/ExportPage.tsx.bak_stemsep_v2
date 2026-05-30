/**
 * ExportPage — trang Xuất Video.
 *
 * v2:
 *   - Load video gốc thật từ project
 *   - Detect sourceRatio để aspect_ratio 'source' hoạt động
 *   - Scrubber sync giữa Preview + Timeline
 */
import React, { useState, useEffect, useCallback } from 'react'
import {
  ExportConfig, ExportTab, ExportJob, ExportPreset,
  DEFAULT_CONFIG, TAB_META,
} from './types'
import api from '../../api'
import CutTab from './CutTab'
import SubtitleStyleTab from './SubtitleStyleTab'
import PaddingTab from './PaddingTab'
import WatermarkTab from './WatermarkTab'
import AudioTrackTab from './AudioTrackTab'
import OutputTab from './OutputTab'
import PreviewPanel from './PreviewPanel'
import RenderQueuePanel from './RenderQueuePanel'
import MultiTrackTimeline from './MultiTrackTimeline'
import PresetDialog from './PresetDialog'
import { outputToSource, sourceToOutput } from './playbackEngine'
import { runExport, listJobs, cancelJobApi, deleteJob, listPresets, getProjectConfig, saveProjectConfig } from './exportApi'

interface Props {
  projectId: number
  onBack: () => void
}

export default function ExportPage({ projectId, onBack }: Props) {
  const [config, setConfig] = useState<ExportConfig>(DEFAULT_CONFIG)
  const [configLoaded, setConfigLoaded] = useState(false)   // chỉ auto-save sau khi load xong
  const [activeTab, setActiveTab] = useState<ExportTab>('cut')
  const [jobs, setJobs] = useState<ExportJob[]>([])
  const [presets, setPresets] = useState<ExportPreset[]>([])
  const [presetDialogMode, setPresetDialogMode] = useState<'save' | 'manage' | null>(null)
  const [projectName, setProjectName] = useState('Project')
  const [videoUrl, setVideoUrl] = useState<string | null>(null)
  const [videoDuration, setVideoDuration] = useState<number>(0)
  const [sourceRatio, setSourceRatio] = useState<number | null>(null)
  // currentTime = OUTPUT time (đã cắt). MultiTrackTimeline dùng SOURCE time.
  const [currentTime, setCurrentTime] = useState<number>(0)
  // Source time tương ứng (cho MultiTrackTimeline marker)
  const [sourceTime, setSourceTime] = useState<number>(0)
  // Resizable preview panel width (% của container)
  const [previewWidthPct, setPreviewWidthPct] = useState<number>(40)
  const [resizingPanel, setResizingPanel] = useState(false)

  // Drag handler resize panel
  useEffect(() => {
    if (!resizingPanel) return
    const onMove = (e: MouseEvent) => {
      const totalW = window.innerWidth
      const pct = Math.max(20, Math.min(70, (e.clientX / totalW) * 100))
      setPreviewWidthPct(pct)
    }
    const onUp = () => setResizingPanel(false)
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
  }, [resizingPanel])

  // Sync output → source khi currentTime đổi
  useEffect(() => {
    const r = outputToSource(currentTime, config.clips, videoDuration)
    if (r) setSourceTime(r.source)
  }, [currentTime, config.clips, videoDuration])

  // Handler khi user scrub trên MultiTrackTimeline (đưa cho ta source time)
  const handleTimelineScrub = useCallback((srcT: number) => {
    setSourceTime(srcT)
    const out = sourceToOutput(srcT, config.clips, videoDuration)
    if (out !== null) {
      setCurrentTime(out)
    } else if (config.clips.length === 0) {
      setCurrentTime(srcT)
    }
    // Nếu source nằm ngoài clip → giữ currentTime cũ (không nhảy)
  }, [config.clips, videoDuration])
  const [voiceSegments, setVoiceSegments] = useState<Array<{ id: number; start: number; end: number; audio_path?: string }>>([])
  // Subs để HIỂN THỊ trên preview (text Việt + timing gốc video)
  // Khác voiceSegments ở chỗ: bao gồm cả subs chưa TTS, dùng start_time/end_time GỐC (không cộng audio_offset)
  // vì sub hiển thị phải khớp HÌNH ẢNH video, không phải audio TTS.
  const [subtitleSegments, setSubtitleSegments] = useState<Array<{ id: number; start: number; end: number; text: string }>>([])

  // Load voice segments từ subs đã TTS xong + sub display segments
  useEffect(() => {
    api.get(`/subtitles/project/${projectId}`).then(res => {
      const subs = res.data || []
      // Voice (cho audio playback)
      const voiceSegs = subs
        .filter((s: any) => s.tts_done && s.audio_path)
        .map((s: any) => ({
          id: s.id,
          start: (s.start_time || 0) + (s.audio_offset || 0),
          end: (s.start_time || 0) + (s.audio_offset || 0) + (s.wav_duration || (s.end_time - s.start_time)),
          audio_path: s.audio_path,
        }))
      setVoiceSegments(voiceSegs)

      // Subs display (cho hiển thị overlay) — lấy text Việt từ field `text` hoặc `vi_text`
      const subDisp = subs
        .filter((s: any) => s.text && s.text.trim() && !s.text.startsWith('[CHƯA') && !s.text.startsWith('[UNTRANSLATED'))
        .map((s: any) => ({
          id: s.id,
          start: s.start_time || 0,
          end: s.end_time || 0,
          text: s.text,
        }))
      setSubtitleSegments(subDisp)
    }).catch(() => {
      setVoiceSegments([])
      setSubtitleSegments([])
    })
  }, [projectId])

  // Load project info + video
  useEffect(() => {
    let cancelled = false
    api.get(`/projects/${projectId}`).then(res => {
      if (cancelled) return
      const p = res.data
      setProjectName(p.name || `Project #${projectId}`)
      // BE đã trả video_path là URL đầy đủ (vd /dub/projects/18/01.mp4)
      if (p.video_path) {
        setVideoUrl(p.video_path)
      } else if (p.video_name) {
        setVideoUrl(`/dub/projects/${projectId}/${p.video_name}`)
      }
    }).catch(() => {})
    return () => { cancelled = true }
  }, [projectId])

  // v4.0 — Load saved config của project (auto-save) + merge với DEFAULT_CONFIG
  useEffect(() => {
    let cancelled = false
    getProjectConfig(projectId)
      .then(saved => {
        if (cancelled) return
        if (saved) {
          // Merge saved vào DEFAULT để có field mới nếu schema thay đổi
          setConfig({
            ...DEFAULT_CONFIG,
            ...saved,
            // Deep merge subtitle_style / padding / audio / output để an toàn
            subtitle_style: { ...DEFAULT_CONFIG.subtitle_style, ...(saved.subtitle_style || {}) },
            padding: { ...DEFAULT_CONFIG.padding, ...(saved.padding || {}) },
            audio: { ...DEFAULT_CONFIG.audio, ...(saved.audio || {}) },
            output: { ...DEFAULT_CONFIG.output, ...(saved.output || {}) },
          })
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setConfigLoaded(true)
      })
    return () => { cancelled = true }
  }, [projectId])

  // v4.0 — Auto-save config debounce 1s khi user thay đổi
  useEffect(() => {
    if (!configLoaded) return    // tránh save lúc đầu chưa load
    const tid = setTimeout(() => {
      saveProjectConfig(projectId, config).catch(e => {
        console.warn('Auto-save config failed:', e?.message)
      })
    }, 1000)
    return () => clearTimeout(tid)
  }, [config, configLoaded, projectId])

  // Detect video duration + ratio khi videoUrl đổi
  useEffect(() => {
    if (!videoUrl) return
    const v = document.createElement('video')
    v.src = videoUrl
    v.preload = 'metadata'
    v.muted = true
    v.onloadedmetadata = () => {
      setVideoDuration(v.duration || 0)
      if (v.videoWidth && v.videoHeight) {
        setSourceRatio(v.videoWidth / v.videoHeight)
      }
    }
  }, [videoUrl])

  const updateConfig = useCallback(<K extends keyof ExportConfig>(
    key: K, value: ExportConfig[K]
  ) => {
    setConfig(prev => ({ ...prev, [key]: value }))
  }, [])

  const handleRender = async () => {
    try {
      const job = await runExport(projectId, config)
      setJobs(prev => [job, ...prev.filter(j => j.id !== job.id)])
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || 'Render thất bại'
      alert(`Lỗi: ${msg}`)
    }
  }

  // Load jobs từ BE + listen WS progress
  useEffect(() => {
    listJobs(projectId).then(setJobs).catch(() => {})

    // WS subscribe
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${proto}://${location.host}/dub/ws/${projectId}`)
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(ev.data)
        if (msg.type === 'export_progress' && msg.job) {
          const j = msg.job
          setJobs(prev => {
            const idx = prev.findIndex(x => x.id === j.id)
            const updated: ExportJob = {
              id: j.id,
              project_id: j.project_id,
              status: j.status,
              progress_percent: j.progress || 0,
              config: prev[idx]?.config || ({} as any),
              output_url: j.output_url,
              error_msg: j.error_msg,
              created_at: j.created_at || prev[idx]?.created_at || new Date().toISOString(),
              started_at: j.started_at || prev[idx]?.started_at,
              finished_at: j.finished_at || prev[idx]?.finished_at,
              estimated_remaining_sec: j.eta_sec || 0,
            }
            if (idx < 0) return [updated, ...prev]
            const next = prev.slice()
            next[idx] = { ...next[idx], ...updated }
            return next
          })
        }
      } catch {}
    }
    ws.onerror = () => {}
    return () => { try { ws.close() } catch {} }
  }, [projectId])

  // Load presets từ BE
  useEffect(() => {
    listPresets().then(setPresets).catch(() => {})
  }, [])

  const handleSavePreset = () => {
    setPresetDialogMode('save')
  }

  const handleManagePresets = () => {
    setPresetDialogMode('manage')
  }

  const handleApplyPreset = (preset: ExportPreset) => {
    setConfig(prev => ({ ...prev, ...preset.config }))
  }

  const handleReset = () => {
    if (!confirm('Reset toàn bộ config về mặc định?')) return
    setConfig(DEFAULT_CONFIG)
  }

  return (
    <div className="fixed inset-0 flex flex-col bg-zinc-50 dark:bg-zinc-950 overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-3 px-4 py-2.5 border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex-shrink-0">
        <button onClick={onBack} className="btn text-[13px]">← Editor</button>
        <div className="flex items-center gap-2">
          <span className="text-[15px] font-semibold text-zinc-900 dark:text-zinc-100">📤 Xuất video</span>
          <span className="text-[12px] text-zinc-500">·</span>
          <span className="text-[13px] text-zinc-600 dark:text-zinc-400">{projectName}</span>
          {videoDuration > 0 && (
            <>
              <span className="text-[12px] text-zinc-500">·</span>
              <span className="text-[12px] text-zinc-500 font-mono">
                {Math.floor(videoDuration / 60)}:{String(Math.floor(videoDuration % 60)).padStart(2, '0')}
                {sourceRatio && ` · ${(sourceRatio).toFixed(2)}:1`}
              </span>
            </>
          )}
        </div>

        <div className="ml-auto flex items-center gap-2">
          <select
            value=""
            onChange={e => {
              const p = presets.find(x => String(x.id) === e.target.value)
              if (p) handleApplyPreset(p)
            }}
            className="text-[12px] px-2 py-1.5 border border-zinc-200 dark:border-zinc-700 rounded-md bg-white dark:bg-zinc-900"
          >
            <option value="" disabled>
              {presets.length === 0 ? '(chưa có preset)' : `Apply preset... (${presets.length})`}
            </option>
            {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          {presets.length > 0 && (
            <button onClick={handleManagePresets} className="btn text-[12px]" title="Quản lý preset (xóa, đổi tên)">📦</button>
          )}
          <button onClick={handleSavePreset} className="btn text-[12px]">💾 Lưu preset</button>
          <button onClick={handleReset} className="btn text-[12px]">↻ Reset</button>
          <button onClick={handleRender} className="btn btn-primary text-[12px] font-semibold">▶ Render</button>
        </div>
      </header>

      {/* Main split */}
      <div className="flex flex-1 overflow-hidden min-h-0">
        {/* Preview (trái) - resizable */}
        <div className="flex-shrink-0 border-r border-zinc-200 dark:border-zinc-800 bg-zinc-100 dark:bg-zinc-900 overflow-hidden"
          style={{ width: `${previewWidthPct}%`, minWidth: 280 }}>
          <PreviewPanel
            config={config}
            videoUrl={videoUrl}
            videoDuration={videoDuration}
            sourceRatio={sourceRatio}
            currentTime={currentTime}
            sourceTime={sourceTime}
            onTimeChange={setCurrentTime}
            voiceSegments={voiceSegments}
            subtitleSegments={subtitleSegments}
          />
        </div>

        {/* Resize divider */}
        <div
          onMouseDown={() => setResizingPanel(true)}
          className="w-1 hover:w-1.5 bg-zinc-200 dark:bg-zinc-800 hover:bg-blue-400 cursor-col-resize flex-shrink-0 transition-all relative group"
          title="Kéo để chỉnh kích thước"
        >
          <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-1 h-8 bg-zinc-400 dark:bg-zinc-600 rounded opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>

        {/* Tabs + config (phải) */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          <nav className="flex border-b border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 flex-shrink-0 overflow-x-auto">
            {TAB_META.map(t => {
              const isActive = t.key === activeTab
              return (
                <button
                  key={t.key}
                  onClick={() => setActiveTab(t.key)}
                  className={`flex items-center gap-2 px-5 py-3 border-b-2 text-[13px] font-medium whitespace-nowrap transition-colors ${
                    isActive
                      ? 'border-blue-600 text-zinc-900 dark:text-zinc-100 bg-blue-50/40 dark:bg-blue-950/20'
                      : 'border-transparent text-zinc-500 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100'
                  }`}
                >
                  <span className="font-bold text-[14px]">{t.icon}</span>
                  <span>{t.label}</span>
                  {t.key === 'cut' && config.clips.length > 0 && (
                    <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded bg-zinc-200 dark:bg-zinc-700">
                      {config.clips.length}
                    </span>
                  )}
                  {t.key === 'watermark' && config.watermarks.length > 0 && (
                    <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded bg-zinc-200 dark:bg-zinc-700">
                      {config.watermarks.length}
                    </span>
                  )}
                  {t.key === 'audio' && config.audio.tracks.length > 0 && (
                    <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded bg-zinc-200 dark:bg-zinc-700">
                      {config.audio.tracks.length}
                    </span>
                  )}
                </button>
              )
            })}
          </nav>

          <div className="flex-1 overflow-y-auto p-5">
            {activeTab === 'cut' && (
              <CutTab
                clips={config.clips}
                videoDuration={videoDuration}
                onChange={clips => updateConfig('clips', clips)}
              />
            )}
            {activeTab === 'subtitle' && (
              <SubtitleStyleTab
                style={config.subtitle_style}
                onChange={style => updateConfig('subtitle_style', style)}
              />
            )}
            {activeTab === 'padding' && (
              <PaddingTab
                padding={config.padding}
                onChange={padding => updateConfig('padding', padding)}
              />
            )}
            {activeTab === 'watermark' && (
              <WatermarkTab
                watermarks={config.watermarks}
                projectId={projectId}
                onChange={watermarks => updateConfig('watermarks', watermarks)}
              />
            )}
            {activeTab === 'audio' && (
              <AudioTrackTab
                audio={config.audio}
                projectId={projectId}
                onChange={audio => updateConfig('audio', audio)}
              />
            )}
            {activeTab === 'output' && (
              <OutputTab
                output={config.output}
                sourceRatio={sourceRatio}
                onChange={output => updateConfig('output', output)}
              />
            )}
          </div>
        </div>
      </div>

      {/* Multi-track timeline (full width, dưới main) */}
      {videoDuration > 0 && (
        <div className="border-t border-zinc-200 dark:border-zinc-800 bg-white dark:bg-zinc-900 p-3 flex-shrink-0 max-h-[42vh] overflow-y-auto">
          <MultiTrackTimeline
            videoUrl={videoUrl}
            videoDuration={videoDuration}
            clips={config.clips}
            onClipsChange={clips => updateConfig('clips', clips)}
            audio={config.audio}
            onAudioChange={audio => updateConfig('audio', audio)}
            voiceSegments={voiceSegments}
            currentTime={sourceTime}
            onScrub={handleTimelineScrub}
          />
        </div>
      )}

      {jobs.length > 0 && (
        <RenderQueuePanel
          jobs={jobs}
          onCancel={id => {
            cancelJobApi(id).catch(() => {})
            // optimistic update
            setJobs(prev => prev.map(j => j.id === id ? { ...j, status: 'cancelled' as const } : j))
          }}
          onClear={id => {
            deleteJob(id).catch(() => {})
            setJobs(prev => prev.filter(j => j.id !== id))
          }}
        />
      )}

      {/* Preset dialog */}
      {presetDialogMode && (
        <PresetDialog
          mode={presetDialogMode}
          currentConfig={config}
          onClose={() => setPresetDialogMode(null)}
          onSaved={() => listPresets().then(setPresets).catch(() => {})}
          onApply={p => {
            handleApplyPreset(p)
            listPresets().then(setPresets).catch(() => {})   // refresh nếu có xóa
          }}
        />
      )}
    </div>
  )
}
