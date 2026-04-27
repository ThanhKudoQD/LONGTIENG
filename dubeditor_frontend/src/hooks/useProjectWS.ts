import { useEffect, useRef } from 'react'
import useStore from '../store'

export function useProjectWS(projectId: number | null) {
  const ws = useRef<WebSocket | null>(null)
  const markTTSDone = useStore(s => s.markTTSDone)

  useEffect(() => {
    if (!projectId) return
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/dub/ws/${projectId}`
    ws.current = new WebSocket(url)

    ws.current.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      if (msg.type === 'tts_done') {
        markTTSDone(msg.subtitle_id, msg.audio_path, msg.wav_duration)
      }
      if (msg.type === 'video_upload') {
        window.dispatchEvent(new CustomEvent('video_upload', { detail: msg }))
      }
      if (msg.type === 'export_progress') {
        window.dispatchEvent(new CustomEvent('export_progress', { detail: msg }))
      }
      if (msg.type === 'export_done') {
        window.dispatchEvent(new CustomEvent('export_done', { detail: msg }))
        // Tự động download
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
    }

    return () => ws.current?.close()
  }, [projectId])
}
