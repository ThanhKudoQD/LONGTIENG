# Tích hợp Dịch thuật AI vào DubEditor

## Những thay đổi trong bản này

### Backend
- `dubeditor/models.py` — thêm `original_text` (Subtitle), `bible_json` + `source_lang` (Project)
- `dubeditor/database.py` — migration tự động cho 3 column mới
- `dubeditor/schemas.py` — thêm fields + 3 schema mới (TranslateAnalyzeRequest, TranslateRunRequest, RetranslateRequest)
- `dubeditor/routers/translate.py` — **router mới** với 7 endpoints
- `dubeditor/router.py` — include translate router

### Frontend
- `src/types/index.ts` — thêm `original_text`, `Bible`, `TranslateProgress` types
- `src/components/TranslatePanel.tsx` — **component mới**: drawer dịch thuật
- `src/components/RetranslateModal.tsx` — **component mới**: modal dịch lại 1 dòng
- `src/components/Editor.tsx` — thêm nút 🌐 Dịch + TranslatePanel
- `src/components/SubtitleList.tsx` — hiện `original_text` + nút Dịch lại
- `src/components/ProjectList.tsx` — badge "Đã dịch" nếu has_bible

## Cài đặt thêm

### 1. Tích hợp module dịch
Copy thư mục `backend/` của dự án SRT Translator vào:
```
srt_translator/
  backend/
    translator.py     ← file chính
    prompts/          ← thư mục prompt
```

### 2. Chạy migration DB
Server tự migrate khi khởi động. Hoặc chạy thủ công:
```bash
python migrate_db.py
```

### 3. Khởi động như bình thường
```bash
python app.py
```

## Flow sử dụng

1. Tạo project → import SRT tiếng Trung
2. Bấm nút **🌐 Dịch** trên toolbar
3. Chọn provider + nhập API key + chọn model
4. **Pass 1** — AI phân tích phim → sinh Bible (nhân vật, xưng hô, scene_map)
5. Review Bible → **Pass 3** — dịch song song theo chunks
6. Subtitles tự động có: original_text (Trung) + text (Việt) + character gán sẵn
7. Click dòng bất kỳ → nút **✨ Dịch lại** → chọn bản mới

## Endpoints mới

| Method | Path | Mô tả |
|--------|------|--------|
| GET | `/dub/api/projects/{pid}/bible` | Lấy Bible đã lưu |
| POST | `/dub/api/projects/{pid}/translate/analyze` | Pass 1 — phân tích |
| POST | `/dub/api/projects/{pid}/translate/run` | Pass 3 — dịch |
| GET | `/dub/api/projects/{pid}/translate/progress` | SSE stream |
| POST | `/dub/api/projects/{pid}/translate/retranslate` | Dịch lại 1 dòng |
| POST | `/dub/api/projects/{pid}/translate/cancel` | Hủy job |
| POST | `/dub/api/projects/{pid}/translate/reset` | Reset bản dịch |
