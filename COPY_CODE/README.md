# Fix v8 — Múi giờ render + Xóa project xóa luôn video

## 📝 Trả lời câu hỏi

**Video xuất ra lưu ở đâu?**
- Trên server: `/home/dmin/nano/data/projects/_exports/export_{project_id}_{job_id}.mp4`
- URL truy cập: `http://localhost:8809/dub/exports/export_X_Y.mp4`
- File ASS subtitle phụ trợ (cùng folder): `sub_{project_id}_{job_id}.ass`

**Xóa project có xóa video output?**
- **Trước fix này**: KHÔNG (BE chỉ glob `{pid}_*`, không khớp `export_{pid}_*`)
- **Sau fix này**: CÓ, xóa tất cả file:
  - Video output `export_{pid}_*.mp4`
  - ASS subtitle `sub_{pid}_*.ass`
  - Row `export_jobs` trong DB

## 🐛 2 fix

### 1. Bug múi giờ "render từ 07:00:00"
**Nguyên nhân**: BE `datetime.utcnow().isoformat()` → `"2026-05-29T07:14:23.123"` (KHÔNG có `Z`). JS `new Date(s)` parse như **local time** thay vì UTC → ở VN sai 7h.

**Fix**:
- BE: append `'Z'` vào isoformat → `"2026-05-29T07:14:23.123Z"` (đánh dấu UTC)
- FE: `parseIsoAsUtc()` robust — nếu string KHÔNG có timezone suffix (Z hoặc ±HH:MM), tự động thêm `Z` (giả định UTC). Cover được cả data cũ trong DB.

### 2. Xóa project KHÔNG xóa video output
**Nguyên nhân**: `delete_project` glob pattern cũ `{pid}_*` không khớp file mới `export_{pid}_*.mp4`.

**Fix**:
- Thêm pattern `export_{pid}_*` và `sub_{pid}_*`
- Xóa row `export_jobs` trong DB (FK đến project)

## 📁 Files

```
dubeditor/export/service.py             ← BE: ISO + Z suffix trong broadcast
dubeditor/routers/export_video.py       ← BE: ISO + Z suffix trong API response
dubeditor/routers/projects.py           ← BE: xóa luôn export files khi delete project
dubeditor_frontend/src/components/export/RenderQueuePanel.tsx  ← FE: parseIsoAsUtc()
```

## 📦 Cài đặt

```bash
unzip -o fix_timezone_delete.zip -d /tmp/fix_v8/
cd /tmp/fix_v8 && bash install_fix.sh
cd /home/dmin/nano && python app.py        # restart BE
cd /home/dmin/nano/dubeditor_frontend && npm run build
```

## 🧪 Test

### Múi giờ
1. Bấm Render → counter `⏱` phải bắt đầu từ `0s`, KHÔNG phải `7g 00p 00s`
2. Để chạy 30s → counter hiện `30s` đúng
3. Xong → tổng thời gian render đúng

### Xóa project
1. Render 1 vài video → các file `export_17_*.mp4` xuất hiện
2. Vào Editor → xóa project 17
3. Check filesystem:
   ```bash
   ls /home/dmin/nano/data/projects/_exports/ | grep _17_
   # Không còn file nào
   ```
4. Check DB:
   ```bash
   sqlite3 /home/dmin/nano/data/dubeditor.db "SELECT id FROM export_jobs WHERE project_id=17"
   # Empty (không còn row)
   ```
