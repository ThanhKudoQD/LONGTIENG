# v3.10 — Đổi genre_packs từ JSON → TXT (rule + glossary)

## Tóm tắt

Thay 5 file JSON (`modern_ceo_romance / ancient_palace / reborn_revenge / mafia_lord / war_god_return`) bằng **4 file TXT theo bối cảnh** (`co_trang / dan_quoc / do_thi / tien_hiep`).

## File thay đổi (4 file)

### 1. Thêm mới: 4 file txt trong `genre_packs/`
```
xung_ho_co_trang.txt
xung_ho_dan_quoc.txt
xung_ho_do_thi.txt
xung_ho_tien_hiep.txt
```

### 2. `stages/stage1_bible.py`
- Đổi enum `VALID_GENRE_IDS` sang 4 bối cảnh + "other"
- Thêm `LEGACY_GENRE_MAP` để Bible cũ tự động map sang id mới khi load lại

### 3. `prompts/v3/bible_world.txt`
- Đổi danh sách `genre_id` từ 6 thể loại cũ → 5 bối cảnh mới
- Sửa JSON mẫu: `modern_ceo_romance` → `do_thi`
- Sửa checklist: "6 giá trị" → "5 giá trị"

### 4. `stages/stage4_translate.py`
- `load_genre_pack()`: đọc file `xung_ho_{genre_id}.txt` thay vì `{genre_id}.json`, trả `str` thay vì `dict`
- `format_genre_pack_for_prompt()`: trả thẳng nội dung txt (đã có sẵn format đẹp), không format lại

## Không cần đụng

- `stages/stage5_polish.py` — chỉ import từ stage4, signature đổi từ `dict→str` nhưng cách dùng giống → tự động chạy đúng
- `prompts/v3/translate_chunk.txt` + `retry.txt` — placeholder `{GENRE_PACK}` giữ nguyên
- DB schema — `bible.world.genre_id` vẫn là string, chỉ giá trị enum đổi

## Cách áp dụng

1. Copy 4 file txt vào `srt_translator_v2/genre_packs/`
2. Copy đè 3 file code đã sửa (stage1_bible.py, stage4_translate.py, bible_world.txt)
3. **Optional**: xóa 5 file JSON cũ trong `genre_packs/` (không bắt buộc — load txt theo prefix `xung_ho_*` không xung đột)

## Test

1. Tạo project mới với phim cổ trang → Stage 1 Bible → kiểm tra `bible.world.genre_id == "co_trang"`
2. Stage 4 chạy → log phải có: `[Stage 4] Loaded genre pack: co_trang (NNN chars)`
3. Bible CŨ (genre_id=`ancient_palace`) → reload → auto-map sang `co_trang`, vẫn chạy được

## Rollback

Nếu chất lượng dịch giảm:
- Phục hồi 3 file code từ git
- 5 file JSON cũ vẫn còn (chưa xóa) → có thể chạy ngay
