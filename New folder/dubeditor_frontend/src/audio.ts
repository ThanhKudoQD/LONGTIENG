/**
 * Global audio player singleton + pub/sub.
 * Trước đây nằm trong AudioList.tsx, components phải setInterval(150ms)
 * để biết playingId đổi → xoay vòng re-render. Giờ pub/sub: chỉ re-render khi đổi.
 */

let _audio: HTMLAudioElement | null = null
let _playingId: number | null = null
const _listeners = new Set<(id: number | null) => void>()

function _notify(id: number | null) {
  if (_playingId === id) return
  _playingId = id
  _listeners.forEach(l => {
    try { l(id) } catch {}
  })
}

export function playSubAudio(subId: number, audioPath: string, onEnd?: () => void, speed: number = 1.0): boolean {
  // Toggle: đang phát chính dòng này → dừng
  if (_playingId === subId && _audio && !_audio.paused) {
    _audio.pause()
    _audio.currentTime = 0
    _audio = null
    _notify(null)
    return false
  }
  if (_audio) {
    _audio.pause()
    _audio = null
  }
  const audio = new Audio(`${audioPath}?t=${Date.now()}`)
  audio.playbackRate = speed
  _audio = audio
  _notify(subId)
  audio.play().catch(() => {})
  audio.onended = () => {
    if (_audio === audio) {
      _audio = null
      _notify(null)
    }
    onEnd?.()
  }
  return true
}

export function stopGlobalAudio() {
  if (_audio) {
    _audio.pause()
    _audio = null
  }
  _notify(null)
}

export function getGlobalPlayingId(): number | null {
  return _playingId
}

/**
 * Subscribe để nhận thông báo khi playingId thay đổi.
 * Trả về unsubscribe function.
 */
export function subscribePlayingId(cb: (id: number | null) => void): () => void {
  _listeners.add(cb)
  return () => { _listeners.delete(cb) }
}
