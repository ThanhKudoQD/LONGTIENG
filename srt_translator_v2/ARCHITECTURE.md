# Architecture v3

## Tổng quan

Pipeline 5 stages tuần tự, mỗi stage có thể chạy độc lập (resume):

```
SRT → [Stage 1: Bible] → bible.json
   └→ [Stage 2: Chunks+Scenes] → chunks.json (lồng arc/chunk/scene)
      └→ [Stage 3: Speaker] → speaker_map per line
         └→ [Stage 4: Translate] → text_v1 + text_v2 per line
            └→ [Stage 5: Retry] → fix dòng thiếu/còn TQ
```

## Models (Pydantic)

### Bible (compact)

```python
Bible
├── cast: Cast
│   └── characters: list[Character]
│       ├── zh: str          # 顾沉舟
│       ├── vi: str          # Cố Trầm Châu (Hán Việt)
│       ├── alias: list[str]
│       ├── g: 'nam'|'nu'|'?'
│       ├── role: 'nam_chinh'|'nu_chinh'|'nam_phu'|'nu_phu'|'phan_dien'|'phu'|'khach'
│       ├── age: '20s'|'30s'|...
│       ├── char: str        # 1 câu tính cách + kiểu nói
│       ├── rel: dict[zh_name → quan hệ]
│       └── catchphrase: optional str
├── world: World
│   ├── genre: list[str]     # ['đô thị', 'tổng tài', 'ngôn tình']
│   ├── era: str             # 'hiện đại'|'cổ đại'|...
│   ├── tone: str            # 1 câu tone tổng thể
│   ├── plot: str            # 3-5 câu cốt truyện
│   └── arcs: list[StoryArc]
│       └── index, r=(start, end), t (title), tone
└── glossary: Glossary
    └── terms: list[GlossaryTerm]
        └── zh, vi, n (số lần), note (optional)
```

**Đã BỎ so với v2:**
- `Character.self_address` (Pronouns)
- `Character.addresses` (dict cách gọi)
- `Character.social_status`
- `Character.speaking_style` (gộp vào `char`)
- `World.main_conflict`, `World.setting` (gộp vào `plot`)

**Lý do:** xưng hô KHÔNG hardcode trong prompt mà để AI quyết định theo ngữ cảnh (rel + emotion + glossary xưng hô thể loại).

### Chunks + Scenes (cấu trúc 3 tầng)

```python
ChunkMap
└── chunks: list[Chunk]
    ├── r: (start_line, end_line)
    ├── t: str               # title chunk
    ├── arc_index: int       # thuộc arc nào
    └── scenes: list[Scene]  # rỗng nếu chunk ≤ 100 dòng
        ├── r: (start, end)
        ├── ch: list[str]    # characters_present (zh)
        ├── e: emotion
        ├── loc: location
        └── tag: 'HOOK'|'PEAK'|None
```

### Translation

```python
SubtitleLine
├── index, start_time_sec, end_time_sec
├── text_zh: str
├── text_v1: str | None     # sát nghĩa
├── text_v2: str | None     # thoát ý (nullable)
├── variant_selected: 1|2   # user chọn bản nào active
├── speaker_zh, speaker_vi
├── emotion, intensity
├── cps_value
└── is_hook, is_emotion_peak
```

## Stage 1 — Bible

**3 sub-calls** (1A tuần tự, 1B+1C song song):

- **1A Cast** (heavy model, ~30s, ~$0.05) — trích xuất nhân vật từ toàn bộ SRT
- **1B World** (medium, ~10s, ~$0.01) — genre/era/plot/arcs
- **1C Glossary** (medium, ~10s, ~$0.01) — thuật ngữ riêng + xưng hô thể loại

Total: ~$0.07 (Gemini Pro+Flash).

## Stage 2 — Chunks + Scenes (1 call/arc)

Mỗi arc → 1 call AI trả về cả chunks + scenes lồng nhau:

