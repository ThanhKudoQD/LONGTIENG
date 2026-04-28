/**
 * Thuật toán helper — thay cho O(n²) trong SubtitleList và AudioList.
 * Với 6000 subs:
 *   - findDuplicateStarts: 18M ops → 6000 ops
 *   - findOverlapsSweep: 18M ops → 6000 ops
 */

interface SubLike {
  id: number
  start_time: number
  end_time: number
  audio_offset?: number
  wav_duration?: number | null
}

/**
 * Tìm các subtitle có start_time trùng nhau (sai số < epsilon).
 * O(n log n) — sort + scan tuyến tính.
 */
export function findDuplicateStarts(subs: SubLike[], epsilon = 0.05): Set<number> {
  const ids = new Set<number>()
  if (subs.length < 2) return ids

  // Sort theo start_time, giữ id để mark
  const arr = subs
    .map(s => ({ id: s.id, t: s.start_time }))
    .sort((a, b) => a.t - b.t)

  for (let i = 1; i < arr.length; i++) {
    if (Math.abs(arr[i].t - arr[i - 1].t) < epsilon) {
      ids.add(arr[i].id)
      ids.add(arr[i - 1].id)
    }
  }
  return ids
}

/**
 * Tìm các subtitle có audio block chồng lấn nhau.
 * O(n log n) — sort + sweep line.
 *
 * Sweep: duyệt theo start tăng dần, giữ "active set" các block chưa kết thúc.
 * Mỗi block mới so với active set hiện tại. Vì max-lane thường nhỏ (~5),
 * active set ngắn → tổng thời gian gần O(n).
 */
export function findOverlapsSweep(subs: SubLike[]): Set<number> {
  const overlaps = new Set<number>()
  if (subs.length < 2) return overlaps

  const blocks = subs.map(s => {
    const start = s.start_time + (s.audio_offset || 0)
    const dur = s.wav_duration ?? (s.end_time - s.start_time)
    return { id: s.id, start, end: start + dur }
  }).sort((a, b) => a.start - b.start)

  // Active set: các block chưa kết thúc tại thời điểm đang xét
  const active: typeof blocks = []

  for (const cur of blocks) {
    // Loại bỏ block đã kết thúc
    for (let i = active.length - 1; i >= 0; i--) {
      if (active[i].end <= cur.start + 0.01) {
        active.splice(i, 1)
      }
    }
    // Mọi block còn lại trong active đều overlap với cur
    if (active.length > 0) {
      overlaps.add(cur.id)
      for (const a of active) overlaps.add(a.id)
    }
    active.push(cur)
  }
  return overlaps
}

/**
 * Lane assignment cho audio blocks — first-fit theo thứ tự start.
 * Tách ra để không phải code lại trong AudioList.
 */
export function assignLanes(subs: SubLike[]): Map<number, number> {
  const lanes = new Map<number, number>()
  const laneEnds: number[] = []
  const sorted = [...subs].sort((a, b) =>
    (a.start_time + (a.audio_offset || 0)) - (b.start_time + (b.audio_offset || 0)))

  for (const s of sorted) {
    const start = s.start_time + (s.audio_offset || 0)
    const end = start + (s.wav_duration ?? (s.end_time - s.start_time))
    let lane = 0
    while (lane < laneEnds.length && laneEnds[lane] > start + 0.01) lane++
    lanes.set(s.id, lane)
    laneEnds[lane] = end
  }
  return lanes
}

/**
 * Math.max trên array lớn — dùng reduce thay vì spread.
 * Với 6000+ phần tử, spread (...arr) chậm hơn 3-5x và có thể stack overflow.
 */
export function maxOf(arr: number[]): number {
  if (arr.length === 0) return 0
  let m = arr[0]
  for (let i = 1; i < arr.length; i++) if (arr[i] > m) m = arr[i]
  return m
}
