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
  activeSubId: number | null
  selectedIds: Set<number>

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
}

let userSelectedUntil = 0

const useStore = create<EditorStore>((set, get) => ({
  project: null,
  subtitles: [],
  characters: [],
  activeSubId: null,
  selectedIds: new Set(),
  seekRequest: null,
  lastTtsAt: 0,

  // Stub — thực tế đọc/ghi qua usePlayTimeStore. Setter forward bên dưới.
  playTime: 0,
  setPlayTime: (t: number) => usePlayTimeStore.getState().setPlayTime(t),

  setProject: (p) => set({ project: p }),
  setSubtitles: (s) => set({ subtitles: s }),
  setCharacters: (c) => set({ characters: c }),

  setActiveSubId: (id) => {
    const sub = get().subtitles.find(s => s.id === id)
    userSelectedUntil = Date.now() + 1000
    set({
      activeSubId: id,
      selectedIds: new Set(id ? [id] : []),
      seekRequest: sub ? { time: sub.start_time, id: Date.now() } : null,
    })
  },

  setActiveSubIdFromVideo: (id) => {
    if (get().activeSubId === id) return
    set({ activeSubId: id })
  },

  toggleSelect: (id, multi = false, range = false, visibleIds?) => {
    const { selectedIds, subtitles, activeSubId } = get()
    const pool = visibleIds ?? subtitles.map(s => s.id)
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
    const [proj, subs, chars] = await Promise.all([
      api.get(`/projects/${projectId}`).then(r => r.data),
      api.get(`/subtitles/project/${projectId}`).then(r => r.data),
      api.get(`/characters/project/${projectId}`).then(r => r.data),
    ])
    set({
      project: proj,
      subtitles: subs,
      characters: chars,
      activeSubId: null,
      selectedIds: new Set(),
    })
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
