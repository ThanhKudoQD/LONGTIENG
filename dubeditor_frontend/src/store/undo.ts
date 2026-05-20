import { create } from 'zustand'

/**
 * UNDO STORE — Toast "Hoàn tác" 1 slot (như Gmail).
 *
 * Triết lý:
 *   - KHÔNG phải undo stack toàn cục.
 *   - Mỗi lần user thực hiện 1 action "có thể lỡ tay" (xóa audio, xóa sub, …)
 *     → push 1 entry vào đây. Entry mới sẽ overwrite entry cũ.
 *   - Hiện Toast ở góc trái dưới với label + countdown 8s.
 *   - Click "Hoàn tác" → gọi `restore()` (FE đã giữ data backup từ BE).
 *   - Hết countdown HOẶC user dismiss → clear, không undo được nữa.
 *
 * KHÔNG cần stack vì:
 *   - User chỉ quan tâm action gần nhất "lỡ tay".
 *   - Backup data trữ ở FE → giữ stack lớn sẽ phình RAM.
 *   - UX rõ ràng hơn: thấy toast → bấm hoặc bỏ qua.
 */

export const UNDO_TIMEOUT_MS = 8000

export interface UndoEntry {
  id:        number              // tăng dần, dùng cho key React + dedup timer
  label:     string              // hiển thị trên toast, vd "Đã xóa 3 audio"
  expiresAt: number              // Date.now() + UNDO_TIMEOUT_MS
  restore:   () => Promise<void> // gọi API + cập nhật FE store
  onExpire?: () => void          // optional: cleanup khi hết hạn (vd xóa cứng file)
}

interface UndoStore {
  current: UndoEntry | null

  /**
   * Đăng ký 1 undo mới. Tự overwrite entry cũ (gọi `onExpire` của entry cũ trước).
   * Trả về id của entry (để caller dedupe nếu cần).
   */
  push: (entry: Omit<UndoEntry, 'id' | 'expiresAt'>) => number

  /** Trigger restore + clear. */
  undo: () => Promise<void>

  /** Dismiss thủ công (X). KHÔNG gọi onExpire vì user chủ động bỏ. */
  dismiss: () => void
}

let _nextId = 1
let _expireTimer: ReturnType<typeof setTimeout> | null = null

const clearExpireTimer = () => {
  if (_expireTimer) { clearTimeout(_expireTimer); _expireTimer = null }
}

const useUndoStore = create<UndoStore>((set, get) => ({
  current: null,

  push: (entry) => {
    // Entry cũ chưa expire → coi như "user không undo nữa" → gọi onExpire ngay
    // (vd: BE đã soft-delete, ta cần xóa cứng file trong trash khi expire)
    const prev = get().current
    if (prev) {
      try { prev.onExpire?.() } catch (e) { console.warn('[Undo] prev.onExpire failed:', e) }
    }
    clearExpireTimer()

    const id = _nextId++
    const next: UndoEntry = {
      id,
      expiresAt: Date.now() + UNDO_TIMEOUT_MS,
      ...entry,
    }
    set({ current: next })

    // Auto-expire
    _expireTimer = setTimeout(() => {
      const cur = get().current
      if (cur && cur.id === id) {
        try { cur.onExpire?.() } catch (e) { console.warn('[Undo] onExpire failed:', e) }
        set({ current: null })
      }
      _expireTimer = null
    }, UNDO_TIMEOUT_MS)

    return id
  },

  undo: async () => {
    const cur = get().current
    if (!cur) return
    clearExpireTimer()
    set({ current: null })
    try {
      await cur.restore()
    } catch (e) {
      console.error('[Undo] restore failed:', e)
      // Có thể show toast lỗi ở đây, nhưng giữ đơn giản trước
    }
  },

  dismiss: () => {
    clearExpireTimer()
    set({ current: null })
  },
}))

export default useUndoStore