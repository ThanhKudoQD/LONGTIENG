"""
License Service — Verify license key (RSA signed) hoàn toàn LOCAL.

Cơ chế:
- 1 cặp RSA key (admin giữ private, app nhúng public)
- Key dạng: base64(payload).base64(signature)
- payload = {"m": machine_id, "e": expire_ts, "n": note}
- Verify chữ ký + bind machine + check expire

File license lưu tại data/license.dat (plain text key).

v3.7 (2026-05): get_machine_id() chuyển sang Hybrid stable ID
- Primary: /etc/machine-id (Linux/WSL) hoặc registry MachineGuid (Windows native)
- Fallback: persistent UUID lưu data/.machine_id
- BỎ uuid.getnode() vì không ổn định trên WSL2 (MAC eth0 đổi theo session)
- BỎ platform.processor() vì hay trả rỗng trên Linux
"""
from __future__ import annotations
import base64
import hashlib
import json
import logging
import os
import platform
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parent.parent
LICENSE_FILE = BASE_DIR / "data" / "license.dat"
# v3.7: persistent fallback ID (chỉ dùng khi không đọc được system ID)
MACHINE_ID_FALLBACK_FILE = BASE_DIR / "data" / ".machine_id"

# Public key của admin — nhúng vào source code
# (Admin giữ private key riêng để tạo license)
# Sinh bằng:
#   openssl genrsa -out private_key.pem 2048
#   openssl rsa -in private_key.pem -pubout -out public_key.pem
PUBLIC_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAo7v43JbaeC/tLrhZX5ic
QwTM1mBCNiFnf+/BoN2ZDR0H9yZYOpvEzVg3jjr3av1mzJMgoGWk/YJeKghV23s/
y00AEEgvJsdKj1bjB+bskfGLuWeuPlBuN/LxPIzvyazXlGtbsNUT2icrOvp1+tyZ
p33MdxrQXFA3FYrcKo6+WkLu1SluA3ptFnTOCmOkKLClkKzDcBxGDW911I5DT3tw
6o8s/Kfdu6wiEBbb9l8TBGcF0oKzIAGwdugh3d1N00oHYUrForIhl9UaK+j5am7V
IRtxX7UM6pLyaU0Qg1fyT8tTgjtrvEchtzRexSvek7ntMSzZNEpSHcMlKAiLuMt/
2wIDAQAB
-----END PUBLIC KEY-----"""

# ─────────────────────────────────────────────────────────────
# MACHINE ID — v3.7 stable across reboots
# ─────────────────────────────────────────────────────────────

def _read_linux_machine_id() -> Optional[str]:
    """Đọc /etc/machine-id (Linux native + WSL2).

    File này được systemd-machine-id-setup sinh ra LẦN ĐẦU khởi động OS,
    sau đó immutable. Trên WSL2 distro Ubuntu, file này stable across reboots,
    chỉ đổi khi `wsl --unregister` + reinstall distro.

    Format: 32 hex chars. Fallback: /var/lib/dbus/machine-id (cùng nội dung).
    """
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            val = Path(path).read_text(encoding="utf-8").strip()
            if val and len(val) >= 16:
                return val
        except Exception:
            continue
    return None


def _read_windows_machine_guid() -> Optional[str]:
    """Đọc HKLM\\SOFTWARE\\Microsoft\\Cryptography\\MachineGuid (Windows native).

    Stable across reboots, chỉ đổi khi cài lại Windows. Chỉ dùng khi app
    chạy trên Windows native (không phải WSL).
    """
    if sys.platform != "win32":
        return None
    try:
        import winreg  # type: ignore
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        try:
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(val).strip() if val else None
        finally:
            winreg.CloseKey(key)
    except Exception as e:
        logger.debug(f"[license] read MachineGuid failed: {e}")
        return None


def _read_or_create_fallback_id() -> str:
    """Sinh + lưu UUID4 lần đầu, đọc lại lần sau.

    Dùng khi cả /etc/machine-id lẫn MachineGuid đều không đọc được
    (rất hiếm — máy thiếu systemd / quyền registry).
    """
    try:
        if MACHINE_ID_FALLBACK_FILE.exists():
            val = MACHINE_ID_FALLBACK_FILE.read_text(encoding="utf-8").strip()
            if val and len(val) >= 16:
                return val
    except Exception:
        pass

    # Tạo mới
    new_id = uuid.uuid4().hex
    try:
        MACHINE_ID_FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
        MACHINE_ID_FALLBACK_FILE.write_text(new_id, encoding="utf-8")
        # Best-effort hide file trên Windows
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.kernel32.SetFileAttributesW(str(MACHINE_ID_FALLBACK_FILE), 0x02)
            except Exception:
                pass
        logger.info(f"[license] generated fallback machine_id: {new_id[:8]}...")
    except Exception as e:
        logger.error(f"[license] failed to save fallback machine_id: {e}")
    return new_id


def get_machine_id() -> str:
    """Sinh machine ID stable across reboot.

    Ưu tiên:
    1. /etc/machine-id (Linux / WSL2) — ổn định nhất
    2. Windows MachineGuid (Windows native, không phải WSL)
    3. Fallback UUID4 lưu data/.machine_id (chỉ khi 2 trên fail)

    Hash kết quả ra 16-char hex để giữ format cũ. Vì hash function ổn định
    nên cùng input → cùng output, key cũ vẫn dùng được NẾU machine_id
    nguồn không đổi.

    Lưu ý migration: với user đã active key bằng machine_id CŨ
    (hash của hostname+MAC+...), key đó SẼ KHÔNG khớp với machine_id mới.
    User cần xin key mới sau khi update.
    """
    # 1. Linux / WSL
    raw = _read_linux_machine_id()
    source = "linux"

    # 2. Windows native (chỉ khi không phải Linux)
    if not raw and sys.platform == "win32":
        raw = _read_windows_machine_guid()
        source = "windows"

    # 3. Fallback
    if not raw:
        raw = _read_or_create_fallback_id()
        source = "fallback"

    # Hash để giữ format 16-char hex (giống bản cũ) + che giấu raw ID
    # Salt cố định để hash ổn định, không phải để bảo mật.
    salt = "NANO_license_v3.7"
    digest = hashlib.sha256(f"{salt}|{raw}".encode("utf-8")).hexdigest()[:16]
    logger.debug(f"[license] machine_id={digest} (source={source})")
    return digest


# ─────────────────────────────────────────────────────────────
# VERIFY KEY
# ─────────────────────────────────────────────────────────────

def _verify_signature(payload_bytes: bytes, sig_bytes: bytes) -> bool:
    """Verify RSA signature dùng public key nhúng sẵn."""
    try:
        from cryptography.hazmat.primitives.asymmetric import padding
        from cryptography.hazmat.primitives import hashes, serialization

        pub = serialization.load_pem_public_key(PUBLIC_KEY_PEM.encode())
        pub.verify(
            sig_bytes, payload_bytes,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        return True
    except Exception as e:
        logger.debug(f"[license] signature verify failed: {e}")
        return False


def parse_key(key_str: str) -> Optional[dict]:
    """Parse + verify key. Trả về payload nếu valid, None nếu invalid.

    Không check machine + expire — đó là phần riêng (để dùng linh hoạt).
    """
    try:
        key_str = key_str.strip().replace("\n", "").replace(" ", "")
        if "." not in key_str:
            return None
        payload_b64, sig_b64 = key_str.split(".", 1)

        # Add padding (base64 yêu cầu length % 4 == 0)
        def _pad(s: str) -> str:
            return s + "=" * (-len(s) % 4)

        payload_bytes = base64.urlsafe_b64decode(_pad(payload_b64))
        sig_bytes = base64.urlsafe_b64decode(_pad(sig_b64))

        # Verify chữ ký
        if not _verify_signature(payload_bytes, sig_bytes):
            return None

        payload = json.loads(payload_bytes)
        # Validate required fields
        if "m" not in payload or "e" not in payload:
            return None
        return payload
    except Exception as e:
        logger.debug(f"[license] parse_key failed: {e}")
        return None


def verify_key(key_str: str) -> Optional[dict]:
    """Full verify: chữ ký + machine + expired.

    Returns: dict với info nếu OK, None nếu không.
    """
    payload = parse_key(key_str)
    if not payload:
        return None

    # Check machine bind
    if payload["m"] != get_machine_id():
        logger.warning("[license] machine_id mismatch")
        return None

    # Check expired
    now = int(time.time())
    if payload["e"] < now:
        logger.warning("[license] key expired")
        return None

    days = max(0, (payload["e"] - now) // 86400)
    return {
        "machine_id": payload["m"],
        "expires_at": payload["e"],
        "expires_in_days": days,
        "note": payload.get("n", ""),
    }


# ─────────────────────────────────────────────────────────────
# ACTIVATE / IS_VALID / STATUS
# ─────────────────────────────────────────────────────────────

def activate(key_str: str) -> dict:
    """Verify key + lưu file local nếu OK.

    Returns:
        {"ok": True, "info": {...}} nếu thành công
        {"ok": False, "error": "reason"} nếu fail
    """
    if not key_str or not key_str.strip():
        return {"ok": False, "error": "Key rỗng"}

    # Parse trước để check chữ ký
    payload = parse_key(key_str)
    if not payload:
        return {"ok": False, "error": "Key không hợp lệ (chữ ký sai)"}

    # Check machine
    if payload["m"] != get_machine_id():
        return {"ok": False, "error": "Key không khớp với máy này"}

    # Check expired
    if payload["e"] < int(time.time()):
        return {"ok": False, "error": "Key đã hết hạn"}

    # OK — lưu file
    try:
        LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        LICENSE_FILE.write_text(key_str.strip(), encoding="utf-8")
        info = verify_key(key_str)
        logger.info(f"[license] activated, expires in {info['expires_in_days']} days")
        return {"ok": True, "info": info}
    except Exception as e:
        return {"ok": False, "error": f"Không lưu được license file: {e}"}


def is_valid() -> bool:
    """Quick check license hiện tại còn valid không."""
    try:
        if not LICENSE_FILE.exists():
            return False
        key_str = LICENSE_FILE.read_text(encoding="utf-8").strip()
        return verify_key(key_str) is not None
    except Exception:
        return False


def get_status() -> dict:
    """Trạng thái license — dùng cho UI hiển thị."""
    machine_id = get_machine_id()
    if not LICENSE_FILE.exists():
        return {
            "valid": False,
            "reason": "no_license",
            "machine_id": machine_id,
        }
    try:
        key_str = LICENSE_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        return {
            "valid": False,
            "reason": "no_license",
            "machine_id": machine_id,
        }

    payload = parse_key(key_str)
    if not payload:
        return {
            "valid": False,
            "reason": "invalid",
            "machine_id": machine_id,
        }

    # Check machine
    if payload["m"] != machine_id:
        return {
            "valid": False,
            "reason": "machine_mismatch",
            "machine_id": machine_id,
        }

    # Check expire
    now = int(time.time())
    if payload["e"] < now:
        return {
            "valid": False,
            "reason": "expired",
            "machine_id": machine_id,
            "expires_at": payload["e"],
        }

    days = max(0, (payload["e"] - now) // 86400)
    return {
        "valid": True,
        "machine_id": machine_id,
        "expires_at": payload["e"],
        "expires_in_days": days,
        "note": payload.get("n", ""),
    }


def deactivate() -> bool:
    """Xóa license file (dùng khi muốn đổi key)."""
    try:
        if LICENSE_FILE.exists():
            LICENSE_FILE.unlink()
        return True
    except Exception:
        return False
