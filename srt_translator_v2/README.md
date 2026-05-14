# SRT Translator v3

Pipeline dịch SRT tiếng Trung → tiếng Việt **dành cho LỒNG TIẾNG** (TTS VoxCPM).

## Triết lý

> "Hiểu phim trước. Dịch sau."

Pipeline 5 stages:

1. **Bible** — phân tích phim, lập hồ sơ nhân vật + bối cảnh + thuật ngữ
2. **Chunks + Scenes** — chia phim thành chương (chunk) lớn rồi cảnh con
3. **Speaker** — gán speaker cho mỗi dòng thoại
4. **Translate** — dịch theo chunk với **2 bản** (sát nghĩa + thoát ý) + sliding window
5. **Retry** — code-based scan dòng còn TQ / rỗng, retry

## Cấu trúc 3 tầng (mới v3)

```
Story (Phim)
├── Arc 1 ("Hôn nhân hợp đồng")           ← cốt truyện lớn
│   ├── Chunk 1.1 ("Lần đầu gặp gỡ")      ← chương kịch
│   │   ├── Scene 1 (office, tense)        ← cảnh con
│   │   ├── Scene 2 (hospital, sad)
│   │   └── Scene 3 (bedroom, intimate)
│   └── Chunk 1.2 ("Ký hợp đồng")
└── Arc 2 ("Phát triển tình cảm")
```

## 2 bản dịch (mới v3)

Mỗi dòng có thể có 2 bản:

- **text_v1** — *sát nghĩa*: dịch sát cấu trúc Trung, phù hợp subtitle
- **text_v2** — *thoát ý*: dịch theo cách người Việt nói tự nhiên, phù hợp lồng tiếng

Cấu hình `variant.mode`:
- `off` — chỉ 1 bản
- `important_only` (mặc định) — chỉ cảnh quan trọng có 2 bản (HOOK/PEAK/intimate/angry)
- `always` — mọi dòng có 2 bản

## Lưu ý LỒNG TIẾNG

- Câu phải **tròn, đủ chủ ngữ** (cho TTS)
- KHÔNG tạo câu dưới 1 giây (TTS lỗi giọng)
- Câu rút phải có ≥ 4-5 âm tiết
- CPS max cho lồng tiếng: 22 (cao hơn subtitle thường vì TTS chỉnh speed được)

## Sử dụng CLI

```bash
# Full pipeline
python run.py translate \
    --input movie.srt \
    --output-dir ./out \
    --provider gemini \
    --api-key YOUR_KEY

# Với variant 2 bản cho mọi dòng
python run.py translate --input movie.srt --output-dir ./out --variant always

# Với DeepSeek (rẻ nhất + giỏi tiếng Trung)
python run.py translate \
    --input movie.srt --output-dir ./out \
    --provider deepseek --api-key sk-... \
    --model-heavy deepseek-chat --model-medium deepseek-chat
```

## Output

```
out/
├── bible.json          # Bible đầy đủ (cast, world, glossary)
├── chunks.json         # Cấu trúc chunks + scenes
├── translation.json    # Bản dịch chi tiết (cả 2 variants)
├── movie_vi_v1.srt     # SRT bản sát nghĩa
├── movie_vi_v2.srt     # SRT bản thoát ý (nếu có)
└── polish_report.json  # Issues còn lại (nếu có)
```

## Cost ước tính

Phim 6000 dòng:

| Provider | Cost | Notes |
|---|---|---|
| Gemini Pro | ~$2.0 | Chất lượng cao, cached prefix giảm 50% |
| Gemini Flash | ~$0.6 | Cân bằng |
| DeepSeek | ~$0.4 | Rẻ nhất, hiểu TQ tốt |

So với v2 cũ (~$5-7): giảm 3-5x.

## Tài liệu thêm

- `ARCHITECTURE.md` — chi tiết kiến trúc
- `prompts/v3/` — toàn bộ prompts dùng cho LLM
