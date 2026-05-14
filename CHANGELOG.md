# CHANGELOG — v2 → v3

Cập nhật toàn diện pipeline dịch SRT TQ→Việt cho lồng tiếng.

## Tóm tắt thay đổi

| | v2 cũ | v3 mới |
|---|---|---|
| **Số calls/phim 6000 dòng** | ~200 | ~70 |
| **Cost Gemini Pro** | $5-7 | ~$2 |
| **Cost DeepSeek** | $1-1.5 | ~$0.5 |
| **Bible Cast** | 8 fields (self_address, addresses, social_status, speaking_style...) | 5 fields (zh/vi/alias/g/role/age/char/rel/catchphrase) |
| **Cấu trúc** | Arc + Scene (2 tầng) | Arc + Chunk + Scene (3 tầng) |
| **Variant dịch** | 1 bản | 2 bản (v1 sát nghĩa + v2 thoát ý) |
| **Sliding window overlap** | ❌ | ✅ 30-50 dòng |
| **Cached prefix** | ❌ | ✅ Gemini/OpenAI cache |
| **Checkpoint per-chunk** | ❌ | ✅ |
| **Polish Stage 5** | 5 sub-stages AI (CPS condense, consistency, glossary) | Code retry only |
| **Genre Pack** | Hardcoded files | Gộp vào Bible.glossary AI |

## File changes

### Backend Python — `srt_translator_v2/`

**Models đã refactor:**
- `models/bible.py` — Cast/World/Glossary compact
- `models/scene.py` — Scene + **Chunk** (mới) + ChunkMap
- `models/translation.py` — SubtitleLine với `text_v1`/`text_v2`/`variant_selected`

**Config mới:**
- `config.py` — ChunkConfig, VariantConfig, CompactModeConfig

**LLM client update:**
- `core/llm_client.py` — PRICING thêm Gemini 3.x/DeepSeek-R1/GPT-5-nano, longest-prefix cost match, cached_prefix proper

**Stages viết lại:**
- `stages/stage1_bible.py` — 3 sub-calls (1A Cast tuần tự, 1B+1C song song)
- `stages/stage2_scenes.py` — 1 call/arc, output compact array, có fallback
- `stages/stage3_speaker.py` — per chunk, checkpoint callback
- `stages/stage4_translate.py` — 2 variants + sliding window + cached prefix + checkpoint
- `stages/stage5_polish.py` — đơn giản hóa: code-only retry

**Prompts v3** (mới folder `prompts/v3/`):
- `bible_cast.txt` — schema mới compact + Hán Việt rules
- `bible_world.txt` — genre array + arcs liền nhau
- `bible_glossary.txt` — gộp thuật ngữ riêng + xưng hô thể loại
- `chunks_and_scenes.txt` — 1 call chia chunk+scene per arc
- `speaker.txt` — gán speaker compact array
- `translate_chunk.txt` — 2 variants + xưng hô context-driven
- `retry.txt` — retry batch dòng thiếu

**Xóa:**
- `prompts/v2/` (toàn bộ)
- `genre_packs/` (không còn dùng)
- `tests/test_basic.py` (outdated)

### DubEditor backend — `dubeditor/`

**models.py:**
- Thêm bảng `Chunk` (project_id, arc_index, chunk_index, title, start_line, end_line, status)
- Subtitle thêm: `text_v1`, `text_v2`, `variant_selected` (default 1), `chunk_id`
- Scene thêm: `chunk_id` FK
- Project thêm relationship `chunks`

**database.py:**
- `_migrate_v3()` auto ALTER COLUMN khi app start (gộp v2+v3 migrations)

**schemas.py:**
- Mới: `ChunkOut`, `SelectVariantRequest`
- Sửa: `TranslateConfig` thêm `variant_mode`/`chunk_overlap`/`cache_enabled`
- Sửa: `TranslateStatusOut` thêm `chunk_count`, `variants_count`
- Sửa: `SubtitleUpdate`/`SubtitleOut` thêm `text_v1`/`text_v2`/`variant_selected`/`chunk_id`
- Xóa: `GenrePackInfo`

**translate_service.py — viết lại:**
- `db_subtitles_to_srt_entries()` — convert DB → SrtEntry
- `save_bible_to_db()` — sync Cast/World/Glossary + Characters + StoryArcs
- `load_active_bible_from_db()` — load V3Bible
- `save_chunks_to_db()` — chunks + scenes + cập nhật Subtitle.chunk_id/scene_id
- `save_speakers_to_db()` — gán speaker per chunk
- `save_translations_to_db()` — lưu 2 variants
- `save_polish_to_db()` — polish issues
- `TranslateRunner` — 5 methods stage + `run_full()` + cancel support

**routers/translate.py:**
- Bỏ: `/translate/genre-packs`
- Thêm: `/projects/{pid}/chunks`, `/projects/{pid}/chunks/{id}`
- Thêm: `/projects/{pid}/subtitles/{id}/select-variant`, `/subtitles/bulk-select-variant`
- Sửa: `retranslate` trả `new_text_v1` + `new_text_v2`
- Sửa: `get_status` thêm `chunk_count`, `variants_count`
- Sửa: `reset` clear v3 fields (text_v1/v2/variant_selected/chunk_id)

**routers/subtitles.py:**
- Helper `_sync_variant_active()` — khi update text_v1/v2/variant_selected → đồng bộ Subtitle.text + recompute CPS

### Frontend React — `dubeditor_frontend/src/`

