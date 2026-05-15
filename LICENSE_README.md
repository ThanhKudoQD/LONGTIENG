# LICENSE KEY SYSTEM — Hướng dẫn

Hệ thống license đơn giản — verify hoàn toàn LOCAL, không cần server.

## Cơ chế:

```
[Admin] → tạo RSA key pair (1 lần)
        ↓
[Admin] → có private_key.pem (GIỮ RIÊNG)
[App]   → có public_key.pem (NHÚNG VÀO CODE)
        ↓
[User]  → chạy app, lấy Machine ID, gửi cho admin
[Admin] → chạy keygen.py → tạo license bind với Machine ID
[User]  → nhập license → app verify chữ ký + machine + expire → chạy
```

## Setup lần đầu (chỉ admin):

### 1. Tạo cặp RSA key

```bash
cd <project_root>
openssl genrsa -out private_key.pem 2048
openssl rsa -in private_key.pem -pubout -out public_key.pem
```

→ Có 2 file: `private_key.pem` + `public_key.pem`

### 2. Nhúng public key vào code

Mở file `dubeditor/license_service.py`, tìm biến `PUBLIC_KEY_PEM`:

```python
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
REPLACE_WITH_YOUR_PUBLIC_KEY
-----END PUBLIC KEY-----"""
```

Mở `public_key.pem`, copy nội dung vào (giữ nguyên định dạng PEM).

### 3. Đảm bảo `private_key.pem` KHÔNG vào Git

Thêm vào `.gitignore`:
```
private_key.pem
*.pem
data/license.dat
```

### 4. Cài cryptography

```bash
pip install cryptography
```

## Cách dùng hàng ngày:

### Khi có user mới muốn dùng:

**Bước 1: User gửi Machine ID**
- User chạy app → màn hình License hiện ra → user copy Machine ID
- Gửi cho admin qua Telegram

**Bước 2: Admin tạo key**

```bash
python tools/keygen.py
```

Interactive:
```
Machine ID của user: abc123def456789
Số ngày key có hạn (vd 30): 30
Ghi chú (tên user): User A - Telegram @userA

✅ KEY ĐÃ TẠO:
eyJtIjoiYWJjMTIzZGVmNDU2Nzg5IiwiZSI6MTc1MzM5NTIwMCwibiI6IlVzZXIgQSJ9.MEUCIQDxxxx...
```

Hoặc CLI args:
```bash
python tools/keygen.py --machine abc123 --days 30 --note "User A"
```

**Bước 3: Gửi key cho user**
- Copy đoạn key dài → gửi qua Telegram
- User dán vào ô License Key → click "Kích hoạt"

## Cấu trúc key:

```
<payload_base64>.<signature_base64>
```

Payload:
```json
{
  "m": "abc123def456789",    // machine_id (hash hardware)
  "e": 1753395200,            // expire timestamp
  "n": "User A"               // ghi chú (optional)
}
```

Key dài khoảng 250-350 ký tự do RSA 2048-bit signature.

## Khi user hết hạn:

- App tự động khóa, hiển thị màn hình License
- User gửi Machine ID + báo admin → admin tạo key mới với days mới
- User nhập key mới → chạy tiếp

## Đổi máy:

- Key bind 1 máy duy nhất qua Machine ID
- Khi đổi máy: user gửi Machine ID mới → admin tạo key mới cho máy đó
- Key cũ tự động "vô hiệu" trên máy mới (không khớp Machine ID)

## Bảo mật:

| Layer | Mức độ |
|---|---|
| ✅ Chữ ký RSA 2048 | User không tự tạo key được |
| ✅ Bind Machine ID | Copy sang máy khác không dùng được |
| ✅ Expire check | Hết hạn tự khóa |
| ⚠️ User crack code | Có thể bypass nếu hack source Python |

→ Đủ tốt cho user thường. Hacker giỏi cần ~vài giờ để bypass.

## Để tăng cường (optional):

1. **Obfuscate code Python** bằng PyArmor
2. Verify ở nhiều chỗ trong code (không chỉ 1 middleware)
3. Compile code thành `.pyd` / `.so` bằng Cython
