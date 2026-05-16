#!/usr/bin/env python3
"""
LICENSE KEY GENERATOR — chỉ admin (BẠN) chạy.

Cách dùng lần đầu (setup):
    # Tạo cặp RSA key (chỉ làm 1 lần)
    openssl genrsa -out private_key.pem 2048
    openssl rsa -in private_key.pem -pubout -out public_key.pem

    # Copy nội dung public_key.pem → paste vào
    #   dubeditor/license_service.py (biến PUBLIC_KEY_PEM)

    # GIỮ private_key.pem CHỈ Ở MÁY BẠN, KHÔNG SHARE

Cách dùng hàng ngày — tạo key cho user:
    python tools/keygen.py
    → Nhập Machine ID của user (user gửi qua Telegram)
    → Nhập số ngày
    → Nhập ghi chú (tên user)
    → Output key → copy gửi user

Hoặc dùng CLI args:
    python tools/keygen.py --machine abc123 --days 30 --note "User A"
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path


def create_key(machine_id: str, days: int, note: str, private_key_path: str) -> str:
    """Tạo license key signed bằng private RSA key."""
    try:
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes, serialization
    except ImportError:
        print("❌ Cần cài: pip install cryptography")
        sys.exit(1)

    priv_path = Path(private_key_path)
    if not priv_path.exists():
        print(f"❌ Không tìm thấy private key: {priv_path}")
        print("   Sinh key bằng: openssl genrsa -out private_key.pem 2048")
        sys.exit(1)

    # Sanitize note — loại bỏ ký tự không phải UTF-8 hợp lệ
    # (terminal đôi khi trả về surrogate khi gõ tiếng Việt)
    safe_note = (note or "").encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    # Tránh surrogate chars
    safe_note = "".join(c for c in safe_note if not (0xD800 <= ord(c) <= 0xDFFF))

    payload = {
        "m": machine_id.strip(),
        "e": int(time.time()) + days * 86400,
        "n": safe_note.strip(),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")

    priv = serialization.load_pem_private_key(priv_path.read_bytes(), password=None)
    sig = priv.sign(payload_bytes, padding.PKCS1v15(), hashes.SHA256())

    payload_b64 = base64.urlsafe_b64encode(payload_bytes).rstrip(b"=").decode()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()

    return f"{payload_b64}.{sig_b64}"


def format_expire_date(days: int) -> str:
    import datetime as dt
    d = dt.datetime.now() + dt.timedelta(days=days)
    return d.strftime("%d/%m/%Y %H:%M")


def main():
    ap = argparse.ArgumentParser(description="License Key Generator (BAN2_DICH)")
    ap.add_argument("--machine", help="Machine ID của user (16 ký tự hex)")
    ap.add_argument("--days", type=int, help="Số ngày key có hạn")
    ap.add_argument("--note", default="", help="Ghi chú (tên user, thông tin)")
    ap.add_argument("--private-key", default="private_key.pem",
                    help="Đường dẫn private RSA key (default: private_key.pem)")
    args = ap.parse_args()

    print("╔══════════════════════════════════════════════════════════╗")
    print("║   BAN2_DICH — LICENSE KEY GENERATOR (admin only)         ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Interactive mode nếu thiếu args
    machine = args.machine
    if not machine:
        machine = input("Machine ID của user: ").strip()
    if not machine:
        print("❌ Machine ID không được rỗng")
        sys.exit(1)

    days = args.days
    if days is None:
        days_str = input("Số ngày key có hạn (vd 30): ").strip()
        try:
            days = int(days_str)
        except ValueError:
            print("❌ Số ngày phải là số nguyên")
            sys.exit(1)
    if days <= 0:
        print("❌ Số ngày phải > 0")
        sys.exit(1)

    note = args.note
    if not note:
        note = input("Ghi chú (tên user, để trống nếu không cần): ").strip()

    # Tạo key
    print()
    print("⏳ Đang tạo key...")
    key = create_key(machine, days, note, args.private_key)

    print()
    print("✅ KEY ĐÃ TẠO — copy đoạn dưới gửi cho user:")
    print()
    print("─" * 70)
    print(key)
    print("─" * 70)
    print()
    print(f"📋 Machine ID  : {machine}")
    print(f"📅 Hết hạn    : {format_expire_date(days)} ({days} ngày)")
    if note:
        print(f"📝 Ghi chú    : {note}")
    print(f"📏 Độ dài key : {len(key)} chars")
    print()


if __name__ == "__main__":
    main()
