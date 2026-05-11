/**
 * Keyboard shortcut helpers cho gán nhanh nhân vật.
 *
 * Format: "1", "q", "Shift+1", "Shift+q"...
 * Match: parseShortcut(event) -> "1" hoặc "Shift+1"
 *
 * Phím hợp lệ: 0-9, a-z (case-insensitive), có thể prefix "Shift+"
 */

const VALID_KEYS = /^([0-9]|[a-zA-Z])$/

export function parseShortcutFromEvent(e: KeyboardEvent): string | null {
  // Bỏ qua nếu có Ctrl/Alt/Meta (để dành cho shortcuts khác)
  if (e.ctrlKey || e.altKey || e.metaKey) return null

  const key = e.key
  if (!VALID_KEYS.test(key)) return null

  const lower = key.toLowerCase()
  return e.shiftKey ? `Shift+${lower}` : lower
}

/**
 * Hiển thị shortcut đẹp: "1" -> "1", "Shift+1" -> "⇧1", "q" -> "Q"
 */
export function formatShortcut(s: string | null | undefined): string {
  if (!s) return ''
  if (s.startsWith('Shift+')) {
    return '⇧' + s.slice(6).toUpperCase()
  }
  return s.toUpperCase()
}

/**
 * Default sequence khi auto-assign cho nhân vật mới.
 * 1-9, 0, q-p, a-l, z-m
 */
const DEFAULT_SEQUENCE = [
  '1','2','3','4','5','6','7','8','9','0',
  'q','w','e','r','t','y','u','i','o','p',
  'a','s','d','f','g','h','j','k','l',
  'z','x','c','v','b','n','m',
]

export function nextAvailableShortcut(usedKeys: Set<string>): string | null {
  // Thử default sequence trước
  for (const k of DEFAULT_SEQUENCE) {
    if (!usedKeys.has(k)) return k
  }
  // Thử Shift+ với cùng sequence
  for (const k of DEFAULT_SEQUENCE) {
    const sk = `Shift+${k}`
    if (!usedKeys.has(sk)) return sk
  }
  return null
}

/**
 * Kiểm tra phím hợp lệ
 */
export function isValidShortcut(s: string): boolean {
  if (!s) return false
  if (s.startsWith('Shift+')) {
    return VALID_KEYS.test(s.slice(6))
  }
  return VALID_KEYS.test(s)
}
