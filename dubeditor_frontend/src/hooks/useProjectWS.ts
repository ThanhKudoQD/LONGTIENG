import { useEffect, useRef } from 'react'
import useStore from '../store'

/**
 * PERF: Khi bulk TTS chạy 6000 subs, backend bắn 6000 event tts_done liên tiếp.
 * Trước đây mỗi event gọi markTTSDone → tạo array subtitles mới → cascade re-render
 * SubtitleList/AudioList/CharSidebar 6000 lần.
 *
 * Giờ batch lại: gom các tts_done trong cửa sổ 200ms thành 1 lần update store.
 * Backend không cần đổi.
 */

interface TtsBatch {
  id: number
  audio_path: string
  wav_duration?: number
}

const BATCH_INTERVAL_MS = 200

export function useProjectWS(projectId: number | null) {
  const ws = useRef<WebSocket | null>(null)
  const batchRef = useRef<TtsBatch[]>([])
  const flushTimerRef = useRef<number | null>(null)

  useEffect(() => {
    if (!projectId) return

    const flushBatch = () => {
      flushTimerRef.current = null
      const items = batchRef.current
      if (!items.length) return
      batchRef.current = []

      // Một lần update store cho cả batch — chỉ 1 cascade re-render thay vì N
      useStore.setState(state => {
        const idMap = new Map<number, TtsBatch>()
        for (const it of items) idMap.set(it.id, it)

        const next = state.subtitles.slice()
        let changed = false
        for (let i = 0; i < next.length; i++) {
          const upd = idMap.get(next[i].id)
          if (upd) {
            next[i] = {
              ...next[i],
              tts_done: true,
              audio_path: upd.audio_path,
              ...(upd.wav_duration !== undefined ? { wav_duration: upd.wav_duration } : {}),
            }
            changed = true
          }
        }
        if (!changed) return state
        return { subtitles: next, lastTtsAt: Date.now() }
      })
    }

    const enqueueTts = (id: number, audio_path: string, wav_duration?: number) => {
      batchRef.current.push({ id, audio_path, wav_duration })
      if (flushTimerRef.current == null) {
        flushTimerRef.current = window.setTimeout(flushBatch, BATCH_INTERVAL_MS)
      }
    }

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/dub/ws/${projectId}`
    ws.current = new WebSocket(url)

    ws.current.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'tts_done') {
        // PERF: batch thay vì gọi markTTSDone ngay
        enqueueTts(msg.subtitle_id, msg.audio_path, msg.wav_duration)
        return
      }
      if (msg.type === 'video_upload') {
        window.dispatchEvent(new CustomEvent('video_upload', { detail: msg }))
      }
      if (msg.type === 'export_progress') {
        window.dispatchEvent(new CustomEvent('export_progress', { detail: msg }))
      }
      if (msg.type === 'export_done') {
        window.dispatchEvent(new CustomEvent('export_done', { detail: msg }))
        const a = document.createElement('a')
        a.href = msg.path
        a.download = msg.path.split('/').pop() || 'export'
        document.body.appendChild(a); a.click(); document.body.removeChild(a)
      }
      if (msg.type === 'export_error') {
        window.dispatchEvent(new CustomEvent('export_error', { detail: msg }))
      }
      if (msg.type === 'auto_assign_progress') {
        window.dispatchEvent(new CustomEvent('aa_progress', { detail: { pct: msg.pct, step: msg.step } }))
      }
      if (msg.type === 'auto_assign_done') {
        window.dispatchEvent(new CustomEvent('aa_done', { detail: msg }))
      }
      if (msg.type === 'auto_assign_error') {
        window.dispatchEvent(new CustomEvent('aa_error', { detail: msg }))
      }
      // TTS Queue events — sync state vào store
      if (msg.type === 'tts_queue_state') {
        useStore.getState().setTtsQueueState(msg.running ?? null, msg.pending || [])
      }
      if (msg.type === 'tts_queue_error') {
        window.dispatchEvent(new CustomEvent('tts_queue_error', { detail: msg }))
      }
    }

    return () => {
      ws.current?.close()
      if (flushTimerRef.current != null) {
        clearTimeout(flushTimerRef.current)
        flushBatch()
      }
    }
  }, [projectId])
}
