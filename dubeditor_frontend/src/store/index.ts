import { create } from 'zustand'
import { Project, Subtitle, Character } from '../types'
import api from '../api'

/**
 * PERF NOTES — quan trọng khi sửa code:
 *
 * 1) Components KHÔNG được destructure useStore() — phải dùng selector cho từng field:
 *    ❌ const { subtitles, activeSubId } = useStore()
 *    ✅ const subtitles = useStore(s => s.subtitles)
 *    Lý do: destructure subscribe vào toàn bộ store → mọi state change đều re-render.
 *
 * 2) playTime tách thành store riêng (usePlayTimeStore) để 60 tick/giây từ video
 *    không trigger re-render SubtitleList/CharSidebar/AudioList.
 *    Chỉ component cần playTime (Playhead) subscribe usePlayTimeStore.
 *
 * 3) updateSubtitle/markTTSDone dùng slice + index thay vì map() toàn bộ array.
 */

interface EditorStore {
  project: Project | null
  subtitles: Subtitle[]
  characters: Character[]
  // v3: map character_id → list mode khả dụng (đã upload audio)
  voiceModesByCharacter: Record<number, string[]>
  activeSubId: number | null
  selectedIds: Set<number>

  // ── FILTER STATE (single source of truth) ──────────────────────────────
  // Dùng cho TOÀN BỘ hành động: hiển thị, đếm, select-all, bulk TTS, auto-fix,
  // bulk trim, set speed character… Khi có filter → mọi xử lý hàng loạt chỉ
  // động vào subset đang lọc. Không filter → áp toàn phim như cũ.
  filterText: string
  filterNoChar: boolean
  filterNoTTS: boolean
  filterOverlap: boolean
  filterCharIds: number[]
  filterChapterIds: number[]
  // chapters cached ở store để selector visibility tính được range
  chapters: any[]
  // overlapSubIds cache cho filter "Lọc đè"
  overlapSubIds: Set<number>

  setFilterText: (v: string) => void
  setFilterNoChar: (v: boolean) => void
  setFilterNoTTS: (v: boolean) => void
  setFilterOverlap: (v: boolean) => void
  setFilterCharIds: (ids: number[]) => void
  setFilterChapterIds: (ids: number[]) => void
  setChapters: (ch: any[]) => void
  setOverlapSubIds: (s: Set<number>) => void

  setProject: (p: Project) => void
  setSubtitles: (s: Subtitle[]) => void
  setCharacters: (c: Character[]) => void
  setActiveSubId: (id: number | null) => void
  setActiveSubIdFromVideo: (id: number | null) => void
  toggleSelect: (id: number, multi?: boolean, range?: boolean, visibleIds?: number[]) => void

  // Compat shim — VideoPlayer cũ gọi useStore.getState().setPlayTime
  // Forward sang usePlayTimeStore.
  setPlayTime: (t: number) => void
  playTime: number  // luôn đọc từ usePlayTimeStore qua getter, KHÔNG dùng làm dep

  lastTtsAt: number
  updateSubtitle: (id: number, patch: Partial<Subtitle>) => void
  deleteSubtitle: (id: number) => void
  deleteAudio: (ids: number[]) => void
  markTTSDone: (id: number, audioPath: string, wavDuration?: number) => void
  loadProject: (projectId: number) => Promise<void>

  seekRequest: { time: number; id: number } | null
  clearSeekRequest: () => void

  // TTS Queue state — sync từ WS event tts_queue_state
  ttsQueueRunning: number | null
  ttsQueuePending: number[]
  setTtsQueueState: (running: number | null, pending: number[]) => void

  // Auto TTS toggle — gán nhân vật xong tự enqueue
  autoTTS: boolean
  setAutoTTS: (v: boolean) => void
}

