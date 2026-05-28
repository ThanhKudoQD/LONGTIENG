/**
 * useSimpleWebSocket — kết nối WS `/ws/{project_id}` và nhận events kind='simple'.
 *
 * BE broadcast 1 event mỗi khi background task có tiến độ:
 *
 *   {
 *     kind: 'simple',
 *     section: 'bible' | 'batches' | 'review',
 *     task_id: 'bible.part.3',
 *     phase: 'started' | 'progress' | 'done' | 'error',
 *     ref: { part_index?: number, batch_index?: number, group_index?: number },
 *     data?: BibleState | TranslateState | ReviewState,   // state mới
 *     message?: string,
 *     error?: string,
 *   }
 *
 * Usage:
 *   useSimpleWebSocket(projectId, {
 *     onBibleUpdate: (state) => setBible(state),
 *     onTranslateUpdate: (state) => setTranslate(state),
 *     onReviewUpdate: (state) => setReview(state),
 *     onMessage: (msg) => console.log(msg),
 *   })
 */
import { useEffect, useRef } from 'react'
import type { BibleState, TranslateState, ReviewState } from '../types'

export interface SimpleEvent {
  kind: 'simple'
  section: 'bible' | 'batches' | 'review' | 'issues'
  task_id: string
  phase: 'started' | 'progress' | 'done' | 'error'
  ref: Record<string, any>
  data?: any
  message?: string
  error?: string
  ts?: string
}

export interface SimpleWebSocketHandlers {
  onBibleUpdate?: (state: BibleState) => void
  onTranslateUpdate?: (state: TranslateState) => void
  onReviewUpdate?: (state: ReviewState) => void

  /** Mọi event đều gọi (chứa raw event). Dùng để hiển thị toast/log. */
  onEvent?: (event: SimpleEvent) => void

  /** Khi 1 task lỗi. */
  onError?: (event: SimpleEvent) => void

  /** Khi WS mất kết nối hoặc reconnect. */
  onConnectionChange?: (connected: boolean) => void
}

export function useSimpleWebSocket(
  projectId: number,
  handlers: SimpleWebSocketHandlers,
) {
  // Lưu handlers vào ref để không cần restart WS mỗi khi callback thay đổi
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers

  useEffect(() => {
    if (!projectId) return

    let ws: WebSocket | null = null
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null
    let closed = false

    const connect = () => {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      // BE mount app vào /dub, ws router register tại /dub/ws/{pid}
      const url = `${proto}://${window.location.host}/dub/ws/${projectId}`

      ws = new WebSocket(url)

      ws.onopen = () => {
        handlersRef.current.onConnectionChange?.(true)
      }

      ws.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data)
          if (event.kind !== 'simple') return  // Bỏ qua events của pipeline khác

          handlersRef.current.onEvent?.(event)

          // Phase=error → callback riêng
          if (event.phase === 'error') {
            handlersRef.current.onError?.(event)
          }

          // Khi có state mới (data), dispatch theo section
          if (event.data) {
            switch (event.section) {
              case 'bible':
                handlersRef.current.onBibleUpdate?.(event.data)
                break
              case 'batches':
                handlersRef.current.onTranslateUpdate?.(event.data)
                break
              case 'review':
                handlersRef.current.onReviewUpdate?.(event.data)
                break
            }
          }
        } catch (err) {
          console.error('[useSimpleWebSocket] parse error', err, e.data)
        }
      }

      ws.onerror = () => {
        // Để onclose xử lý reconnect
      }

      ws.onclose = () => {
        handlersRef.current.onConnectionChange?.(false)
        if (!closed) {
          // Reconnect sau 2s
          reconnectTimer = setTimeout(connect, 2000)
        }
      }
    }

    connect()

    return () => {
      closed = true
      if (reconnectTimer) clearTimeout(reconnectTimer)
      try {
        ws?.close()
      } catch {}
    }
  }, [projectId])
}