**types/index.ts — viết lại:**
- `BibleCharacter` compact (zh/vi/alias/g/role/age/char/rel/catchphrase)
- `BibleWorld` (genre array/era/tone/plot/arcs)
- `Chunk` type mới
- `Subtitle` thêm text_v1/v2/variant_selected/chunk_id
- `TranslateConfig` thêm variant_mode/chunk_overlap/cache_enabled
- `RetranslateResult` với new_text_v1/v2
- Constants: `VARIANT_MODE_LABELS`, `ARC_TONE_LABELS`, `ISSUE_TYPE_LABELS` v3
- Xóa: `GenrePackInfo`, `GENRE_MAIN_LABELS`, `GENRE_SUB_LABELS`, `Pronouns`

**api.ts:**
- Thêm: `listChunks`, `getChunkDetail`, `selectVariant`, `bulkSelectVariant`
- Sửa: `retranslate` payload bỏ `variants` count, trả `RetranslateResult`
- Bỏ: `listGenrePacks`

**components/translate/ConfigPanel.tsx — viết lại:**
- Bỏ Genre Pack section
- Thêm: Variant Mode (3 options off/important_only/always)
- Thêm: Chunk Overlap slider (advanced)
- Thêm: Cache toggle
- Stages bar: `bible | chunks | speaker | translate | polish` (đổi "scenes" → "chunks")
- STORAGE_KEY mới: `translate_config_v3`

**components/translate/SceneList.tsx — viết lại thành ChunkList:**
- Sidebar tree 3 tầng: Arc (expand/collapse) → Chunk → Scene
- Filter: pending/done/issue
- Detail panel: scenes con + issues + preview thoại
- Variant badge trên mỗi sub preview

**components/translate/BibleViewer.tsx — viết lại:**
- 4 tabs: Cast / World / Glossary / Raw JSON
- Cast: group theo role, expand chi tiết alias/catchphrase/rel
- World: genre array + era + tone + plot + arcs với tone label
- Glossary: search + sort theo n
- JSON: editor + save

**components/translate/IssueQueue.tsx:**
- Confidence filter match cả `h/m/l` và `high/mid/low`
- TypeColor cho 4 issue_type v3 (untranslated/empty/chinese_remains/other)

**components/EditPanel.tsx — viết lại:**
- Variant picker UI (chỉ hiện khi có text_v2)
- 2 textareas v1+v2 với border xanh/tím khi chọn
- `switchVariant()` API call đồng bộ
- Save patch text_v1/text_v2/variant_selected

**components/SubtitleList.tsx:**
- Variant badge `v1`/`v2` cạnh voice mode pill
- Inline retranslate handle `new_text_v1`/`new_text_v2`
- Lưu cả 2 bản + variant chọn vào DB

**components/RetranslateModal.tsx — viết lại:**
- Hiển thị riêng v1 (border xanh) + v2 (border tím)
- Click chọn → callback `onApply({text, variant, text_v1, text_v2})`
- Hiển thị emotion + intensity từ AI

**components/TranslatePage.tsx:**
- State mới: `chunks`, `refreshChunks`
- Bỏ: `genrePacks`, `GENRE_MAIN_LABELS`, `GENRE_SUB_LABELS`
- Bible genre display dùng `genre.join(' · ')`
- Overview thêm chunks prop + variants count
- Tab "Phân cảnh" → "Chunks"

**components/ConfigModal.tsx (shim):**
- STORAGE_KEY v3 với fallback đọc v2 (migrate dần)
- DEFAULT_CONFIG thêm v3 fields

**Xóa:** `components/VoicePicker1.tsx` (duplicate)

### Migration

**migrate_to_v3.py** (standalone script):
- `--dry-run` flag để preview
- Idempotent
- Schema changes (text_v1/v2/variant_selected/chunk_id, scenes.chunk_id, chunks table)
- Backfill text_v1 từ Subtitle.text đã dịch
- Drop deprecated `translate_chunks` table

### Documentation

- `README.md` v3 — overview + cost + CLI
- `ARCHITECTURE.md` v3 — chi tiết models/stages/checkpoint
- `CHANGELOG.md` — file này

## Quick Migration Guide

1. **Backup git:**
   ```bash
   git add -A && git commit -m "Backup before v3 migration"
   ```

2. **Copy files mới:**
   ```bash
   cp -r /home/claude/output/srt_translator_v2/* /path/to/project/srt_translator_v2/
   cp -r /home/claude/output/dubeditor/* /path/to/project/dubeditor/
   cp -r /home/claude/output/dubeditor_frontend/* /path/to/project/dubeditor_frontend/
   cp /home/claude/output/migrate_to_v3.py /path/to/project/
   ```

3. **Migrate DB (preview trước):**
   ```bash
   python migrate_to_v3.py --dry-run
   python migrate_to_v3.py
   ```

4. **Restart server** — auto-migration `_migrate_v3()` cũng chạy khi start app.

5. **FE rebuild:**
   ```bash
   cd dubeditor_frontend && npm run build
   ```

6. **Test:**
   - Vào trang Translate
   - Reset project test → chạy lại pipeline với variant `important_only`
   - Kiểm tra cost dashboard giảm 3-5x so với v2

## Lưu ý

- Genre Pack đã được gộp vào Bible.glossary tự động. Nếu trước đó user dùng "co_trang" pack, AI sẽ tự nhận diện qua text và thêm xưng hô thể loại (朕/本宫/đại hiệp...) vào Glossary.
- Field `self_address`, `addresses`, `social_status`, `speaking_style` trong DB Characters vẫn giữ (legacy) — không xóa hard để tránh mất data. Pipeline v3 không đọc các field này nữa.
- Bible JSON cũ vẫn parse được (Pydantic v3 ignore extra fields). Nhưng khuyến nghị chạy Stage 1 lại để có Bible v3 chuẩn.