// v3.13: 2 cờ tracking nguồn của setActiveSubId
// - userSelectedUntil: dùng cho việc khác (vd. block video auto-seek track)
// - _activeSubIsUserChange: dùng RIÊNG cho auto-sync resume — SET TRUE khi user click,
//   reset FALSE NGAY trong subscribe handler sau khi đọc xong. Tránh trường hợp:
//   user click sub 11 → 100ms sau video chạy tới sub 37 → flag time-based 1000ms
//   vẫn TRUE → save 37 thay vì 11.
let userSelectedUntil = 0
let _activeSubIsUserChange = false

const useStore = create<EditorStore>((set, get) => ({
  project: null,
  subtitles: [],
  characters: [],
  voiceModesByCharacter: {},
  activeSubId: null,
  selectedIds: new Set(),
  seekRequest: null,
  lastTtsAt: 0,

  // ── Filter state defaults ────────────────────────────────────────────
  filterText: '',
  filterNoChar: false,
  filterNoTTS: false,
  filterOverlap: false,
  filterCharIds: [],
  filterChapterIds: [],
  chapters: [],
  overlapSubIds: new Set(),

  setFilterText: (v) => set({ filterText: v }),
  setFilterNoChar: (v) => set({ filterNoChar: v }),
  setFilterNoTTS: (v) => set({ filterNoTTS: v }),
  setFilterOverlap: (v) => set({ filterOverlap: v }),
  setFilterCharIds: (ids) => set({ filterCharIds: ids }),
  setFilterChapterIds: (ids) => set({ filterChapterIds: ids }),
  setChapters: (ch) => set({ chapters: ch }),
  setOverlapSubIds: (s) => set({ overlapSubIds: s }),

  // Stub — thực tế đọc/ghi qua usePlayTimeStore. Setter forward bên dưới.
  playTime: 0,
  setPlayTime: (t: number) => usePlayTimeStore.getState().setPlayTime(t),

  setProject: (p) => set({ project: p }),
  setSubtitles: (s) => set({ subtitles: s }),
  setCharacters: (c) => set({ characters: c }),

  setActiveSubId: (id) => {
    const sub = get().subtitles.find(s => s.id === id)
    userSelectedUntil = Date.now() + 1000
    _activeSubIsUserChange = true   // v3.13: subscribe sẽ đọc + reset
    set({
      activeSubId: id,
      selectedIds: new Set(id ? [id] : []),
      seekRequest: sub ? { time: sub.start_time, id: Date.now() } : null,
    })
  },

  setActiveSubIdFromVideo: (id) => {
    if (get().activeSubId === id) return
    // v3.13: KHÔNG set _activeSubIsUserChange — video chạy không phải user action
    set({ activeSubId: id })
  },

  toggleSelect: (id, multi = false, range = false, visibleIds?) => {
    const { selectedIds, subtitles, activeSubId } = get()
    const pool = visibleIds ?? subtitles.map(s => s.id)
    // v3.13: mọi nhánh đều là user action → set flag
    _activeSubIsUserChange = true
    if (range && activeSubId) {
      const a = pool.indexOf(activeSubId), b = pool.indexOf(id)
      const lo = Math.min(a, b), hi = Math.max(a, b)
      set({ selectedIds: new Set(pool.slice(lo, hi + 1)), activeSubId: id })
    } else if (multi) {
      const newSel = new Set(selectedIds)
      newSel.has(id) ? newSel.delete(id) : newSel.add(id)
      set({ selectedIds: newSel, activeSubId: id })
    } else {
      const sub = subtitles.find(s => s.id === id)
      userSelectedUntil = Date.now() + 1000
      set({
        selectedIds: new Set([id]),
        activeSubId: id,
        seekRequest: sub ? { time: sub.start_time, id: Date.now() } : null,
      })
    }
  },

  clearSeekRequest: () => set({ seekRequest: null }),

  // TTS Queue state
  ttsQueueRunning: null,
  ttsQueuePending: [],
  setTtsQueueState: (running, pending) => set({ ttsQueueRunning: running, ttsQueuePending: pending }),

  // Auto TTS — load từ localStorage, default off
  autoTTS: typeof window !== 'undefined' && localStorage.getItem('autoTTS') === '1',
  setAutoTTS: (v: boolean) => {
    if (typeof window !== 'undefined') localStorage.setItem('autoTTS', v ? '1' : '0')
    set({ autoTTS: v })
  },

  // OPTIMIZED: dùng index + slice thay vì map() toàn bộ → giữ tham chiếu các phần tử khác
  updateSubtitle: (id, patch) => {
    set(state => {
      const idx = state.subtitles.findIndex(s => s.id === id)
      if (idx < 0) return state
      const next = state.subtitles.slice()
      next[idx] = { ...next[idx], ...patch }
      return {
        subtitles: next,
        lastTtsAt: (patch.tts_done || patch.audio_path) ? Date.now() : state.lastTtsAt,
      }
    })
  },

  deleteAudio: (ids) => {
    const idSet = new Set(ids)
    set(state => ({
      subtitles: state.subtitles.map(s =>
        idSet.has(s.id) ? { ...s, tts_done: false, audio_path: null, wav_duration: null } : s
      ),
    }))
  },

  deleteSubtitle: (id) => {
    set(state => {
      const newSel = new Set(state.selectedIds)
      newSel.delete(id)
      return {
        subtitles: state.subtitles.filter(s => s.id !== id),
        selectedIds: newSel,
      }
    })
  },

  markTTSDone: (id, audioPath, wavDuration) => {
    set(state => {
      const idx = state.subtitles.findIndex(s => s.id === id)
      if (idx < 0) return state
      const next = state.subtitles.slice()
      next[idx] = {
        ...next[idx],
        tts_done: true,
        audio_path: audioPath,
        ...(wavDuration !== undefined ? { wav_duration: wavDuration } : {}),
      }
      return { subtitles: next, lastTtsAt: Date.now() }
    })
  },

  loadProject: async (projectId) => {
    // v3.13 FIX: Chỉ reset filter + activeSub khi ĐỔI project. Nếu loadProject
    // được gọi lại với CÙNG projectId (vd. sau import SRT, sau upload video),
    // GIỮ NGUYÊN filter + activeSub để không phá resume state.
    // Trước đây: reset cả 2 → loadProject lần 2 ghi đè state vừa resume xong
    // → auto-sync PATCH null lên DB → lần mở sau bị mất.
    const currentProjectId = (useStore.getState().project as any)?.id
    const sameProject = currentProjectId === projectId

    const [proj, subs, chars, vmRes] = await Promise.all([
      api.get(`/projects/${projectId}`).then(r => r.data),
      api.get(`/subtitles/project/${projectId}`).then(r => r.data),
      api.get(`/characters/project/${projectId}`).then(r => r.data),
      api.get(`/characters/project/${projectId}/voice-modes`).then(r => r.data).catch((e) => {
        console.warn('[Store] voice-modes endpoint failed, fallback to empty:', e?.message)
        return {}
      }),
    ])
    const vm: Record<number, string[]> = {}
    for (const [k, v] of Object.entries(vmRes || {})) {
      vm[Number(k)] = Array.isArray(v) ? (v as string[]) : []
    }
    console.log('[Store] voiceModesByCharacter:', vm, 'sameProject:', sameProject)

    if (sameProject) {
      // Cùng project (reload sau upload/import) — KHÔNG đụng tới filter/activeSub
      set({
        project: proj,
        subtitles: subs,
        characters: chars,
        voiceModesByCharacter: vm,
      })
    } else {
      // Đổi project — reset toàn bộ state filter/active để tránh leak từ project cũ
      set({
        project: proj,
        subtitles: subs,
        characters: chars,
        voiceModesByCharacter: vm,
        activeSubId: null,
        selectedIds: new Set(),
        filterText: '',
        filterNoChar: false,
        filterNoTTS: false,
        filterOverlap: false,
        filterCharIds: [],
        filterChapterIds: [],
        chapters: [],
        overlapSubIds: new Set(),
      })
    }
  },
}))

