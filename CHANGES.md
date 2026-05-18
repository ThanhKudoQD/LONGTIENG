# v3.9 — Editor Resume + Translate Log Persistence

## Tóm tắt

Giải quyết 3 vấn đề:

1. **TTS tất cả** chỉ áp cho đoạn đang được active (đã có sẵn, chỉ cần sync khái niệm "active chapter").
2. **Mở lại project** tự động restore: filter chapter + scroll đến sub đang làm dở.
3. **Pipeline translate** giữ log + LLM history khi F5 / back về Editor; dialog "Tiếp tục từ Stage X hay Chạy lại" khi có data dở.

## Danh sách file đã sửa (10 file)

### Backend (5 file)

```
dubeditor/models.py                    +2 cột Project, +2 model LLMCall/PipelineEvent
dubeditor/database.py                  Migration 2 cột mới
dubeditor/schemas.py                   +field ProjectOut, +next_stage TranslateStatusOut
dubeditor/routers/projects.py          PATCH whitelist 2 field mới, GET parse JSON
dubeditor/routers/translate.py         Wire log persist, +3 endpoint, +next_stage logic
```

### Frontend (5 file)

```
dubeditor_frontend/src/types/index.ts                    +field Project/TranslateStatus
dubeditor_frontend/src/api.ts                            +listEvents/listLlmCalls/clearLogs
dubeditor_frontend/src/store/index.ts                    Auto-sync filter/active → BE
dubeditor_frontend/src/components/Editor.tsx             Restore filter+sub khi load
dubeditor_frontend/src/components/TranslatePage.tsx      Load history, dialog resume
```

**File `dubeditor/llm_log_service.py` giữ nguyên** — đã có sẵn trong project, chỉ cần wire vào.

## Cách áp dụng

Copy đè 10 file theo đúng cấu trúc thư mục trong `changes/` (tương ứng với project gốc).

Sau khi copy:
- Backend: restart `app.py` (uvicorn). Migration sẽ tự động chạy lần đầu nhờ `_migrate_v3()` trong `database.py`.
- Frontend: rebuild Vite (`npm run build`) hoặc reload dev server.

## Kiểm tra migration

Lần đầu chạy sau khi áp, kiểm tra DB đã có cột mới:

```bash
sqlite3 data/dubeditor.db ".schema projects" | grep last_
# Phải thấy:
#   last_filter_chapter_ids TEXT
#   last_subtitle_index     INTEGER

sqlite3 data/dubeditor.db ".tables" | grep -E "llm_calls|pipeline_events"
# Phải thấy 2 table mới
```

## Cách test từng phần

### Phần 1 — TTS tất cả theo đoạn active

1. Mở project, vào Editor.
2. Tick 1 chapter trong dropdown filter → list chỉ hiện sub của chapter đó.
3. Bấm "🎙 TTS tất cả" → button hiện "Tạo TTS (đoạn đang lọc)" và confirm "Sẽ tạo TTS cho N dòng trong đoạn đang lọc".
4. Tick thêm 1 chapter nữa (2 chapter cùng lúc) → TTS bulk chỉ áp 2 đoạn này.

### Phần 2 — Resume khi mở lại

1. Trong Editor, tick filter 2 chapter bất kỳ, scroll xuống sub 235 và click chọn.
2. **Đợi 2 giây** (cho debounce sync xong) — mở DevTools/Network sẽ thấy PATCH `/projects/{id}` với `last_filter_chapter_ids` và `last_subtitle_index`.
3. Bấm "← Back" về ProjectList rồi mở lại project.
4. Kết quả mong đợi: filter 2 chapter được tick lại; sub 235 active + auto-scroll tới.

**Test fallback:**
- Xóa 1 trong 2 chapter đã tick → mở lại → chỉ chapter còn lại được active.
- Xóa toàn bộ chapter đã tick → mở lại → clear filter, active sub đầu phim.
- Xóa subtitle 235 (nếu có thể) → mở lại → fallback active sub đầu của filter (hoặc sub đầu phim).

### Phần 3 — Translate logs persist + resume

**3a. Logs persist:**