```json
{
  "chunks": [
    {
      "r": [1, 250],
      "t": "Lần đầu gặp gỡ",
      "scenes": [
        [1, 35, ["顾沉舟","苏念"], "tense", "office"],
        [36, 80, ["苏念","李华"], "sad", "hospital"],
        [81, 250, ["顾沉舟","苏念"], "intimate", "bedroom", "PEAK"]
      ]
    }
  ]
}
```

**Output compact**: scenes là array thay vì dict → tiết kiệm ~70% token output.

5 arcs phim 6000 dòng = 5 calls song song. Total: ~$0.10 (Flash).

## Stage 3 — Speaker (per chunk)

1 call/chunk:
- Input: nhân vật trong arc, scenes của chunk, thoại chunk
- Output: `[[line_idx, speaker_zh, confidence h/m/l], ...]` compact

Phim 6000 dòng ~25 chunks → 25 calls (concurrency 5). Total: ~$0.15.

**Checkpoint:** sau mỗi chunk xong → callback `on_chunk_done` để DubEditor save DB. Fail giữa chừng vẫn giữ progress.

## Stage 4 — Translate (heart of pipeline)

### Per chunk processing

```python
async def process_one_chunk(chunk, ...):
    # 1. Build context blocks
    characters_in_chunk = format_characters_in_chunk(chunk, bible)
    relationships = format_relationships(chunk, bible)
    glossary_chunk = format_glossary_chunk(chunk, entries, bible)
    scenes_in_chunk = format_scenes_in_chunk(chunk)
    
    # 2. Sliding window (30-50 dòng overlap)
    context_before = format_context(chunk.start - overlap, chunk.start - 1)
    context_after = format_context(chunk.end + 1, chunk.end + overlap)
    
    # 3. Cached prefix split tại "PHẦN BIẾN — CONTEXT CHUNK"
    cached_prefix = prompt[:marker_idx]  # Bible + rules, giữ nguyên xuyên phim
    variable = prompt[marker_idx:]       # context riêng chunk
    
    # 4. Call LLM với cached_prefix
    resp = await call_llm(req, cached_prefix=cached_prefix)
    
    # 5. Parse + filter variant (theo config.variant.mode)
    # 6. Checkpoint save DB
```

### 2 bản dịch (text_v1 + text_v2)

Variant config:

- `off`: chỉ text_v1
- `important_only` (mặc định): tạo v2 cho dòng quan trọng:
  - Dòng ≥ 5 ký tự TQ
  - Scene tag HOOK/PEAK
  - Emotion: intimate/angry/shocked/sad/fearful
  - Intensity ≥ 7
- `always`: mọi dòng

### Sliding window — KHÔNG ép copy xưng hô

Context trước/sau dùng để:
- ✅ Hiểu mạch cảnh (tiếp tone scene đang dở)
- ✅ Reference glossary đã dùng (term/tên nhất quán)
- ❌ KHÔNG ép giữ xưng hô — xưng hô shift theo emotion từng dòng

### Cached prefix

Gemini explicit cache + OpenAI prompt cache: phần Bible + rules (~3-5K tokens) cache 1 giờ → 25 chunks chỉ trả $1/lần đầu, sau đó cache hit giảm 75-90%.

Cost ước tính (phim 6000 dòng):
- Không cache: ~$3-4 (Pro)
- Có cache: ~$1.5-2 (Pro)

## Stage 5 — Retry (đơn giản hóa)

**Đã BỎ:**
- ~~5A CPS condense (AI rút câu vượt CPS)~~
- ~~5B Consistency check (AI quét xưng hô per character)~~
- ~~5C Glossary enforcement (AI rephrase)~~

**Chỉ giữ code-based:**

```python
for line in all_subtitles:
    if has_chinese_chars(line.text_active):  # regex [\u4e00-\u9fff]
        flag_retry(line)
    elif not line.text_active.strip():
        flag_retry(line)
    elif line.text_active.startswith("[CHƯA DỊCH"):
        flag_retry(line)
```

Retry batch 10 dòng/call dùng Flash. Cost: ~$0.05.

**Lý do đơn giản hóa:** với pipeline mới (Bible compact + chunk overlap + 2 variants), drift xảy ra ít. Nếu cần consistency check thì user review tay.