// ─── PlayTime Store riêng ──────────────────────────────────────────────────
interface PlayTimeStore {
  playTime: number
  setPlayTime: (t: number) => void
}

export const usePlayTimeStore = create<PlayTimeStore>((set) => ({
  playTime: 0,
  setPlayTime: (t) => {
    set({ playTime: t })

    if (Date.now() < userSelectedUntil) return

    const subs = useStore.getState().subtitles
    if (!subs.length) return

    // Binary search — subtitles đã sort theo start_time (từ backend ORDER BY index)
    let lo = 0, hi = subs.length - 1, idx = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (subs[mid].start_time <= t) { idx = mid; lo = mid + 1 }
      else hi = mid - 1
    }
    const newActive = idx >= 0 ? subs[idx].id : null
    if (useStore.getState().activeSubId !== newActive) {
      useStore.getState().setActiveSubIdFromVideo(newActive)
    }
  },
}))

export default useStore

// ─────────────────────────────────────────────────────────────────────
// VISIBLE SELECTORS — single source of truth cho filter
// ─────────────────────────────────────────────────────────────────────
// Bất cứ hành động hàng loạt nào (TTS, auto-fix, delete, set speed,
// swap NV, trim…) ĐỀU phải dùng các hàm này, KHÔNG được đọc trực tiếp
// state.subtitles và tự build filter, để tránh lệch giữa các component.
//
// Quy tắc: nếu có BẤT KỲ filter nào đang bật → trả subset đã lọc.
//          nếu không filter → trả toàn bộ subtitles.

