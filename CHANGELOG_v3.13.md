# Changelog v3.13 — Retranslate per chunk

## Tóm tắt

Thêm chức năng **dịch lại 1 chunk** từ UI tab Chunks. Trước đây khi 1 chunk
trong Stage 4 bị lỗi (timeout, JSON parse fail, mất kết nối), user buộc phải
chạy lại toàn bộ Stage 4 cho cả phim — vừa tốn $, vừa có thể ghi đè các chunk
đã dịch tốt. Giờ user có thể:

1. Nhìn vào tab Chunks → thấy badge `❌ Lỗi` / `X dòng cần review` trên chunk có vấn đề
2. Click nút `🔄 Dịch lại chunk` ở header detail hoặc sidebar row
3. Chọn 1 trong 2 mode:
   - **Chỉ dịch lại dòng lỗi** (errors_only): tiết kiệm $, AI vẫn nhận full chunk làm context
   - **Dịch lại toàn bộ chunk** (all): khi muốn cải thiện chất lượng cả chunk
4. Xem stats real-time: cost, tokens, số dòng updated, số dòng còn lỗi

## Files thay đổi (6 files)

### Backend Python

#### 1. `dubeditor/schemas.py`
- **Thêm** class `RetranslateChunkRequest(TranslateConfig)` — kế thừa
  TranslateConfig để dùng lại logic build_pipeline_config + per-stage
  model/thinking + variant_mode.
- **Thêm** class `RetranslateChunkResponse` — stats chi tiết
- **Sửa** class `ChunkOut`: thêm `error_message`, `lines_with_errors`

#### 2. `dubeditor/translate_service.py`
- **Sửa** import từ `stages.stage4_translate`:
  thêm `process_one_chunk` và `load_prompt as load_stage_prompt`
- **Thêm** method `TranslateRunner.run_translate_chunk(chunk_id, mode)`:
  - Load Bible + ChunkMap + SpeakerMap từ DB (không gọi LLM)
  - Match V3Chunk qua range start_line/end_line
  - Nếu mode='errors_only': query subs có needs_review / rỗng / còn TQ / placeholder
  - Gọi `process_one_chunk` (reuse 100% logic Stage 4)
  - Filter result theo mode rồi `save_translations_to_db`
  - Update `Chunk.status` (`translating` → `done`/`translated`/`error`)
  - Track tokens/cost delta riêng cho lần retranslate này

#### 3. `dubeditor/routers/translate.py`
- **Sửa** import: thêm `RetranslateChunkRequest`, `RetranslateChunkResponse`
- **Sửa** `_db_chunk_to_out`: nhận thêm `lines_with_errors`, đưa
  `error_message` vào output
- **Sửa** `list_chunks`: compute `lines_with_errors` per chunk bằng 1 query
  gộp (không N+1)
- **Thêm** endpoint `POST /projects/{pid}/translate/retranslate-chunk`:
  - Conflict check với pipeline đang chạy
  - Validate api_key + chunk_id
  - Spawn task qua `asyncio.create_task` → cancel-friendly
  - Đăng ký vào `_active_runners` + `_active_tasks` (chia sẻ cancel infrastructure
    với pipeline run)
  - Trả về `RetranslateChunkResponse` với stats đầy đủ

### Frontend TypeScript

#### 4. `dubeditor_frontend/src/types/index.ts`
- **Sửa** `Chunk` interface:
  - status enum thêm `'translating'`
  - thêm `error_message?: string | null`
  - thêm `lines_with_errors?: number`
- **Thêm** `RetranslateChunkResult` interface

#### 5. `dubeditor_frontend/src/api.ts`
- **Sửa** import: thêm `RetranslateChunkResult`
- **Thêm** `translateApi.retranslateChunk(pid, payload)` — POST endpoint mới

#### 6. `dubeditor_frontend/src/components/translate/SceneList.tsx`
- **Thêm** helper `chunkStatusBadge(status)` — render badge theo status
- **Sửa** `Props`: thêm `onChunksRefresh?: () => void`
- **Sửa** main component:
  - State `retranslateModalFor`, `retranslatingChunkId`, `retranslateResult`
  - Filter type thêm `'error'`
  - Filter chip `❌ Chunks lỗi (N)` (chỉ hiện khi có chunks lỗi)
  - Logic filter: `c.status === 'error' || (c.lines_with_errors || 0) > 0`