## Configuration

```python
PipelineConfig:
├── cps: target=17, max=22, condense_threshold=22
├── chunk: target_lines=300, overlap_lines=30, max_chunks_per_arc=8
├── variant: mode='important_only', min_chars=5, important_intensity_min=7
├── compact: auto_threshold_subs=500, combine_b2_b3=False
├── cache: enabled=True, min_tokens_to_cache=1024
├── concurrency: bible=3, chunks=5, speaker=5, translate=5, polish=5
└── models: heavy=gemini-2.5-pro, medium=gemini-2.5-flash
```

`auto_tune_for_size(total_subs)` tự điều chỉnh:
- < 500 subs: bật compact mode (gộp B2+B3), chunk 250 dòng, overlap 20
- 500-1500: chunk 250, overlap 30
- 1500-3000: chunk 300, overlap 40
- > 3000: chunk 400, overlap 50, concurrency 7

## Checkpoint mechanism

```python
@dataclass
class PipelineCallbacks:
    on_stage1_done: (Bible) → None
    on_stage2_done: (ChunkMap) → None
    on_stage3_chunk_done: (dict) → None
    on_stage4_chunk_done: (dict) → None
    on_stage5_done: (PolishReport) → None
```

DubEditor inject callbacks để save DB sau mỗi chunk. Fail giữa Stage 4 (25 chunks) chỉ mất chunk đang chạy, không mất 24 chunk đã xong.

## Integration với DubEditor

`dubeditor/translate_service.py` cầu nối:

1. `db_subtitles_to_srt_entries()` — convert DB → SrtEntry
2. `save_bible_to_db()` — Cast/World/Glossary + sync DB Characters
3. `save_chunks_to_db()` — chunks + scenes table + cập nhật Subtitle.chunk_id/scene_id
4. `save_translations_to_db()` — text_v1, text_v2, variant_selected=1 mặc định
5. `TranslateRunner.run_full()` — orchestrate + checkpoints

## API endpoints (DubEditor)

```
GET    /projects/{pid}/translate/status   # bao gồm chunk_count, variants_count
POST   /projects/{pid}/translate/start    # full pipeline
POST   /projects/{pid}/translate/run-stage # 1 stage
POST   /projects/{pid}/translate/cancel
POST   /projects/{pid}/translate/reset
GET    /projects/{pid}/translate/progress  # SSE

GET    /projects/{pid}/bible
PUT    /projects/{pid}/bible
GET    /projects/{pid}/bibles              # list versions

GET    /projects/{pid}/chunks              # v3 NEW
GET    /projects/{pid}/chunks/{id}         # v3 NEW
GET    /projects/{pid}/scenes
GET    /projects/{pid}/story-arcs

POST   /projects/{pid}/subtitles/{id}/select-variant       # v3 NEW
POST   /projects/{pid}/subtitles/bulk-select-variant       # v3 NEW

POST   /projects/{pid}/translate/retranslate # trả new_text_v1 + new_text_v2

GET    /projects/{pid}/polish-issues
POST   /projects/{pid}/polish-issues/{id}/apply
POST   /projects/{pid}/polish-issues/{id}/dismiss
```

## So với v2

| | v2 | v3 |
|---|---|---|
| Số calls/phim 6000 dòng | ~200 | ~70 |
| Cost (Gemini Pro) | $5-7 | $2 |
| Cost (DeepSeek) | $1-1.5 | $0.5 |
| Bible structure | Heavy (self_address/addresses) | Compact (char + rel) |
| Cấu trúc | Arc + Scene (2 tầng) | Arc + Chunk + Scene (3 tầng) |
| Variant | 1 bản | 2 bản (v1/v2) |
| Sliding window | ❌ | ✅ 30-50 dòng |
| Cached prefix | ❌ | ✅ |
| Checkpoint | ❌ | ✅ per chunk |
| Polish | 5 sub-stages AI | Code retry only |
| Genre Pack | Hardcoded files | Gộp vào Glossary AI |