export interface VisibleFilters {
  filterText: string
  filterNoChar: boolean
  filterNoTTS: boolean
  filterOverlap: boolean
  filterCharIds: number[]
  filterChapterIds: number[]
  overlapSubIds: Set<number>
  chapters: any[]
}

export function readFilters(): VisibleFilters {
  const s = useStore.getState()
  return {
    filterText: s.filterText,
    filterNoChar: s.filterNoChar,
    filterNoTTS: s.filterNoTTS,
    filterOverlap: s.filterOverlap,
    filterCharIds: s.filterCharIds,
    filterChapterIds: s.filterChapterIds,
    overlapSubIds: s.overlapSubIds,
    chapters: s.chapters,
  }
}

export function hasAnyFilter(f?: VisibleFilters): boolean {
  const v = f ?? readFilters()
  return !!(
    v.filterText.trim() ||
    v.filterNoChar ||
    v.filterNoTTS ||
    v.filterOverlap ||
    v.filterCharIds.length > 0 ||
    v.filterChapterIds.length > 0
  )
}

function buildChapterRanges(f: VisibleFilters): [number, number][] {
  if (!f.filterChapterIds.length) return []
  return f.chapters
    .filter((c: any) => f.filterChapterIds.includes(c.id))
    .map((c: any) => [c.start_sub_index, c.end_sub_index] as [number, number])
}

function matchVisible(s: Subtitle, f: VisibleFilters, chapterRanges: [number, number][]): boolean {
  if (f.filterText) {
    const q = f.filterText.toLowerCase()
    if (!s.text.toLowerCase().includes(q) &&
        !(s.character?.name?.toLowerCase().includes(q))) return false
  }
  if (f.filterNoChar && s.character_id) return false
  if (f.filterNoTTS && (s as any).tts_done) return false
  if (f.filterOverlap && !f.overlapSubIds.has(s.id)) return false
  if (f.filterCharIds.length > 0 &&
      (!s.character_id || !f.filterCharIds.includes(s.character_id))) return false
  // v3.4 FIX: nếu user ĐÃ chọn filter chapter mà chapterRanges rỗng
  // (chapters chưa load xong trong store, hoặc chapter id không match)
  // → coi như KHÔNG match (an toàn: không thấy gì còn hơn show toàn phim
  //   khiến bulk TTS xử lý sai range).
  // Trước đây: chỉ check khi chapterRanges.length > 0 → bug: bulk TTS chạy
  // toàn phim trong khi user đang filter 1 chapter.
  if (f.filterChapterIds.length > 0) {
    if (chapterRanges.length === 0) return false
    const inRange = chapterRanges.some(([lo, hi]) => s.index >= lo && s.index <= hi)
    if (!inRange) return false
  }
  return true
}