- **Sửa** `ChunkSidebarRow`:
  - Props mới: `isRetranslating`, `onRetranslate`
  - Row 3: badge `⏳ Đang dịch lại` / `❌ Lỗi` / `N dòng cần review`
  - Nút `🔄` absolute top-right (visible on selected/hover)
- **Sửa** `ChunkDetail`:
  - Props mới: `isRetranslating`, `onRetranslate`
  - Header strip thêm status badge + lines-err badge
  - Banner đỏ hiện `error_message` nếu có
  - Nút `🔄 Dịch lại chunk` ở góc phải header
  - `useEffect` reload subs cũng phụ thuộc `isRetranslating` để auto-refresh
- **Thêm** `RetranslateChunkModal` component:
  - Radio button chọn mode (errors_only / all)
  - Ước tính cost dựa trên số dòng × $0.0006
  - Đọc config từ `localStorage.translate_config_v3` (cùng nguồn với
    ConfigPanel) — bao gồm provider, api_keys, model_stage4,
    thinking_stage4, variant_mode, chunk_overlap, cache_enabled
- **Thêm** Toast hiển thị kết quả retranslate (góc dưới phải)

#### 7. `dubeditor_frontend/src/components/TranslatePage.tsx`
- **Sửa** render `<SceneList>`: thêm prop `onChunksRefresh={refreshChunks}`

## Cách dùng

### Trigger từ UI
1. Vào tab **Chunks** trong Translate
2. Tìm chunk cần dịch lại (filter `❌ Chunks lỗi` để xem nhanh)
3. Click vào chunk → header detail → nút **🔄 Dịch lại chunk**
4. Hoặc click nút `🔄` ở góc trên phải row (visible khi selected hoặc hover)
5. Chọn mode trong modal → **Bắt đầu**

### Trigger từ API trực tiếp

```bash
curl -X POST http://localhost:8000/dub/api/projects/123/translate/retranslate-chunk \
  -H 'Content-Type: application/json' \
  -d '{
    "chunk_id": 45,
    "mode": "errors_only",
    "api_key": "AIza...",
    "provider": "gemini",
    "model_stage4": "gemini-2.5-pro",
    "thinking_stage4": true,
    "variant_mode": "important_only",
    "chunk_overlap": 30,
    "cache_enabled": true
  }'
```

Response:
```json
{
  "ok": true,
  "chunk_id": 45,
  "mode": "errors_only",
  "lines_in_chunk": 287,
  "lines_targeted": 8,
  "lines_updated": 8,
  "lines_v2": 3,
  "lines_still_error": 0,
  "cost_usd": 0.0123,
  "tokens_in": 9450,
  "tokens_out": 1280,
  "cached_tokens": 7200,
  "duration_ms": 18430
}
```

## Lợi ích phụ

- Endpoint mới chia sẻ `_active_runners` + `_active_tasks` → có thể dùng
  `POST /translate/cancel` để hủy retranslate đang chạy
- LLM observer tự động log call vào DB (`LLMCall`) → xem ở tab Logs
- Progress events stream qua SSE (`retranslate_chunk` → `retranslate_chunk_done`)
- `lines_with_errors` được compute trong `list_chunks` → ngay khi pipeline
  full vừa chạy xong, tab Chunks đã hiện rõ chunk nào còn vấn đề

## Không bị ảnh hưởng

- Pipeline full vẫn chạy y nguyên
- Retranslate per-line (1 dòng) + per-batch (1-5 dòng) vẫn hoạt động
- DB schema không thay đổi (Chunk.status đã có sẵn enum, error_message đã có column)
- Không thêm dependency mới

## Migration

Không cần migration. Tất cả field DB đã tồn tại từ v3.0.

## Test thủ công khuyến nghị

1. Chạy full pipeline cho 1 phim test → verify tab Chunks hiện đúng
   `lines_with_errors` cho từng chunk
2. Dùng DevTools chặn 1 LLM call để giả lập chunk lỗi → verify chunk
   status = error
3. Test mode `errors_only`: tạo vài dòng có TQ chưa dịch trong 1 chunk
   → click retranslate → verify chỉ những dòng đó được ghi đè
4. Test mode `all`: verify mọi dòng trong chunk đều có text_v1 mới
5. Test cancel: bắt đầu retranslate → click cancel → verify chunk status
   trở về error với message "Bị hủy"
6. Test pipeline conflict: chạy full pipeline → trong khi đang chạy bấm
   retranslate chunk → verify HTTP 409
