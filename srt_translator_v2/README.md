# SRT Translator v2 — Pipeline dịch C-drama Trung → Việt

Hệ thống dịch phim Trung Quốc → tiếng Việt với chất lượng cao,
được thiết kế cho mục đích **lồng tiếng đa nhân vật**.

## Triết lý

1. **Hiểu phim trước, dịch sau** — Bible toàn phim trước khi dịch dòng nào.
2. **Dịch theo phân cảnh, không theo dòng** — AI thấy cả mạch hội thoại.
3. **Mỗi stage một nhiệm vụ duy nhất** — không nhồi, không kiêm nhiệm.
4. **TTS-friendly** — câu dịch phải nói được, không chỉ đọc được.
5. **CPS-aware** — sub phải đọc kịp trên màn hình.

## Pipeline 5 stage

```
SRT (ZH) → [1] Bible → [2] Scenes → [3] Speaker → [4] Translate → [5] Polish → SRT (VI)
```

| Stage | Mô tả | Số call API điển hình (1 phim 60 tập, ~1500 dòng) |
|-------|-------|---------------------------------------------------|
| 1. Bible | Đọc cả phim, lập hồ sơ nhân vật + bối cảnh + thuật ngữ | 4 |
| 2. Scenes | Chia phim thành 150-250 phân cảnh kịch | 1 |
| 3. Speaker | Gán nhân vật cho mỗi dòng (text-based) | ~150-250 |
| 4. Translate | Dịch theo phân cảnh, có cảm xúc + xưng hô | ~150-250 |
| 5. Polish | CPS condense + nhất quán xuyên phim | ~20-30 |

**Tổng:** ~325-535 calls/phim, ~$0.80-1.40/phim với prompt caching.

## Cấu trúc thư mục

```
srt_translator_v2/
├── core/              # Components dùng chung
│   ├── llm_client.py       # Unified Gemini/OpenAI/DeepSeek client + caching
│   ├── srt_parser.py       # Parse/build SRT, tính CPS
│   ├── token_counter.py    # Estimate tokens
│   └── pipeline.py         # Orchestrator chính
│
├── stages/            # 5 stage chính
│   ├── stage1_bible.py     # Cast + World + Glossary + Genre Pack
│   ├── stage2_scenes.py    # Scene detection
│   ├── stage3_speaker.py   # Speaker assignment
│   ├── stage4_translate.py # Translate per scene
│   └── stage5_polish.py    # CPS + Consistency
│
├── prompts/v2/        # Prompt templates (text files, dễ edit)
│   ├── bible_cast.txt
│   ├── bible_world.txt
│   ├── bible_glossary.txt
│   ├── scene_detect.txt
│   ├── speaker.txt
│   ├── translate_scene.txt
│   ├── cps_condense.txt
│   ├── polish_consistency.txt
│   └── polish_glossary.txt
│
├── genre_packs/       # Thư viện thể loại có sẵn (5 cái cốt lõi)
│   ├── modern_ceo_romance.json     # Tổng tài đô thị
│   ├── reborn_revenge.json         # Trọng sinh báo thù
│   ├── war_god_return.json         # Chiến thần trở về
│   ├── mafia_lord.json             # Hắc đạo bá đạo
│   └── ancient_palace.json         # Cung đấu cổ trang
│
├── models/            # Pydantic models cho I/O an toàn
│   ├── bible.py
│   ├── scene.py
│   └── translation.py
│
├── schemas/           # JSON Schema cho LLM output validation
│
├── examples/          # Sample SRT + expected output
│
├── tests/             # Test scripts
│
├── config.py          # Cấu hình chung
├── run.py             # CLI entry point
├── requirements.txt
└── README.md
```

## Cài đặt

```bash
cd srt_translator_v2/
pip install -r requirements.txt
```

## Sử dụng

### 1. Chạy toàn bộ pipeline

```bash
python run.py translate \
    --input /path/to/movie.srt \
    --output /path/to/movie_vi.srt \
    --provider gemini \
    --api-key YOUR_KEY \
    --genre auto
```

### 2. Chạy từng stage (debug)

```bash
# Chỉ Stage 1 — sinh Bible
python run.py bible --input movie.srt --output bible.json

# Stage 2 — scene detection
python run.py scenes --input movie.srt --bible bible.json --output scenes.json

# Stage 3 — speaker
python run.py speaker --input movie.srt --bible bible.json --scenes scenes.json --output speakers.json

# Stage 4 — translate
python run.py translate-only --input movie.srt --bible bible.json --scenes scenes.json --speakers speakers.json --output draft.srt

# Stage 5 — polish
python run.py polish --input draft.srt --bible bible.json --output final.srt
```

### 3. Tích hợp vào DubEditor (sau)

Sẽ có file `integration.py` để mount vào FastAPI router hiện tại.

## Provider hỗ trợ

| Provider | Models | Caching | Khuyên dùng |
|----------|--------|---------|-------------|
| **Gemini** | 2.5 Pro, 2.5 Flash | ✅ Context Cache (75% off) | Default — chất lượng + giá |
| **OpenAI** | GPT-5, GPT-5-mini | ✅ Auto prefix cache (50% off) | Backup |
| **DeepSeek** | DeepSeek-V3 | ✅ Auto context cache (90% off) | Rẻ nhất, hiểu TQ tốt |

## Roadmap

- [x] **Phase 1**: Pipeline dịch chuẩn (5 stage)
- [ ] **Phase 2**: Visual lip-sync cho Speaker (kết hợp Pyannote)
- [ ] **Phase 3**: Back-translation QC cho cảnh emotion peak
- [ ] **Phase 4**: Bible incremental update xuyên series

## License

Proprietary — Internal use only.
