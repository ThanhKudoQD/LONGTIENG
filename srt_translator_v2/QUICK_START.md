# 🚀 QUICK START

## 1. Cài đặt

```bash
cd srt_translator_v2/
pip install -r requirements.txt
```

Yêu cầu: Python 3.10+

## 2. Lấy API key

Vào https://aistudio.google.com/apikey để lấy Gemini API key (free tier có).

Hoặc dùng DeepSeek (rẻ + hiểu tiếng Trung tốt): https://platform.deepseek.com

## 3. Đặt key

```bash
cp .env.example .env
# Mở .env và điền key
```

## 4. Chạy thử với SRT mẫu

```bash
python run.py translate \
  --input examples/sample.srt \
  --output-dir ./output \
  --provider gemini
```

Pipeline sẽ chạy qua 5 stage và tạo ra:
- `output/sample.vi.srt` — SRT tiếng Việt
- `output/sample.bible.json` — Hồ sơ phim
- `output/sample.scenes.json` — Phân cảnh
- `output/sample.review_queue.csv` — Các dòng cần review tay
- `output/sample.full.csv` — Full table debug
- `output/sample.cost.txt` — Báo cáo chi phí

## 5. Chạy phim thật của bạn

```bash
python run.py translate \
  --input /path/to/your_movie.srt \
  --output-dir ./output \
  --project-type short_drama \
  --genre-pack auto
```

## 6. Các lệnh hữu ích

```bash
# Xem stats SRT trước khi chạy (KHÔNG cần API)
python run.py stats --input movie.srt

# Liệt kê genre packs có sẵn
python run.py list-packs

# Chỉ chạy Stage 1 (Bible) để xem hệ thống hiểu phim thế nào
python run.py bible --input movie.srt --output bible.json

# Sau đó dùng bible đó cho Stage 2
python run.py scenes --input movie.srt --bible bible.json --output scenes.json

# Chỉ định genre pack cụ thể (khi auto detect sai)
python run.py translate \
  --input movie.srt \
  --genre-pack modern_ceo_romance
```

## 7. Genre packs có sẵn

| ID | Tên |
|----|-----|
| `modern_ceo_romance` | Tổng tài đô thị |
| `reborn_revenge` | Trọng sinh báo thù |
| `war_god_return` | Chiến thần trở về |
| `mafia_lord` | Hắc đạo bá đạo |
| `ancient_palace` | Cung đấu cổ trang |

## 8. Tinh chỉnh sau khi review

Sau khi xem output, có thể tinh chỉnh:

### Sửa Bible
Mở `output/<name>.bible.json`, sửa thủ công các trường:
- `cast`: thêm/sửa tên nhân vật, xưng hô
- `glossary`: thêm/sửa thuật ngữ riêng

Sau đó chạy lại từ Stage 2 với bible đã sửa:
```bash
python run.py scenes --input movie.srt --bible bible.json --output scenes.json
```

### Sửa prompts
Tất cả prompt đều ở `prompts/v2/*.txt`, edit text tự do.
- `translate_scene.txt`: prompt chính, edit để thay đổi style dịch
- `bible_cast.txt`: edit quy tắc đặt tên Hán Việt

### Thêm Genre Pack mới
Copy 1 file `genre_packs/*.json` rồi sửa theo thể loại mới.

## 9. Chi phí ước tính

Phim 60 tập × 2 phút (~1500 dòng) với Gemini 2.5 Pro + 2.5 Flash:
- Stage 1 (Bible): ~$0.10
- Stage 2 (Scenes): ~$0.05
- Stage 3 (Speaker): ~$0.20
- Stage 4 (Translate): ~$0.80
- Stage 5 (Polish): ~$0.15
- **Total: ~$1.30/phim**

Với DeepSeek-V3 (cache 90% off): ~$0.50/phim

## 10. Troubleshooting

### "No API key"
Set environment variable hoặc dùng `--api-key`:
```bash
export GEMINI_API_KEY=your_key
```

### "Cannot decode SRT file"
SRT của bạn dùng encoding khác. Parser tự thử utf-8, utf-8-sig, gbk, gb18030.
Nếu vẫn lỗi → convert bằng `iconv -f BIG5 -t UTF-8 input.srt > out.srt`.

### Pipeline chạy chậm
Tăng concurrency:
```bash
python run.py translate --input x.srt --concurrency 10
```
Lưu ý: Gemini free tier có rate limit thấp; với 5+ concurrent có thể bị 429.

### Tên dịch sai (vd: "Tống Niệm" thay vì "Tô Niệm")
- Edit `bible.json` thủ công
- Hoặc edit `prompts/v2/bible_cast.txt` để bổ sung quy tắc Hán Việt
- Hoặc đặt sẵn trong genre pack

## Kiến trúc

Xem `README.md` để hiểu pipeline 5-stage chi tiết.
