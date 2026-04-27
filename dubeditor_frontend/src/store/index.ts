import { create } from 'zustand'
import { Project, Subtitle, Character } from '../types'
import api from '../api'

interface EditorStore {
  project: Project | null
  subtitles: Subtitle[]
  characters: Character[]
  activeSubId: number | null
  selectedIds: Set<number>
  playTime: number

  setProject: (p: Project) => void
  setSubtitles: (s: Subtitle[]) => void
  setCharacters: (c: Character[]) => void
  setActiveSubId: (id: number | null) => void
  setActiveSubIdFromVideo: (id: number | null) => void
  toggleSelect: (id: number, multi?: boolean, range?: boolean, visibleIds?: number[]) => void
  setPlayTime: (t: number) => void

  lastTtsAt: number
  updateSubtitle: (id: number, patch: Partial<Subtitle>) => void
  deleteSubtitle: (id: number) => void
  deleteAudio: (ids: number[]) => void
  markTTSDone: (id: number, audioPath: string) => void
  loadProject: (projectId: number) => Promise<void>

  seekRequest: { time: number; id: number } | null
  clearSeekRequest: () => void
}

// Timestamp đến khi setPlayTime không được override activeSubId
// (user vừa click sub hoặc bấm ↑↓)
let userSelectedUntil = 0

const useStore = create<EditorStore>((set, get) => ({
  project: null,
  subtitles: [],
  characters: [],
  activeSubId: null,
  selectedIds: new Set(),
  playTime: 0,
  seekRequest: null,

  setProject: (p) => set({ project: p }),
  setSubtitles: (s) => set({ subtitles: s }),
  setCharacters: (c) => set({ characters: c }),

  // User chủ động chọn sub → seek video + lock setPlayTime 1 giây
  setActiveSubId: (id) => {
    const sub = get().subtitles.find(s => s.id === id)
    userSelectedUntil = Date.now() + 1000  // lock 1 giây
    set({
      activeSubId: id,
      selectedIds: new Set(id ? [id] : []),
      seekRequest: sub ? { time: sub.start_time, id: Date.now() } : null,
    })
  },

  // Từ video timeupdate → chỉ update highlight
  setActiveSubIdFromVideo: (id) => {
    set({ activeSubId: id })
  },

  toggleSelect: (id, multi = false, range = false, visibleIds?) => {
    const { selectedIds, subtitles, activeSubId } = get()
    // Dùng visibleIds nếu có (filter đang active), không thì dùng tất cả
    const pool = visibleIds ?? subtitles.map(s => s.id)
    if (range && activeSubId) {
      const ids = pool
      const a = ids.indexOf(activeSubId), b = ids.indexOf(id)
      const lo = Math.min(a, b), hi = Math.max(a, b)
      set({ selectedIds: new Set(ids.slice(lo, hi + 1)), activeSubId: id })
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

  setPlayTime: (t) => {
    set({ playTime: t })

    // Nếu user vừa chọn sub thủ công → không override activeSubId
    if (Date.now() < userSelectedUntil) return

    const { subtitles } = get()
    if (!subtitles.length) return

    const started = subtitles.filter(s => s.start_time <= t)
    if (started.length > 0) {
      const active = started[started.length - 1]
      set({ activeSubId: active.id })
    } else {
      set({ activeSubId: null })
    }
  },

  clearSeekRequest: () => set({ seekRequest: null }),

  lastTtsAt: 0,
  updateSubtitle: (id, patch) => {
    set(state => ({
      subtitles: state.subtitles.map(s => s.id === id ? { ...s, ...patch } : s),
      lastTtsAt: (patch.tts_done || patch.audio_path) ? Date.now() : state.lastTtsAt
    }))
  },

  deleteAudio: (ids) => {
    set(state => ({
      subtitles: state.subtitles.map(s =>
        ids.includes(s.id) ? { ...s, tts_done: false, audio_path: null, wav_duration: null } : s
      )
    }))
  },
  deleteSubtitle: (id) => {
    set(state => ({
      subtitles: state.subtitles.filter(s => s.id !== id),
      selectedIds: new Set([...state.selectedIds].filter(sid => sid !== id)),
    }))
  },

  markTTSDone: (id, audioPath) => {
    set(state => ({
      subtitles: state.subtitles.map(s => s.id === id ? { ...s, tts_done: true, audio_path: audioPath } : s)
    }))
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
  }
}))

export default useStore