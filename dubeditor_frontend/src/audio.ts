/**
 * Global audio player singleton + pub/sub.
 *
 * v2 — tối ưu độ trễ khi click sub có audio:
 *   - BỎ cache busting `?t=Date.now()` (làm browser tải lại file mỗi lần).
 *     FastAPI StaticFiles đã trả ETag/Last-Modified, browser tự revalidate
 *     khi file đổi → không cần bust.
 *   - REUSE 1 HTMLAudioElement thay vì `new Audio()` mỗi click → tiết kiệm
 *     overhead init/decode.
 *   - PRELOAD audio cho các sub gần (preload="auto") → giảm fetch latency
 *     gần như 0 cho các row visible.
 */

let _audio: HTMLAudioElement | null = null
let _playingId: number | null = null
const _listeners = new Set<(id: number | null) => void>()

// Preload cache: subId → HTMLAudioElement đã preload (chỉ giữ ref, GC khi cần)
const _preloadCache = new Map<number, HTMLAudioElement>()
const PRELOAD_MAX = 30   // tối đa giữ 30 audio đã preload

function _notify(id: number | null) {
  if (_playingId === id) return
  _playingId = id
  _listeners.forEach(l => {
    try { l(id) } catch {}
  })
}

function _getOrCreate(subId: number, audioPath: string): HTMLAudioElement {
  const cached = _preloadCache.get(subId)
  if (cached && cached.src.endsWith(audioPath)) {
    return cached
  }
  // Tạo mới + preload metadata + buffer
  const a = new Audio()
  a.preload = 'auto'
  a.src = audioPath   // KHÔNG thêm ?t=... — để browser cache theo ETag
  _preloadCache.set(subId, a)
  // LRU đơn giản: nếu vượt giới hạn, xóa cái cũ nhất (key đầu Map)
  if (_preloadCache.size > PRELOAD_MAX) {
    const firstKey = _preloadCache.keys().next().value
    if (firstKey !== undefined && firstKey !== subId) {
      _preloadCache.delete(firstKey)
    }
  }
  return a
}

export function playSubAudio(
  subId: number,
  audioPath: string,
  onEnd?: () => void,
  speed: number = 1.0,
): boolean {
  // Toggle: đang phát chính dòng này → dừng
  if (_playingId === subId && _audio && !_audio.paused) {
    _audio.pause()
    _audio.currentTime = 0
    _audio = null
    _notify(null)
    return false
  }
  // Dừng audio đang phát (không xóa khỏi preload cache để click lại nhanh)
  if (_audio) {
    _audio.pause()
    _audio.currentTime = 0
    _audio = null
  }

  const a = _getOrCreate(subId, audioPath)
  a.playbackRate = speed
  // Nếu đã được preload, đặt lại currentTime để phát từ đầu
  try { a.currentTime = 0 } catch { /* InvalidStateError nếu chưa load metadata, bỏ qua */ }

  _audio = a
  _notify(subId)

  a.play().catch(() => {
    // Lỗi play (vd browser block autoplay) — không crash
  })

  // onended dùng addEventListener để có thể detach (tránh leak callback cũ)
  const handleEnd = () => {
    if (_audio === a) {
      _audio = null
      _notify(null)
    }
    a.removeEventListener('ended', handleEnd)
    onEnd?.()
  }
  a.addEventListener('ended', handleEnd)
  return true
}

export function stopGlobalAudio() {
  if (_audio) {
    _audio.pause()
    _audio.currentTime = 0
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

/**
 * Preload audio cho 1 danh sách sub (không phát). Dùng khi virtualizer render
 * range mới → preload audio cho các row visible + neighbors để click instant.
 *
 * subs: [{id, audio_path}], chỉ những sub có audio_path.
 */
export function preloadSubAudios(subs: Array<{ id: number; audio_path: string | null | undefined }>): void {
  for (const s of subs) {
    if (!s.audio_path) continue
    if (_preloadCache.has(s.id)) continue
    _getOrCreate(s.id, s.audio_path)
  }
}

/**
 * Xóa preload cache (vd khi đổi project). Audio đang phát giữ nguyên.
 */
export function clearPreloadCache(): void {
  // Giữ lại audio đang phát
  const playing = _playingId
  _preloadCache.forEach((a, id) => {
    if (id !== playing) {
      try { a.src = '' } catch {}
    }
  })
  _preloadCache.clear()
}

/**
 * Invalidate preload cho 1 sub (khi audio bị xóa hoặc TTS lại). Lần click sau
 * sẽ fetch lại từ server.
 */
export function invalidatePreload(subId: number): void {
  const a = _preloadCache.get(subId)
  if (a) {
    try { a.src = '' } catch {}
    _preloadCache.delete(subId)
  }
}