/**
 * Trả các Subtitle đang VISIBLE theo filter hiện tại.
 * Không filter → trả full subtitles.
 */
export function getVisibleSubtitles(): Subtitle[] {
  const f = readFilters()
  if (!hasAnyFilter(f)) return useStore.getState().subtitles
  const ranges = buildChapterRanges(f)
  return useStore.getState().subtitles.filter(s => matchVisible(s, f, ranges))
}

/**
 * Trả ids các Subtitle đang VISIBLE theo filter hiện tại.
 */
export function getVisibleSubtitleIds(): number[] {
  return getVisibleSubtitles().map(s => s.id)
}

/**
 * Helper cho component cần tính visible từ state đã có (memo).
 * Truyền subtitles + filters → trả subset.
 */
export function filterVisible(
  subtitles: Subtitle[],
  f: VisibleFilters,
): Subtitle[] {
  const has =
    !!f.filterText.trim() ||
    f.filterNoChar ||
    f.filterNoTTS ||
    f.filterOverlap ||
    f.filterCharIds.length > 0 ||
    f.filterChapterIds.length > 0
  if (!has) return subtitles
  const ranges = buildChapterRanges(f)
  return subtitles.filter(s => matchVisible(s, f, ranges))
}


// ─────────────────────────────────────────────────────────────────────
// v3.9: AUTO-SYNC RESUME STATE → BACKEND
// ─────────────────────────────────────────────────────────────────────
// Mỗi khi user đổi filterChapterIds hoặc activeSubId, PATCH lên Project DB.
// Khi mở lại project, Editor sẽ đọc last_filter_chapter_ids + last_subtitle_index
// để restore trạng thái.
//
// Debounce để không spam HTTP request khi user click liên tục.
// - filterChapterIds: 500ms
// - activeSubId: 1500ms
//
// Dùng zustand.subscribe() mặc định (1 arg) + so sánh ref ngoài để tương thích
// cả zustand v3 và v4 không cần subscribeWithSelector middleware.
//
// QUAN TRỌNG: Editor.tsx phải gọi `markResumeApplied()` SAU KHI đã restore
// filter + activeSubId từ DB, để các thay đổi trước đó không bị ghi đè.

let _filterSyncTimer: ReturnType<typeof setTimeout> | null = null
let _activeSubSyncTimer: ReturnType<typeof setTimeout> | null = null
let _lastSyncedFilterKey = ''         // dedup
let _lastSyncedActiveIndex: number | null | undefined = undefined
let _prevProjectId: number | null = null
let _prevFilterChapterIds: number[] = []
let _prevActiveSubId: number | null = null
// Khi mở project mới, syncing bị tắt cho đến khi Editor restore xong
// (tránh ghi đè data DB bằng filterChapterIds=[] mặc định)
let _resumeApplied = false

export function markResumeApplied() {
  // v3.13 FIX: Clear pending sync timers + reset flag TRƯỚC khi mark applied.
  if (_filterSyncTimer) { clearTimeout(_filterSyncTimer); _filterSyncTimer = null }
  if (_activeSubSyncTimer) { clearTimeout(_activeSubSyncTimer); _activeSubSyncTimer = null }
  _activeSubIsUserChange = false   // resume gọi setActiveSubId nhưng KHÔNG phải user click

  _resumeApplied = true
  // Sync ngay value hiện tại làm baseline (không gọi API)
  const s = useStore.getState()
  const ids = [...s.filterChapterIds].sort((a, b) => a - b)
  _lastSyncedFilterKey = JSON.stringify(ids)
  const sub = s.activeSubId ? s.subtitles.find(x => x.id === s.activeSubId) : null
  _lastSyncedActiveIndex = sub ? sub.index : null
  _prevFilterChapterIds = s.filterChapterIds
  _prevActiveSubId = s.activeSubId
}

