# 🏗️ Architecture — SRT Translator v2

Tài liệu giải thích lý do thiết kế từng phần. Đọc khi muốn customize sâu.

## Triết lý cốt lõi

### 1. "Hiểu trước, dịch sau"

Hầu hết tool dịch SRT đều dịch tuần tự dòng-1, dòng-2, dòng-3... Vấn đề: dòng 5 nói gì phụ thuộc dòng 1-4. Tool không có context → dịch sai cảm xúc, sai xưng hô.

Pipeline này khác: **đọc cả phim trước, lập Bible (nhân vật, bối cảnh, cốt truyện), rồi mới dịch**.

### 2. "Dịch theo phân cảnh"

Đơn vị dịch không phải 1 dòng, không phải 10 dòng, mà là **1 phân cảnh kịch**:
- 1 địa điểm
- 1 mốc thời gian
- 1 nhóm nhân vật
- 1 mục đích kịch

AI thấy CẢ MẠCH HỘI THOẠI nên biết: dòng này đang giận hay đang dỗ, đang mỉa hay đang khen.

### 3. "Mỗi stage một việc"

Cũ: 1 prompt khổng lồ làm cả speaker + translate + QC → AI lú lẫn, kết quả tệ.

Mới: 5 stage tách biệt:
1. **Bible** — chỉ trích xuất thông tin phim
2. **Scenes** — chỉ chia phân cảnh
3. **Speaker** — chỉ gán speaker
4. **Translate** — chỉ dịch (đã có speaker + scene)
5. **Polish** — chỉ tinh chỉnh CPS + consistency

Mỗi stage có prompt riêng, model riêng, có thể debug riêng.

## Pipeline data flow

```
┌──────────────────────────────────────────────────────────┐
│  INPUT                                                    │
│  - SRT tiếng Trung (~1500-1800 dòng cho short drama 2h)   │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  STAGE 1: BIBLE                                           │
│  ├─ 1A. Cast (Gemini Pro) — đọc cả SRT                    │
│  ├─ 1B. World + Story Arcs (Gemini Pro)                   │
│  ├─ 1C. Glossary (Gemini Pro)                             │
│  └─ 1D. Genre Pack matcher (local logic)                  │
│  OUTPUT: bible.json                                       │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  STAGE 2: SCENES                                          │
│  - Đọc Bible + SRT, chia thành 150-250 phân cảnh          │
│  - Mỗi cảnh có: location, characters, emotion, arc        │
│  - (Gemini Flash — task này không cần creativity)         │
│  OUTPUT: scenes.json                                      │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  STAGE 3: SPEAKER                                         │
│  - Per-scene: gán speaker cho mỗi dòng                    │
│  - Song song 5 calls cùng lúc                             │
│  - Confidence: high/mid/low                               │
│  - low confidence → flag review                           │
│  OUTPUT: dict line_idx → {speaker, confidence}            │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  STAGE 4: TRANSLATE  ← TRÁI TIM                           │
│  - Per-scene: dịch cả mạch hội thoại                      │
│  - Input có:                                              │
│    · Bible (cached)                                       │
│    · Scene context (location, emotion, purpose)           │
│    · Address matrix (ai gọi ai gì)                        │
│    · Glossary terms relevant                              │
│    · 5 few-shot examples kinh điển                        │
│  - Output có: text_vi, speaker_vi, emotion, intensity     │
│  OUTPUT: dict line_idx → {text_vi, emotion, ...}          │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  STAGE 5: POLISH                                          │
│  ├─ 5A. CPS Condense — rút gọn dòng vượt CPS              │
│  ├─ 5B. Consistency — quét per-character xuyên phim       │
│  └─ 5C. Glossary Enforcement — quét tên sai               │
│  OUTPUT: lines + polish_report                            │
└──────────────────────────────────────────────────────────┘
                          ↓
┌──────────────────────────────────────────────────────────┐
│  OUTPUT FILES                                             │
│  - <name>.vi.srt        — SRT tiếng Việt cuối             │
│  - <name>.bible.json    — Hồ sơ phim                      │
│  - <name>.scenes.json   — Scene map                       │
│  - <name>.review_queue.csv  — Dòng cần check tay          │
│  - <name>.full.csv      — Bảng full debug                 │
│  - <name>.polish_report.json — Báo cáo QC                 │
│  - <name>.cost.txt      — Chi phí API                     │
└──────────────────────────────────────────────────────────┘
```

