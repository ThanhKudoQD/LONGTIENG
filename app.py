"""
VoiceCast + VoxCPM2 — Unified Server
Chạy: python app.py --model-id ./VoxCPM2
UI:   http://localhost:8809
API:  http://localhost:8809/docs
"""

import os, sys, io, re, time, shutil, logging, threading, asyncio
import numpy as np
import soundfile as sf
import torch
import uvicorn

from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

import bcrypt
import jwt as pyjwt

from fastapi import (FastAPI, HTTPException, UploadFile, File,
                     Form, Request, Depends, Response)
from fastapi.responses import (HTMLResponse, JSONResponse,
                               FileResponse, StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["TORCHINDUCTOR_FREEZING"] = "0"

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR    = Path(__file__).parent
DATA_DIR    = BASE_DIR / "data"
PUBLIC_DIR  = BASE_DIR / "public"
UPLOADS_DIR = PUBLIC_DIR / "uploads"
GEN_DIR     = UPLOADS_DIR / "generated"

for d in [DATA_DIR, PUBLIC_DIR, UPLOADS_DIR,
          UPLOADS_DIR/"avatars", UPLOADS_DIR/"roles", GEN_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Config ───────────────────────────────────────────────────────────────────
MODEL_ID   = str(BASE_DIR / "VoxCPM2")
GPU_MEM    = 0.95
MAX_SEQS   = 2
HOST       = "0.0.0.0"
PORT       = 8809
JWT_SECRET = os.environ.get("JWT_SECRET", "voicecast_secret_change_me")
JWT_EXPIRE = 7  # days

# ─── Nano-vLLM singleton ──────────────────────────────────────────────────────
_nano_server = None
_nano_ready  = threading.Event()
_nano_error  = None

def _start_nano():
    global _nano_server, _nano_error
    try:
        from nanovllm_voxcpm import VoxCPM
        from nanovllm_voxcpm.models.voxcpm2.config import LoRAConfig
        logger.info(f"[Nano] Loading {MODEL_ID} ...")
        _lora_config = LoRAConfig(
            enable_lm=True,
            enable_dit=True,
            max_loras=8,
            max_lora_rank=32,
        )
        _lora_config = LoRAConfig(
            enable_lm=True,
            enable_dit=True,
            max_loras=1,
            max_lora_rank=32,
        )
        _nano_server = VoxCPM.from_pretrained(
            model=MODEL_ID, devices=[0],
            gpu_memory_utilization=GPU_MEM,
            max_num_seqs=MAX_SEQS,
            lora_config=_lora_config,
        )
        logger.info("[Nano] Model ready ✅")
    except Exception as e:
        _nano_error = e
        logger.error(f"[Nano] Failed: {e}")
    finally:
        _nano_ready.set()

def get_nano():
    _nano_ready.wait()
    if _nano_error:
        raise RuntimeError(f"Model load failed: {_nano_error}")
    if _nano_server is None:
        raise RuntimeError("Model TTS chưa được load. Bấm 'Model ON' ở header để load model trước.")
    return _nano_server

def _preload_all_loras():
    """Register tất cả LoRA từ DB khi khởi động."""
    try:
        from dubeditor.models import Role
        srv = get_nano()
        db  = _get_vc_session()
        try:
            roles = db.query(Role).filter(Role.lora_path != "").all()
        finally:
            db.close()
        for role in roles:
            lora_path = (role.lora_path or "").strip()
            if not lora_path or not os.path.exists(lora_path):
                continue
            try:
                lora_name = f"lora_{hash(lora_path) & 0xFFFFFF:06x}"
                if hasattr(srv, "list_loras") and hasattr(srv, "register_lora"):
                    registered = [l.name for l in srv.list_loras()]
                    if lora_name not in registered:
                        srv.register_lora(name=lora_name, path=lora_path)
                    logger.info(f"[LoRA] Preloaded: {role.character_name} → {lora_name}")
                else:
                    logger.info("[LoRA] Version này không hỗ trợ register_lora, bỏ qua preload")
                    break
            except Exception as e:
                logger.warning(f"[LoRA] Preload failed {role.character_name}: {e}")
    except Exception as e:
        logger.warning(f"[LoRA] Preload all failed: {e}")

# ─── Database ─────────────────────────────────────────────────────────────────
def uid():
    return hex(int(time.time() * 1000))[2:] + hex(int.from_bytes(
        os.urandom(3), 'big'))[2:]

# ─── DB Helpers (SQLAlchemy) ──────────────────────────────────────────────────
def _role_to_dict(role) -> dict:
    from dubeditor.voice_modes import parse_voice_modes
    return {
        "id":                   role.id,
        "actor_id":             role.actor_id,
        "character_name":       role.character_name,
        "show_name":            role.show_name,
        "type":                 role.type,
        "genre":                role.genre,
        "description":          role.description,
        "audio":                role.audio,
        "reference_audio_text": role.reference_audio_text,
        "lora_path":            role.lora_path,
        "sort_order":           role.sort_order,
        "images":               [img.url for img in role.images],
        # v3: multi-mode voice refs (toggle ở Project level)
        "voice_modes":          parse_voice_modes(role.voice_modes),
    }

def _actor_to_dict(actor) -> dict:
    return {
        "id":         actor.id,
        "name":       actor.name,
        "gender":     actor.gender,
        "birth_year": actor.birth_year,
        "avatar":     actor.avatar,
        "bio":        actor.bio,
        "roles":      [_role_to_dict(r) for r in actor.roles],
    }

def _get_vc_session():
    """Trả về SQLAlchemy session từ dubeditor (DB dùng chung)."""
    from dubeditor.database import SessionLocal
    return SessionLocal()

def seed_admin():
    from dubeditor.models import Admin
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    db = _get_vc_session()
    try:
        exists = db.query(Admin).filter(Admin.username == username).first()
        if not exists:
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            db.add(Admin(username=username, password=hashed))
            db.commit()
            logger.info(f"✅ Admin tạo thành công: {username}")
    finally:
        db.close()

# ─── Auth ─────────────────────────────────────────────────────────────────────
def sign_token(payload: dict) -> str:
    payload["exp"] = datetime.utcnow() + timedelta(days=JWT_EXPIRE)
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")

def verify_token(token: str) -> dict:
    return pyjwt.decode(token, JWT_SECRET, algorithms=["HS256"])

def get_token(request: Request) -> Optional[str]:
    token = request.cookies.get("token")
    if not token:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
    return token

async def require_auth_api(request: Request):
    token = get_token(request)
    if not token:
        raise HTTPException(401, "Unauthorized")
    try:
        return verify_token(token)
    except Exception:
        raise HTTPException(401, "Token không hợp lệ")

# ─── TTS Core ─────────────────────────────────────────────────────────────────
def _wav_bytes(wav: np.ndarray, sr: int = 48000) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, wav, sr, format="WAV")
    buf.seek(0)
    return buf.read()

def _build_text(text: str, control: str = "") -> str:
    """Prefix control instruction vào text cho VoxCPM.

    Output format VoxCPM cần: "(instruction)Hello world"

    Args:
        text: nội dung cần đọc
        control: control instruction (có hoặc không có ngoặc bao quanh)
    """
    c = (control or "").strip()
    t = (text or "").strip()
    if not c:
        return t
    # Bỏ ngoặc thừa nếu caller đã wrap rồi
    if c.startswith("(") and c.endswith(")"):
        c = c[1:-1].strip()
    if not c:
        return t
    return f"({c}){t}"

def _generate_sync(
    target_text: str,
    reference_wav_path: Optional[str] = None,
    prompt_wav_path: Optional[str] = None,
    prompt_text: Optional[str] = None,
    cfg_value: float = 3.0,
    lora_path: Optional[str] = None,
) -> np.ndarray:
    srv = get_nano()
    logger.info(f"[GEN] {target_text[:80]}")

    # LoRA: dùng load_lora nếu có (version cũ) hoặc register_lora (version mới)
    lora_name = None
    if lora_path and os.path.exists(lora_path):
        try:
            if hasattr(srv, 'register_lora') and hasattr(srv, 'list_loras'):
                # nano-vllm-voxcpm >= 2.0.1
                lora_name = f"lora_{hash(lora_path) & 0xFFFFFF:06x}"
                registered_names = [l.name for l in srv.list_loras()]
                if lora_name not in registered_names:
                    srv.register_lora(name=lora_name, path=lora_path)
                logger.info(f"[LoRA] Using: {lora_name}")
            elif hasattr(srv, 'load_lora'):
                # nano-vllm-voxcpm <= 1.x
                srv.load_lora(lora_path)
                logger.info(f"[LoRA] Loaded: {lora_path}")
            else:
                logger.warning("[LoRA] Không tìm thấy API load LoRA")
        except Exception as e:
            logger.warning(f"[LoRA] Failed: {e}")
            lora_name = None

    ref_latents = None
    if reference_wav_path and os.path.exists(reference_wav_path):
        with open(reference_wav_path, "rb") as f:
            ref_bytes = f.read()
        fmt = Path(reference_wav_path).suffix.lstrip(".") or "wav"
        ref_latents = srv.encode_latents(ref_bytes, fmt)

    prompt_id = None
    if prompt_wav_path and prompt_text and os.path.exists(prompt_wav_path):
        with open(prompt_wav_path, "rb") as f:
            prompt_bytes = f.read()
        fmt = Path(prompt_wav_path).suffix.lstrip(".") or "wav"
        prompt_id = srv.add_prompt(prompt_bytes, fmt, prompt_text.strip())

    try:
        gen_kwargs = dict(
            target_text=target_text,
            prompt_id=prompt_id,
            ref_audio_latents=ref_latents,
            cfg_value=cfg_value,
        )
        # lora_name chỉ có trong nano-vllm-voxcpm >= 2.0.1
        import inspect
        if lora_name and 'lora_name' in inspect.signature(srv.generate).parameters:
            gen_kwargs['lora_name'] = lora_name
        chunks = list(srv.generate(**gen_kwargs))
        return np.concatenate(chunks)
    finally:
        if prompt_id:
            try: srv.remove_prompt(prompt_id)
            except: pass

def _save_generated(wav: np.ndarray, sr: int = 48000) -> str:
    fname = f"{uid()}.wav"
    fpath = GEN_DIR / fname
    sf.write(str(fpath), wav, sr)
    return f"/uploads/generated/{fname}"

# ─── Model API ──────────────────────────────────────────────────────────────
_model_loading = False

def _do_load():
    global _model_loading, _nano_error
    _model_loading = True
    try:
        _nano_ready.clear()
        _nano_error = None
        _start_nano()
        _preload_all_loras()
    finally:
        _model_loading = False

# ─── FastAPI App ──────────────────────────────────────────────────────────────
def _cleanup_on_shutdown():
    """Cleanup chạy khi app shutdown — unload model + free VRAM."""
    global _nano_server, _nano_error
    try:
        if _nano_server is not None:
            try:
                _nano_server.stop()
                logger.info("[Shutdown] Model server stopped")
            except Exception as e:
                logger.warning(f"[Shutdown] Stop server failed: {e}")
            _nano_server = None
            _nano_error  = None
        # Free GPU memory
        import gc
        gc.collect()
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
                logger.info("[Shutdown] VRAM freed ✅")
        except Exception as e:
            logger.warning(f"[Shutdown] CUDA cleanup failed: {e}")
    except Exception as e:
        logger.warning(f"[Shutdown] Cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    from dubeditor.database import init_db as dub_init_db
    dub_init_db()  # khởi tạo toàn bộ bảng (DubEditor + VoiceCast) trong 1 DB
    seed_admin()

    # Khởi động TTS Queue worker
    from dubeditor.tts_queue import queue_manager
    from dubeditor.routers.ws import broadcast as dub_broadcast
    from dubeditor.routers.tts import do_generate as dub_do_generate
    queue_manager.setup(generate_fn=dub_do_generate, broadcast_fn=dub_broadcast)
    queue_manager.start_worker()

    # Đăng ký signal handler cho SIGTERM / SIGINT
    # (lifespan shutdown đôi khi không chạy nếu kill -9, nhưng SIGTERM/SIGINT thì chạy được)
    import signal
    def _signal_handler(signum, frame):
        logger.info(f"[Signal] Received {signum}, cleaning up...")
        _cleanup_on_shutdown()
        # Re-raise để uvicorn shutdown bình thường
        raise SystemExit(0)
    try:
        signal.signal(signal.SIGTERM, _signal_handler)
        signal.signal(signal.SIGINT, _signal_handler)
    except (ValueError, OSError):
        # Trong worker thread không đăng ký signal được — bỏ qua
        pass

    # Đăng ký atexit cho trường hợp normal exit
    import atexit
    atexit.register(_cleanup_on_shutdown)

    logger.info(f"✅ Server: http://{HOST}:{PORT}")
    yield

    # Shutdown (lifespan exit)
    logger.info("[Shutdown] Lifespan exiting...")
    queue_manager.stop_worker()
    _cleanup_on_shutdown()

app = FastAPI(title="VoiceCast + VoxCPM2", version="3.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ━━━ License middleware (khóa hoàn toàn nếu invalid/expired) ━━━
from dubeditor import license_service as _license_service

# Các path KHÔNG cần check license:
# - /dub/api/license/*  — endpoints để activate/check status license
# - /app                — frontend dubeditor (SPA này có LicenseGate riêng)
# - /dub/projects, /dub/videos, /dub/exports — static files (audio/video preview)
# - /uploads, /static   — assets chung
# - /health, /healthz   — healthcheck
#
# Các path SẼ BỊ CHẶN khi license invalid:
# - /                   — index.html (VoiceCast main page)
# - /admin              — admin page
# - /admin/login        — admin login page
# - /api/admin/*        — admin APIs
# - /dub/api/*          — dubeditor APIs (trừ /dub/api/license/*)
_LICENSE_WHITELIST_PREFIXES = (
    "/dub/api/license/",
    "/app",
    "/dub/projects/",
    "/dub/videos/",
    "/dub/exports/",
    "/static/",
    "/uploads/",
)
_LICENSE_WHITELIST_EXACT = {"/health", "/healthz"}


def _license_invalid_html_page() -> str:
    """Trang HTML đẹp hiển thị khi license invalid (cho user truy cập /, /admin)."""
    return """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>License Required</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,sans-serif}
  body{min-height:100vh;display:flex;align-items:center;justify-content:center;background:linear-gradient(135deg,#0f172a,#1e293b);color:#fff;padding:20px}
  .card{background:rgba(255,255,255,0.05);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,0.1);border-radius:20px;padding:40px;max-width:480px;width:100%;text-align:center}
  .icon{font-size:64px;margin-bottom:16px}
  h1{font-size:28px;font-weight:700;margin-bottom:8px}
  .subtitle{color:#94a3b8;margin-bottom:24px;font-size:14px}
  .alert{background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);color:#fca5a5;border-radius:12px;padding:14px;margin-bottom:20px;font-size:13px}
  .btn{display:inline-block;background:#3b82f6;color:#fff;padding:12px 28px;border-radius:10px;text-decoration:none;font-weight:600;transition:all 0.2s}
  .btn:hover{background:#2563eb;transform:translateY(-1px)}
  .info{margin-top:20px;font-size:12px;color:#64748b}
  .info code{background:rgba(255,255,255,0.06);padding:2px 8px;border-radius:6px;color:#cbd5e1;font-family:monospace}
</style>
</head>
<body>
  <div class="card">
    <div class="icon">🔒</div>
    <h1>License Required</h1>
    <p class="subtitle">Phần mềm chưa được kích hoạt hoặc license đã hết hạn</p>
    <div class="alert">
      ⚠ Bạn cần kích hoạt phần mềm trước khi sử dụng tính năng này.
    </div>
    <a href="/app/" class="btn">→ Đến trang kích hoạt</a>
    <div class="info">
      Liên hệ admin để nhận license key.<br>
      <code>📱 Telegram: @your_admin</code>
    </div>
  </div>
</body>
</html>"""


@app.middleware("http")
async def license_middleware(request, call_next):
    from fastapi.responses import JSONResponse, HTMLResponse
    path = request.url.path

    # Whitelist các path không cần license
    if path in _LICENSE_WHITELIST_EXACT:
        return await call_next(request)
    if any(path.startswith(p) for p in _LICENSE_WHITELIST_PREFIXES):
        return await call_next(request)
    # WebSocket sẽ tự handle trong handler
    if request.headers.get("upgrade", "").lower() == "websocket":
        return await call_next(request)

    if not _license_service.is_valid():
        # API request → trả JSON 403
        if (path.startswith("/api/")
            or path.startswith("/dub/api/")
            or "application/json" in request.headers.get("accept", "")):
            return JSONResponse(
                {"error": "LICENSE_INVALID", "detail": "License hết hạn hoặc không hợp lệ"},
                status_code=403,
            )
        # Page request (/, /admin, /admin/login) → trả HTML page
        return HTMLResponse(_license_invalid_html_page(), status_code=403)

    return await call_next(request)
# ━━━ END License middleware ━━━

# ── DubEditor ────────────────────────────────────────────────────────────────
from dubeditor.router import router as dub_router
from pathlib import Path as _Path
app.include_router(dub_router, prefix="/dub")
_dub_projects = _Path(__file__).parent / "data" / "projects"
_dub_projects.mkdir(parents=True, exist_ok=True)
(_dub_projects / "_videos").mkdir(exist_ok=True)
(_dub_projects / "_exports").mkdir(exist_ok=True)
app.mount("/dub/projects", StaticFiles(directory=str(_dub_projects)), name="dub-projects")
(_dub_videos := _dub_projects / "_videos")
app.mount("/dub/videos", StaticFiles(directory=str(_dub_projects / "_videos")), name="dub-videos")
app.mount("/dub/exports", StaticFiles(directory=str(_dub_projects / "_exports")), name="dub-exports")
_dub_fe = _Path(__file__).parent / "public" / "dubeditor"
_dub_fe.mkdir(parents=True, exist_ok=True)
app.mount("/app", StaticFiles(directory=str(_dub_fe), html=True), name="dubeditor-ui")

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# ─── Pages ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    f = PUBLIC_DIR / "index.html"
    return HTMLResponse(f.read_text(encoding="utf-8") if f.exists()
                        else "<h1>index.html not found</h1>")

@app.get("/admin", response_class=HTMLResponse)
async def admin_page(request: Request):
    token = get_token(request)
    if not token:
        return HTMLResponse("", status_code=302,
                            headers={"Location": "/admin/login"})
    try:
        verify_token(token)
    except Exception:
        return HTMLResponse("", status_code=302,
                            headers={"Location": "/admin/login"})
    f = PUBLIC_DIR / "admin.html"
    return HTMLResponse(f.read_text(encoding="utf-8") if f.exists()
                        else "<h1>admin.html not found</h1>")

@app.get("/admin/login", response_class=HTMLResponse)
async def login_page():
    return HTMLResponse(_login_html())

# ─── Auth ─────────────────────────────────────────────────────────────────────
class LoginBody(BaseModel):
    username: str
    password: str

@app.post("/admin/login")
async def do_login(body: LoginBody, response: Response):
    from dubeditor.models import Admin
    db = _get_vc_session()
    try:
        admin = db.query(Admin).filter(Admin.username == body.username).first()
    finally:
        db.close()
    if not admin:
        raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng")
    if not bcrypt.checkpw(body.password.encode(), admin.password.encode()):
        raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng")
    token = sign_token({"id": admin.id, "username": admin.username})
    response.set_cookie("token", token, httponly=True, max_age=JWT_EXPIRE * 86400)
    return {"token": token, "message": "Đăng nhập thành công"}

@app.post("/admin/logout")
async def do_logout(response: Response):
    response.delete_cookie("token")
    return {"message": "Đã đăng xuất"}

@app.post("/api/admin/change-password")
async def change_password(request: Request, admin=Depends(require_auth_api)):
    from dubeditor.models import Admin
    body = await request.json()
    db   = _get_vc_session()
    try:
        a = db.query(Admin).filter(Admin.username == admin["username"]).first()
        if not bcrypt.checkpw(body.get("current", "").encode(), a.password.encode()):
            raise HTTPException(400, "Mật khẩu hiện tại không đúng")
        a.password = bcrypt.hashpw(body.get("newPass", "").encode(), bcrypt.gensalt()).decode()
        db.commit()
    finally:
        db.close()
    return {"message": "Đã đổi mật khẩu"}

# ─── Public API ───────────────────────────────────────────────────────────────
@app.get("/api/actors")
async def api_actors():
    from dubeditor.models import Actor
    db = _get_vc_session()
    try:
        actors = db.query(Actor).order_by(Actor.name).all()
        return {"actors": [_actor_to_dict(a) for a in actors]}
    finally:
        db.close()

@app.get("/api/actors/{actor_id}")
async def api_actor(actor_id: str):
    from dubeditor.models import Actor
    db = _get_vc_session()
    try:
        a = db.query(Actor).filter(Actor.id == actor_id).first()
        if not a:
            raise HTTPException(404, "Không tìm thấy")
        return _actor_to_dict(a)
    finally:
        db.close()

# ─── Admin: Actors ────────────────────────────────────────────────────────────
@app.post("/api/admin/actors")
async def create_actor(request: Request, admin=Depends(require_auth_api)):
    from dubeditor.models import Actor
    body = await request.json()
    if not body.get("name", "").strip():
        raise HTTPException(400, "Tên là bắt buộc")
    new_id = uid()
    db = _get_vc_session()
    try:
        db.add(Actor(
            id=new_id,
            name=body["name"].strip(),
            gender=body.get("gender", "nam"),
            birth_year=int(body.get("birth_year", 1990)),
            avatar=body.get("avatar", ""),
            bio=body.get("bio", ""),
        ))
        db.commit()
    finally:
        db.close()
    return {"id": new_id, "message": "Đã tạo diễn viên"}

@app.put("/api/admin/actors/{actor_id}")
async def update_actor(actor_id: str, request: Request, admin=Depends(require_auth_api)):
    from dubeditor.models import Actor
    body = await request.json()
    if not body.get("name", "").strip():
        raise HTTPException(400, "Tên là bắt buộc")
    db = _get_vc_session()
    try:
        a = db.query(Actor).filter(Actor.id == actor_id).first()
        if not a:
            raise HTTPException(404, "Không tìm thấy")
        a.name       = body["name"].strip()
        a.gender     = body.get("gender", "nam")
        a.birth_year = int(body.get("birth_year", 1990))
        a.avatar     = body.get("avatar", "")
        a.bio        = body.get("bio", "")
        db.commit()
    finally:
        db.close()
    return {"message": "Đã cập nhật"}

@app.delete("/api/admin/actors/{actor_id}")
async def delete_actor(actor_id: str, admin=Depends(require_auth_api)):
    from dubeditor.models import Actor
    db = _get_vc_session()
    try:
        a = db.query(Actor).filter(Actor.id == actor_id).first()
        if a:
            db.delete(a)
            db.commit()
    finally:
        db.close()
    return {"message": "Đã xóa"}

# ─── Admin: Roles ─────────────────────────────────────────────────────────────
@app.post("/api/admin/actors/{actor_id}/roles")
async def create_role(actor_id: str, request: Request, admin=Depends(require_auth_api)):
    from dubeditor.models import Role, RoleImage
    body   = await request.json()
    new_id = uid()
    db     = _get_vc_session()
    try:
        from dubeditor.voice_modes import dump_voice_modes
        count = db.query(Role).filter(Role.actor_id == actor_id).count()
        db.add(Role(
            id=new_id, actor_id=actor_id,
            character_name=body.get("character_name", ""),
            show_name=body.get("show_name", ""),
            type=body.get("type", "chinh"),
            genre=body.get("genre", "hien-dai"),
            description=body.get("description", ""),
            audio=body.get("audio", ""),
            reference_audio_text=body.get("reference_audio_text", ""),
            lora_path=body.get("lora_path", ""),
            sort_order=count,
            voice_modes=dump_voice_modes(body.get("voice_modes") or {}),
        ))
        for i, url in enumerate(body.get("images", [])):
            db.add(RoleImage(role_id=new_id, url=url, sort_order=i))
        db.commit()
    finally:
        db.close()
    return {"id": new_id, "message": "Đã thêm vai"}

@app.put("/api/admin/roles/{role_id}")
async def update_role(role_id: str, request: Request, admin=Depends(require_auth_api)):
    from dubeditor.models import Role, RoleImage
    from dubeditor.voice_modes import dump_voice_modes
    body = await request.json()
    db   = _get_vc_session()
    try:
        r = db.query(Role).filter(Role.id == role_id).first()
        if not r:
            raise HTTPException(404, "Không tìm thấy")
        r.character_name       = body.get("character_name", "")
        r.show_name            = body.get("show_name", "")
        r.type                 = body.get("type", "chinh")
        r.genre                = body.get("genre", "hien-dai")
        r.description          = body.get("description", "")
        r.audio                = body.get("audio", "")
        r.reference_audio_text = body.get("reference_audio_text", "")
        r.lora_path            = body.get("lora_path", "")
        # v3: multi-mode voice (toggle ở Project level)
        if "voice_modes" in body:
            r.voice_modes = dump_voice_modes(body.get("voice_modes") or {})
        # Cập nhật images
        db.query(RoleImage).filter(RoleImage.role_id == role_id).delete()
        for i, url in enumerate(body.get("images", [])):
            db.add(RoleImage(role_id=role_id, url=url, sort_order=i))
        db.commit()
    finally:
        db.close()
    return {"message": "Đã cập nhật vai"}

@app.delete("/api/admin/roles/{role_id}")
async def delete_role(role_id: str, admin=Depends(require_auth_api)):
    from dubeditor.models import Role
    db = _get_vc_session()
    try:
        r = db.query(Role).filter(Role.id == role_id).first()
        if r:
            db.delete(r)
            db.commit()
    finally:
        db.close()
    return {"message": "Đã xóa vai"}

# ─── Admin: Upload ────────────────────────────────────────────────────────────
@app.post("/api/admin/upload/avatar")
async def upload_avatar(file: UploadFile = File(...),
                        admin=Depends(require_auth_api)):
    ext = Path(file.filename).suffix or ".jpg"
    fname = uid() + ext
    with open(UPLOADS_DIR / "avatars" / fname, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/avatars/{fname}"}

@app.post("/api/admin/upload/role")
async def upload_role_file(file: UploadFile = File(...),
                           admin=Depends(require_auth_api)):
    ext = Path(file.filename).suffix or ".wav"
    fname = uid() + ext
    with open(UPLOADS_DIR / "roles" / fname, "wb") as f:
        f.write(await file.read())
    return {"url": f"/uploads/roles/{fname}"}


# ─── Admin: Voice modes per role ──────────────────────────────────────────────
@app.put("/api/admin/roles/{role_id}/voice-mode/{mode}")
async def upsert_voice_mode(role_id: str, mode: str, request: Request,
                             admin=Depends(require_auth_api)):
    """Set hoặc cập nhật 1 voice mode cho role.

    Body: { audio: "/uploads/...", text: "...", duration: 3.5 }
    Body có thể chỉ chứa các field muốn update (partial).
    """
    from dubeditor.models import Role
    from dubeditor.voice_modes import parse_voice_modes, dump_voice_modes, MODE_LABELS

    if mode not in MODE_LABELS:
        raise HTTPException(400, f"Mode không hợp lệ: {mode}. Phải là 1 trong {list(MODE_LABELS.keys())}")

    body = await request.json()
    db = _get_vc_session()
    try:
        r = db.query(Role).filter(Role.id == role_id).first()
        if not r:
            raise HTTPException(404, "Không tìm thấy role")

        modes = parse_voice_modes(r.voice_modes)
        modes[mode] = {
            "audio":    body.get("audio", modes.get(mode, {}).get("audio", "")),
            "text":     body.get("text", modes.get(mode, {}).get("text", "")),
            "duration": body.get("duration", modes.get(mode, {}).get("duration", 0)),
        }
        r.voice_modes = dump_voice_modes(modes)
        db.commit()
        return {"message": f"Đã cập nhật mode '{mode}'", "voice_modes": modes}
    finally:
        db.close()


@app.delete("/api/admin/roles/{role_id}/voice-mode/{mode}")
async def delete_voice_mode(role_id: str, mode: str,
                              admin=Depends(require_auth_api)):
    """Xóa 1 voice mode khỏi role."""
    from dubeditor.models import Role
    from dubeditor.voice_modes import parse_voice_modes, dump_voice_modes

    db = _get_vc_session()
    try:
        r = db.query(Role).filter(Role.id == role_id).first()
        if not r:
            raise HTTPException(404, "Không tìm thấy role")

        modes = parse_voice_modes(r.voice_modes)
        if mode in modes:
            del modes[mode]
            r.voice_modes = dump_voice_modes(modes)
            db.commit()
        return {"message": f"Đã xóa mode '{mode}'", "voice_modes": modes}
    finally:
        db.close()


# ─── TTS API ──────────────────────────────────────────────────────────────────
class TTSRequest(BaseModel):
    role_id: str
    text: str
    mode: str = "ultimate"        # "clone" | "ultimate" (Hi-Fi)
    cfg_value: float = 3.0
    locdit_steps: int = 40
    use_lora: bool = False
    # v3: chọn voice mode (3 mode). '' = dùng role.audio mặc định
    voice_mode: str = ""          # 'normal' | 'sad' | 'angry' | ''

@app.post("/api/tts/generate")
async def tts_generate(body: TTSRequest):
    from dubeditor.models import Role
    from dubeditor.voice_modes import parse_voice_modes, MODE_LABELS
    db = _get_vc_session()
    try:
        role = db.query(Role).filter(Role.id == body.role_id).first()
        if not role:
            raise HTTPException(404, f"Không tìm thấy role: {body.role_id}")

        # Resolve audio + ref_text:
        # 1. Nếu voice_mode set + role có voice_modes[mode] → dùng mode đó
        # 2. Fallback normal mode nếu mode đó chưa upload
        # 3. Fallback cuối: role.audio + role.reference_audio_text
        audio_url = role.audio or ""
        ref_text  = role.reference_audio_text or ""
        voice_mode_used = "default"

        vm = (body.voice_mode or "").strip().lower()
        if vm and vm in MODE_LABELS:
            modes = parse_voice_modes(role.voice_modes)
            ref = modes.get(vm)
            if ref and ref.get("audio"):
                audio_url = ref["audio"]
                ref_text  = ref.get("text", "") or ""
                voice_mode_used = vm
            else:
                # Fallback normal nếu mode đó trống
                ref = modes.get("normal")
                if ref and ref.get("audio"):
                    audio_url = ref["audio"]
                    ref_text  = ref.get("text", "") or ""
                    voice_mode_used = f"normal (fallback from {vm})"

        lora_path = (role.lora_path or "").strip() or None
    finally:
        db.close()

    audio_path = None
    if audio_url:
        candidate = PUBLIC_DIR / audio_url.lstrip("/")
        if candidate.exists():
            audio_path = str(candidate)
        else:
            logger.warning(f"[GEN] Audio file MISSING: {candidate}")

    if lora_path and not os.path.exists(lora_path):
        logger.warning(f"LoRA path không tồn tại: {lora_path}")
        lora_path = None

    if not audio_path and not lora_path:
        raise HTTPException(400, "Role này chưa có audio mẫu hoặc LoRA. Không thể generate.")

    logger.info(
        f"[GEN] mode={body.mode} cfg={body.cfg_value} "
        f"role={body.role_id} voice_mode={voice_mode_used} "
        f"audio_url={audio_url!r} ref_text_len={len(ref_text)} "
        f"text={body.text!r}"[:380]
    )

    loop = asyncio.get_event_loop()
    try:
        # Ultimate (Hi-Fi): cần audio_path + ref_text → giọng giống ref nhất
        if body.mode == "ultimate" and audio_path and ref_text:
            wav = await loop.run_in_executor(None, lambda: _generate_sync(
                target_text=body.text.strip(),
                reference_wav_path=audio_path,
                prompt_wav_path=audio_path,
                prompt_text=ref_text,
                cfg_value=body.cfg_value,
                lora_path=lora_path,
            ))
            mode_used = f"ultimate ({voice_mode_used})"
        elif audio_path:
            # Controllable Cloning: chỉ ref audio, không prompt_text
            wav = await loop.run_in_executor(None, lambda: _generate_sync(
                target_text=body.text.strip(),
                reference_wav_path=audio_path,
                cfg_value=body.cfg_value,
                lora_path=lora_path,
            ))
            mode_used = f"clone ({voice_mode_used})" + (" + lora" if lora_path else "")
        else:
            wav = await loop.run_in_executor(None, lambda: _generate_sync(
                target_text=body.text.strip(),
                cfg_value=body.cfg_value,
                lora_path=lora_path,
            ))
            mode_used = "lora_only"

        logger.info(f"[GEN] DONE mode_used={mode_used} dur={len(wav)/48000:.2f}s")

        url = _save_generated(wav)
        return {
            "url":      url,
            "mode":     mode_used,
            "role_id":  body.role_id,
            "duration": round(len(wav) / 48000, 2),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"TTS error: {e}", exc_info=True)
        raise HTTPException(500, str(e))

@app.get("/api/tts/status")
async def tts_status():
    vram = {}
    if torch.cuda.is_available():
        free, total = torch.cuda.mem_get_info()
        vram = {"free_gb": round(free/1024**3, 2),
                "total_gb": round(total/1024**3, 2),
                "used_gb": round((total-free)/1024**3, 2)}
    return {"ready": _nano_server is not None,
            "model": MODEL_ID,
            "error": str(_nano_error) if _nano_error else None,
            "vram": vram}

# ─── Login Page ───────────────────────────────────────────────────────────────
def _login_html(error=""):
    err_html = f'<div class="err">⚠ {error}</div>' if error else ""
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>VoiceCast Admin — Đăng nhập</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:wght@600;700&family=Outfit:wght@400;500&display=swap" rel="stylesheet">
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#07070f;color:#ede9f8;font-family:'Outfit',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center}}
.box{{background:#0e0e1a;border:1px solid #22223a;border-radius:16px;padding:40px;width:100%;max-width:380px}}
.logo{{font-family:'Cormorant Garamond',serif;font-size:1.8rem;font-weight:700;text-align:center;margin-bottom:6px}}
.logo em{{color:#c9a84c;font-style:normal}}
.sub{{text-align:center;font-size:.72rem;letter-spacing:2.5px;text-transform:uppercase;color:#46456a;margin-bottom:32px}}
.fg{{display:flex;flex-direction:column;gap:6px;margin-bottom:16px}}
label{{font-size:.7rem;text-transform:uppercase;letter-spacing:.8px;color:#8b8aa8}}
input{{background:#141421;border:1px solid #22223a;border-radius:8px;padding:11px 14px;color:#ede9f8;font-family:'Outfit',sans-serif;font-size:.9rem;outline:none;transition:border-color .2s;width:100%}}
input:focus{{border-color:#c9a84c}}
.err{{background:rgba(224,85,119,.12);border:1px solid rgba(224,85,119,.3);color:#e05577;border-radius:8px;padding:10px 14px;font-size:.82rem;margin-bottom:16px}}
button{{width:100%;background:#c9a84c;color:#08080f;border:none;border-radius:8px;padding:12px;font-family:'Outfit',sans-serif;font-size:.9rem;font-weight:600;cursor:pointer;margin-top:4px}}
button:hover{{background:#e8c872}}
</style>
</head>
<body>
<div class="box">
  <div class="logo">Voice<em>Cast</em></div>
  <div class="sub">Quản trị hệ thống</div>
  {err_html}
  <div id="err2" class="err" style="display:none"></div>
  <div class="fg"><label>Tên đăng nhập</label>
    <input id="u" value="admin" autofocus placeholder="admin"></div>
  <div class="fg"><label>Mật khẩu</label>
    <input id="p" type="password" placeholder="••••••••"></div>
  <button onclick="doLogin()">Đăng nhập</button>
</div>
<script>
async function doLogin(){{
  const r=await fetch('/admin/login',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{username:document.getElementById('u').value,
                          password:document.getElementById('p').value}})}});
  const d=await r.json();
  if(r.ok){{window.location='/admin';}}
  else{{const e=document.getElementById('err2');
    e.textContent='⚠ '+(d.detail||'Lỗi đăng nhập');e.style.display='block';}}
}}
document.addEventListener('keydown',e=>{{if(e.key==='Enter')doLogin()}});
</script>
</body></html>"""

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    import argparse
    parser = argparse.ArgumentParser(description="VoiceCast + VoxCPM2")
    parser.add_argument("--model-id",  default=str(BASE_DIR / "VoxCPM2"))
    parser.add_argument("--host",      default="0.0.0.0")
    parser.add_argument("--port",      type=int,   default=8809)
    parser.add_argument("--gpu-mem",   type=float, default=0.75)
    parser.add_argument("--max-seqs",  type=int,   default=1)
    parser.add_argument("--no-model",  action="store_true",
                        help="Chạy không load model (debug UI)")
    args = parser.parse_args()

    global MODEL_ID, GPU_MEM, MAX_SEQS, HOST, PORT
    MODEL_ID = args.model_id
    GPU_MEM  = args.gpu_mem
    MAX_SEQS = args.max_seqs
    HOST     = args.host
    PORT     = args.port

    if args.no_model:
        logger.warning("[Nano] --no-model: bỏ qua load model")
        _nano_ready.set()

    uvicorn.run(app, host=HOST, port=PORT, log_level="info")


# ─── Model load/unload endpoints ─────────────────────────────────────────────
@app.get("/api/model/status")
def model_status():
    return {
        "loaded": _nano_server is not None,
        "loading": _model_loading,
        "error": str(_nano_error) if _nano_error else None,
    }

@app.post("/api/model/load")
def model_load():
    global _model_loading
    if _nano_server is not None:
        return {"ok": True, "msg": "Model đã load rồi"}
    if _model_loading:
        return {"ok": False, "msg": "Đang load..."}
    t = threading.Thread(target=_do_load, daemon=True)
    t.start()
    return {"ok": True, "msg": "Bắt đầu load model..."}

@app.post("/api/model/unload")
def model_unload():
    global _nano_server, _nano_error
    import gc, torch
    if _nano_server is None:
        return {"ok": True, "msg": "Model chưa load"}
    try:
        _nano_server.stop()
    except: pass
    _nano_server = None
    _nano_error  = None
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    logger.info("[Model] Unloaded ✅")
    return {"ok": True, "msg": "Model đã unload"}

if __name__ == "__main__":
    main()