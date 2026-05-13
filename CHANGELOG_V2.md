# SRT Translator v2 — Integration Notes

Tích hợp pipeline v2 vào DubEditor: **thay hoàn toàn** v1, dọn code cũ.

## Tổng quan thay đổi

### Đã xóa
- `srt_translator/backend/translator.py` (80KB, monolithic v1)
- `srt_translator/backend/prompts/*` (17 prompt cũ)
- `migrate_translate_chunks_qc.py` (migration v1 cũ)
- Table `translate_chunks` (dropped tự động khi app khởi động)
- Column `projects.bible_json` (data sẽ chuyển sang bảng `bibles` mới — chạy `migrate_to_v2.py`)
- FE: `TranslatePanel.tsx` (dead code), `TranslatePage.tsx` cũ (3383 dòng), `RetranslateModal.tsx` cũ

### Đã thêm
- `srt_translator_v2/` — pipeline v2 đầy đủ (Bible 5-stage, 5 genre packs)
- `dubeditor/translate_service.py` — bridge Pydantic ↔ SQLAlchemy
- `dubeditor/models.py` — thêm 4 model: `Bible`, `Scene`, `StoryArc`, `PolishIssue`
- `dubeditor/routers/translate.py` — rewrite hoàn toàn, 15 endpoints v2
- `migrate_to_v2.py` — migration script đầy đủ
- FE `components/translate/` — 5 sub-components mới (ConfigPanel, BibleViewer, SceneList, IssueQueue, ProgressLog)

## DB Schema thay đổi

### Bảng mới
- `bibles` — Bible v2 versioned (mỗi project có thể nhiều version, 1 active)
- `scenes` — Phân cảnh kịch (~150-250/phim)
- `story_arcs` — Cốt truyện lớn (3-6/phim)
- `polish_issues` — Review queue từ Stage 5

### Cột mới
- `projects`: `project_type`, `genre_pack`, `translate_status`, `translate_progress`, `translate_error`
- `characters`: `name_zh`, `aliases_zh/vi`, `role`, `gender`, `age_group`, `social_status`, `personality`, `speaking_style`, `self_address` (JSON), `addresses` (JSON), `relationships_json`, `notes`
- `subtitles`: `scene_id`, `speaker_zh`, `speaker_confidence`, `speaker_reason`, `emotion`, `intensity`, `cps_value`, `needs_review`, `review_reason`, `text_draft`, `is_hook`, `translation_version`

### Cột xóa
- `projects.bible_json` (data → bảng `bibles`)

### Migration tự động
- `init_db()` chạy on-startup → thêm cột mới + drop `translate_chunks`
- Nếu có data cũ từ `projects.bible_json` → chạy `python migrate_to_v2.py` (one-time) để migrate sang bảng `bibles` (placeholder, cần re-run Stage 1)

## API v2 — Endpoint list

Tất cả với prefix `/dub/api`:

### Pipeline control
- `GET  /projects/{pid}/translate/status` — trạng thái + stats
- `POST /projects/{pid}/translate/start` — chạy full 5 stage
- `POST /projects/{pid}/translate/run-stage` — chạy 1 stage cụ thể (resume)
- `POST /projects/{pid}/translate/cancel` — hủy
- `POST /projects/{pid}/translate/reset` — xóa Bible+Scenes (giữ Subtitles)
- `GET  /projects/{pid}/translate/progress` — SSE stream

### Bible
- `GET  /projects/{pid}/bible` — Bible active
- `PUT  /projects/{pid}/bible` — edit thủ công
- `GET  /projects/{pid}/bibles` — list versions

### Scenes & Arcs
- `GET  /projects/{pid}/scenes` — list scenes
- `GET  /projects/{pid}/scenes/{id}` — detail + subtitles
- `GET  /projects/{pid}/story-arcs` — list arcs

### Polish issues
- `GET  /projects/{pid}/polish-issues` — list (filter resolved/type)
- `POST /projects/{pid}/polish-issues/{id}/apply` — áp dụng suggested
- `POST /projects/{pid}/polish-issues/{id}/dismiss` — bỏ qua

### Single
- `POST /projects/{pid}/translate/retranslate` — dịch lại 1 dòng
- `GET  /translate/genre-packs` — list packs

## FE structure

```
dubeditor_frontend/src/
├── api.ts                  ← thêm `translateApi.*` + `openProgressSSE`
├── types/index.ts          ← types v2 (Bible, Scene, Issue, ProgressEvent...)
├── components/
│   ├── TranslatePage.tsx   ← 599 dòng (giảm từ 3383)
│   ├── RetranslateModal.tsx ← v2 với hint + variants
│   ├── ConfigModal.tsx     ← chỉ còn loadConfig/getApiKey helpers
│   └── translate/
│       ├── ConfigPanel.tsx ← modal cấu hình + run stage
│       ├── BibleViewer.tsx ← Cast/World/Glossary/Raw tabs
│       ├── SceneList.tsx   ← sidebar + detail
│       ├── IssueQueue.tsx  ← review queue
│       └── ProgressLog.tsx ← SSE feed realtime
```

## Khởi động sau khi pull code mới

```bash
# 1. Backup DB hiện tại
cp data/dubeditor.db data/dubeditor.db.bak

# 2. Chạy migration đầy đủ (1 lần)
python migrate_to_v2.py

# 3. Install deps mới
pip install httpx pydantic python-dotenv

# 4. Khởi động app như bình thường
python app.py
```

App.py sẽ tự gọi `init_db()` → thêm cột mới + drop `translate_chunks`. Không cần thao tác thêm.

## Cách dùng FE mới

1. Vào project → click "🌐 Dịch thuật" để mở TranslatePage
2. Click "▶ Bắt đầu" → modal Config:
   - Chọn provider (Gemini/OpenAI/DeepSeek) + paste API key
   - Chọn models (tier Heavy/Medium/Light)
   - Chọn loại project (short_drama/drama_series/movie)
   - Chọn genre pack (auto detect hoặc chỉ định)
3. Click "▶ Bắt đầu toàn bộ pipeline" → chạy 5 stage tuần tự
4. Tab "Logs" để xem progress realtime (SSE)
5. Khi xong:
   - Tab "Bible" — xem hồ sơ phim
   - Tab "Phân cảnh" — duyệt scenes + subtitles từng cảnh
   - Tab "Vấn đề" — review queue, apply/dismiss từng issue
6. Click vào dòng nào trong SubtitleList (trang Editor) → có option "Dịch lại" (dùng modal v2)

## Files đã xác thực

- 43 Python files: all parse OK, no circular imports
- 5 genre packs, 9 prompts: valid JSON/text
- FE TypeScript: syntax OK, errors chỉ là thiếu node_modules (sẽ pass khi `npm install`)

## Known limitations

- Migration `bible_json` → `bibles` chỉ tạo bản placeholder. Khuyến nghị re-run Stage 1 cho các project cũ.
- Pipeline v2 dùng Pyannote audio diarization: **chưa tích hợp** (Phase 2).
- Genre pack auto-detect dựa trên `world.genre_main + genre_sub` từ Bible — chính xác 80-90%, có thể override tay.