## Bible — 3 phần độc lập

### 1A. Cast — Hồ sơ nhân vật

Cho mỗi nhân vật:
- **zh + vi + aliases**: tên Trung, Hán Việt, biệt danh
- **role**: nam_chinh/nu_chinh/nam_phu/nu_phu/phan_dien/phu/khach
- **gender, age_group, social_status**
- **personality + speaking_style**: tính cách + kiểu nói đặc trưng
- **self_address (Pronouns)**: cách tự xưng theo TÌNH HUỐNG:
  - `default`: mặc định
  - `when_angry`: khi giận
  - `when_intimate`: khi thân mật
  - `when_formal`: khi trang trọng
- **addresses**: cách gọi từng nhân vật khác (map zh_name → cách gọi)
- **relationships**: quan hệ với từng nhân vật khác

→ Stage 4 dùng `self_address` + `addresses` để build **Address Matrix** cho mỗi scene.

### 1B. World — Bối cảnh + Story Arcs

- **genre_main**: đô thị / cổ trang / dân quốc / tiên hiệp / võ hiệp / huyền huyễn / khoa huyễn
- **genre_sub**: ngôn tình / trọng sinh / báo thù / cung đấu / tổng tài / chiến thần / hắc đạo / ...
- **era, setting**: thời đại, không gian
- **plot_summary, main_conflict, tone_overall**
- **story_arcs**: 3-6 đoạn cốt truyện lớn

→ Story arcs giúp Stage 2 group các scene liên quan, Stage 4 biết "đây là arc báo thù" để tone đúng.

### 1C. Glossary — Thuật ngữ riêng phim

KHÔNG phải từ điển Trung-Việt phổ thông. Chỉ các thuật ngữ **riêng của phim này**:
- Tổ chức trong phim
- Địa danh riêng
- Chức vụ / tước hiệu cụ thể
- Vật phẩm tên riêng
- Biệt danh / nickname
- Khái niệm thể loại (kim đan, nguyên anh, độ kiếp...)
- Cliché câu thoại

→ Mỗi entry có `vi` (cách dịch chuẩn) + `notes` (khi nào dùng khác).

### 1D. Genre Pack — Thư viện thể loại

Genre Pack = "preset" cho thể loại đã quen thuộc, **kế thừa** cho phim cùng thể loại.

Mỗi pack chứa:
- `tone_signature`: tone tổng thể
- `typical_pronouns`: map tình huống → cặp xưng hô
- `common_terms`: thuật ngữ phổ biến trong thể loại
- `common_cliches`: cliché thoại
- `translation_examples`: 5 few-shot examples
- `style_notes`: ghi chú style

5 pack có sẵn:
- `modern_ceo_romance` (Tổng tài đô thị)
- `reborn_revenge` (Trọng sinh báo thù)
- `war_god_return` (Chiến thần trở về)
- `mafia_lord` (Hắc đạo bá đạo)
- `ancient_palace` (Cung đấu cổ trang)

Stage 1D tự match Genre Pack theo `genre_main` + `genre_sub`, sau đó MERGE `common_terms` + `common_cliches` vào Bible.glossary.

## Address Matrix — Cốt lõi của xưng hô đúng

Đây là cách hệ thống tránh dịch nhầm "anh-em" thành "tôi-cậu" hoặc ngược lại.

Với mỗi scene, Stage 4 BUILD động một ma trận:

```
Cố Trầm Châu (nam_chinh, nam) → Tô Niệm (nu_chinh, nu): "tôi-em" (default)
Tô Niệm (nu_chinh, nu) → Cố Trầm Châu (nam_chinh, nam): "em-anh" (default)
Cố Trầm Châu → Cố Tân: "anh-em" (default — anh em ruột)
Cố Tân → Cố Trầm Châu: "tôi-anh" (default)

⚠️ Cảnh giận/lạnh: có thể chuyển sang 'tôi-cô' hoặc 'tao-mày' nếu cao trào.
```

