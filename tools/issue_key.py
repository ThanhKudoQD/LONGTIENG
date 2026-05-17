#!/usr/bin/env python3
"""
Issue License Key — admin tool tạo key cho user.

Cách dùng:
    python tools/issue_key.py <machine_id> <days> [note] [--private-key PATH]

Ví dụ:
    python tools/issue_key.py 91a5b019aafc3c68 365 "User A"
    python tools/issue_key.py 91a5b019aafc3c68 30   "Trial" --private-key /path/private_key.pem

Mặc định đọc private_key.pem ở thư mục hiện tại hoặc thư mục script.
"""
import argparse
import base64
import json
import sys
import time
from pathlib import Path


def issue_key(machine_id: str, days: int, note: str, private_key_path: Path) -> str:
    """Tạo license key dạng base64(payload).base64(signature)."""
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.hazmat.primitives import hashes, serialization

    # Load private key
    pem_bytes = private_key_path.read_bytes()
    private_key = serialization.load_pem_private_key(pem_bytes, password=None)

    # Build payload
    now = int(time.time())
    expire_ts = now + days * 86400
    payload = {
        "m": machine_id.strip(),
        "e": expire_ts,
        "n": note or "",
    }
    # Dùng separators (',', ':') để giảm size — không phải bắt buộc nhưng gọn
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")

    # Sign
    sig_bytes = private_key.sign(
        payload_bytes,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    # Encode urlsafe-base64 không có '='
    def _b64(b: bytes) -> str:
        return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")

    return f"{_b64(payload_bytes)}.{_b64(sig_bytes)}"


def main():
    parser = argparse.ArgumentParser(description="Issue license key for user.")
    parser.add_argument("machine_id", help="Machine ID của user (16-char hex)")
    parser.add_argument("days", type=int, help="Số ngày hiệu lực")
    parser.add_argument("note", nargs="?", default="", help="Ghi chú (optional)")
    parser.add_argument("--private-key", default=None,
                        help="Đường dẫn private_key.pem (default: ./private_key.pem hoặc cạnh script)")
    args = parser.parse_args()

    # Resolve private key path
    if args.private_key:
        pk_path = Path(args.private_key).expanduser().resolve()
    else:
        # Thử cwd → cạnh script → cha của script
        for cand in [
            Path("private_key.pem"),
            Path(__file__).resolve().parent / "private_key.pem",
            Path(__file__).resolve().parent.parent / "private_key.pem",
        ]:
            if cand.exists():
                pk_path = cand
                break
        else:
            print("❌ Không tìm thấy private_key.pem. Dùng --private-key PATH.",
                  file=sys.stderr)
            sys.exit(1)

    if not pk_path.exists():
        print(f"❌ Private key không tồn tại: {pk_path}", file=sys.stderr)
        sys.exit(1)

    # Validate machine_id
    mid = args.machine_id.strip().lower()
    if len(mid) < 8 or not all(c in "0123456789abcdef" for c in mid):
        print(f"❌ Machine ID không hợp lệ: {mid!r} (cần hex 16 ký tự)",
              file=sys.stderr)
        sys.exit(1)

    if args.days < 1 or args.days > 36500:
        print(f"❌ Days không hợp lệ: {args.days} (1-36500)", file=sys.stderr)
        sys.exit(1)

    # Issue
    try:
        key = issue_key(mid, args.days, args.note, pk_path)
    except Exception as e:
        print(f"❌ Lỗi tạo key: {e}", file=sys.stderr)
        sys.exit(1)

    expire_dt = time.strftime("%Y-%m-%d %H:%M",
                              time.localtime(int(time.time()) + args.days * 86400))
    print()
    print("═" * 70)
    print(f"  License Key cho machine_id = {mid}")
    print(f"  Hết hạn: {expire_dt} ({args.days} ngày)")
    if args.note:
        print(f"  Note: {args.note}")
    print("═" * 70)
    print()
    print(key)
    print()
    print("═" * 70)
    print("Gửi đoạn key trên cho user. User paste vào trang License trong app.")


if __name__ == "__main__":
    main()