1. Vào trang Translate, bấm "▶ Bắt đầu" chạy pipeline.
2. Đợi Stage 1 Bible chạy được vài LLM call (xem tab Logs có event + LLM calls).
3. **F5** trang. Kết quả: tab Logs vẫn hiện toàn bộ event + LLM call đã chạy trước F5. SSE tiếp tục nhận event mới.
4. Bấm "Back" về Editor rồi vào lại Translate. Kết quả: log vẫn còn.

**3b. Cancel giữ data:**

1. Đang chạy giữa Stage 2 (Chunks), bấm "⏸ Cancel" (nút màu đỏ).
2. Dialog cảnh báo hiện: API call đang dở sẽ bị hủy thô, dữ liệu Stage đã xong vẫn giữ.
3. OK → pipeline dừng, status đổi về "idle".
4. **Tab Bible** vẫn còn data Stage 1, **tab Chunks** có data 1 phần (nếu Stage 2 đã save chunk nào).

**3c. Resume dialog:**

1. Sau khi Cancel ở 3b, bấm "▶ Tiếp tục / Chạy lại" (nút tự đổi label vì `can_resume=true`).
2. Mở ConfigPanel, sửa config nếu muốn, bấm Start.
3. Dialog hiện 2 lựa chọn:
   - **OK** → Tiếp tục từ Stage 2 (Chunks). Pipeline chạy `run-stage` thay vì full.
   - **Cancel** → Confirm phá huỷ 1 lần nữa → Reset (xóa Bible/Chunks/Logs) → chạy full pipeline.

**3d. Clear logs riêng:**

1. Sau khi có log + LLM history, bấm nút "🗑 Clear logs".
2. Confirm → log + LLM history bị xóa, Bible/Chunks/Translations KHÔNG ảnh hưởng.

## Lưu ý kỹ thuật

### Debounce auto-sync ở `store/index.ts`

Mỗi lần user đổi `filterChapterIds` hoặc `activeSubId`, store debounce trước khi PATCH:
- `filterChapterIds`: 500ms
- `activeSubId`: 1500ms

Nếu user click sub liên tục, chỉ PATCH 1 lần ở lần dừng cuối → tiết kiệm HTTP calls.

### Cờ `_resumeApplied` quan trọng

Khi mở project, store reset `filterChapterIds: []` và `activeSubId: null` (default). Nếu cứ tự động sync ngay → sẽ ghi `[]`/`null` đè data DB.

Cờ `_resumeApplied` tắt sync cho đến khi Editor gọi `markResumeApplied()` SAU KHI restore xong từ DB. Lúc đó sync mới bật, ghi nhận các thay đổi user thực sự làm.

### Rolling buffer LLM logs

`llm_log_service.py` cap 200 LLM calls + 500 events / project. Cũ nhất tự xóa khi vượt cap. Không lo DB phồng.

### `prompt_full` vs `prompt_preview`

Endpoint `/translate/llm-calls` trả cả `prompt_full` (đầy đủ) và `prompt_preview` (truncate 2000 chars). UI ProgressLog hiện đang dùng `prompt_preview` — đủ cho hiển thị. Nếu sau này muốn xem full, thêm nút "Show full" trong UI.

### Cancel "hủy thô"

Theo yêu cầu của bạn, cancel KHÔNG đợi LLM call in-flight save xong → log của call cuối có thể bị mất. Đã có warning trong dialog confirm. Tradeoff: cancel nhanh, không treo.

## Rủi ro / Lưu ý khi triển khai

1. **Cột mới khác kiểu trong DB cũ**: nếu trước đây bạn từng tự thêm cột `last_subtitle_index`/`last_filter_chapter_ids` với type khác, migration sẽ skip (vì `add_col` chỉ thêm nếu chưa tồn tại). Kiểm tra schema sau khi áp.

2. **Browser cache**: sau khi rebuild FE, hard-refresh (Ctrl+Shift+R) để load JS mới — nếu không, store cũ vẫn chạy.

3. **2 dòng `_lora_config` đè nhau trong `app.py`** vẫn là code chết, không liên quan tới change này.

4. **Reset xóa logs**: nếu bạn không muốn Reset xóa logs (giữ history debug), comment dòng `clear_logs(db, pid)` trong `routers/translate.py` reset endpoint.