Ma trận này được EMBED vào prompt Stage 4, AI phải tuân theo.

## CPS Management

CPS (Characters Per Second) = số ký tự / giây của 1 dòng SRT.
- Quá cao → đọc không kịp
- Netflix: max 17
- Short drama (màn hình điện thoại): max **15** (chặt hơn)

Pipeline xử lý 2 lớp:
1. **Stage 4** đã được hướng dẫn: câu Việt phải có độ dài tương đương câu Trung (±20%) → đa số sẽ vừa
2. **Stage 5A** rút gọn các dòng vẫn vượt 15 CPS, batch 10 dòng/call

Sau Stage 5A, nếu vẫn vượt 18 CPS (emergency) → flag review tay.

## TTS-Friendly Translation

Vì pipeline phục vụ LỒNG TIẾNG, không chỉ làm sub, prompt yêu cầu:
- **Câu tròn**: không cụt cộc "Hả?" → "Cái gì cơ?"
- **Đủ chủ ngữ**: không "Đi đâu?" → "Cô đi đâu?"
- **Độ dài match**: câu Việt độ dài tương đương câu Trung để TTS phát đúng nhịp
- **Tránh từ khó phát âm**: hạn chế Hán Việt nặng trong tone đời thường

## Confidence Tracking

Mỗi dòng có:
- `speaker_confidence`: high/mid/low (từ Stage 3)
- `needs_review`: bool (tổng hợp từ nhiều nguồn)
- `review_reason`: string giải thích

`needs_review=True` khi:
- Speaker confidence = low
- CPS vẫn vượt sau khi rút gọn
- Có issue high-confidence từ Stage 5
- Untranslated (dòng bị bỏ sót)

→ Tất cả vào file `<name>.review_queue.csv` để bạn check tay.

## Cost Optimization

Cost mỗi phim phụ thuộc model:
- Gemini 2.5 Pro: ~$1.30/phim
- Gemini 2.5 Flash: ~$0.30/phim
- DeepSeek-V3: ~$0.50/phim (với cache 90% off)

Pipeline đã set:
- **Heavy stages** (Bible, Translate): Gemini 2.5 Pro — cần chất lượng
- **Medium stages** (Scenes, Speaker, Consistency): Gemini 2.5 Flash — rẻ
- **Light stages** (CPS Condense): Gemini 2.5 Flash

Override qua CLI:
```bash
python run.py translate --model gemini-2.5-flash  # Tất cả Flash
python run.py translate --provider deepseek --model deepseek-chat
```

## Customization Points

| Việc muốn làm | Edit file |
|--------------|-----------|
| Đổi style dịch tổng thể | `prompts/v2/translate_scene.txt` |
| Thêm quy tắc Hán Việt | `prompts/v2/bible_cast.txt` |
| Thêm thể loại mới | Tạo `genre_packs/<id>.json` mới |
| Thay đổi CPS limit | `config.py` → `PROJECT_TYPES` |
| Thêm idiom dịch | `prompts/v2/translate_scene.txt` section C, D |
| Đổi cách chia scene | `prompts/v2/scene_detect.txt` |
| Speaker khắt khe hơn | `prompts/v2/speaker.txt` — thêm sanity check |
| Polish khắt khe hơn | `prompts/v2/polish_consistency.txt` |

## Limitations & Future Work

**Phase 1 (hiện tại):**
- Text-based speaker (không dùng audio/video)
- 1 lần dịch xong là final (không iterate)

**Phase 2 (tương lai):**
- Audio fusion: dùng Pyannote diarization để verify text-based speaker
- Visual: dùng face detection để hỗ trợ scene detection
- Back-translation QC: dịch ngược Việt → Trung để check fidelity
- Bible incremental: kế thừa Bible giữa các phim cùng series
- Active learning: học từ user corrections trong review queue
