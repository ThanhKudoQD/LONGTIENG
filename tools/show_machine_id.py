#!/usr/bin/env python3
"""
Show Machine ID — user chạy file này để biết machine_id máy mình,
gửi cho admin để xin key mới (v3.7+).

Cách dùng:
    python tools/show_machine_id.py

In ra 16-char hex. Gửi đoạn này cho admin.
"""
import sys
from pathlib import Path

# Đảm bảo import được dubeditor module
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from dubeditor.license_service import get_machine_id, get_status  # noqa: E402


def main():
    mid = get_machine_id()
    print()
    print("═" * 60)
    print("  MACHINE ID — gửi cho admin để xin key:")
    print("═" * 60)
    print()
    print(f"  {mid}")
    print()
    print("═" * 60)

    # Hiển thị trạng thái license hiện tại nếu có
    status = get_status()
    if status.get("valid"):
        print(f"\n✓ License hiện tại còn HIỆU LỰC, hết hạn sau "
              f"{status['expires_in_days']} ngày")
    elif status.get("reason") == "no_license":
        print("\n⚠ Chưa có license — paste key vào UI sau khi nhận từ admin")
    elif status.get("reason") == "machine_mismatch":
        print("\n⚠ License hiện tại KHÔNG khớp machine_id mới — cần key mới")
    elif status.get("reason") == "expired":
        print("\n⚠ License đã hết hạn — cần key mới")
    else:
        print(f"\n⚠ License invalid: {status.get('reason')}")


if __name__ == "__main__":
    main()