function _patchProject(pid: number, body: Record<string, any>) {
  console.log('[Resume Sync] PATCH project', pid, body)
  return api.patch(`/projects/${pid}`, body).catch((e) => {
    console.warn('[Resume Sync] PATCH project failed:', e?.message)
  })
}

useStore.subscribe((state) => {
  const pid = state.project?.id ?? null

  // Reset cache khi đổi project
  if (pid !== _prevProjectId) {
    _prevProjectId = pid
    _prevFilterChapterIds = state.filterChapterIds
    _prevActiveSubId = state.activeSubId
    _lastSyncedFilterKey = ''
    _lastSyncedActiveIndex = undefined
    _resumeApplied = false    // chờ Editor restore xong
    _activeSubIsUserChange = false   // v3.13: reset flag
    if (_filterSyncTimer) { clearTimeout(_filterSyncTimer); _filterSyncTimer = null }
    if (_activeSubSyncTimer) { clearTimeout(_activeSubSyncTimer); _activeSubSyncTimer = null }
    return
  }
  if (!pid) return
  // Chưa restore xong → bỏ qua mọi thay đổi (default value, không phải user action)
  if (!_resumeApplied) {
    _prevFilterChapterIds = state.filterChapterIds
    _prevActiveSubId = state.activeSubId
    _activeSubIsUserChange = false   // v3.13: clear flag nếu set trong lúc chưa resume
    return
  }

  // Filter chapter changed?
  if (state.filterChapterIds !== _prevFilterChapterIds) {
    _prevFilterChapterIds = state.filterChapterIds
    const ids = [...state.filterChapterIds].sort((a, b) => a - b)
    const key = JSON.stringify(ids)
    if (key !== _lastSyncedFilterKey) {
      if (_filterSyncTimer) clearTimeout(_filterSyncTimer)
      _filterSyncTimer = setTimeout(() => {
        _lastSyncedFilterKey = key
        console.log('[Resume Sync] Filter changed → saving:', ids)
        _patchProject(pid, { last_filter_chapter_ids: ids.length ? ids : null })
      }, 500)
    }
  }

  // Active sub changed?
  // v3.13 FIX: Chỉ save khi user vừa CLICK chọn sub. Dùng flag boolean
  // _activeSubIsUserChange (set bởi setActiveSubId/toggleSelect, KHÔNG set bởi
  // setActiveSubIdFromVideo) — reset NGAY trong handler này sau khi đọc, tránh
  // bug click sub A → 100ms sau video chạy tới sub B → flag time-based vẫn
  // TRUE → save B thay vì A.
  if (state.activeSubId !== _prevActiveSubId) {
    _prevActiveSubId = state.activeSubId
    const wasUserSelect = _activeSubIsUserChange
    _activeSubIsUserChange = false   // reset NGAY sau khi đọc
    if (wasUserSelect) {
      const sub = state.activeSubId
        ? state.subtitles.find(s => s.id === state.activeSubId)
        : null
      const idx = sub ? sub.index : null
      if (idx !== _lastSyncedActiveIndex) {
        if (_activeSubSyncTimer) clearTimeout(_activeSubSyncTimer)
        _activeSubSyncTimer = setTimeout(() => {
          _lastSyncedActiveIndex = idx
          console.log('[Resume Sync] Active sub changed → saving index:', idx)
          _patchProject(pid, { last_subtitle_index: idx })
        }, 1500)
      }
    }
  }
})