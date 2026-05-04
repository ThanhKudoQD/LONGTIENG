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

import sqlite3
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
DB_PATH     = DATA_DIR / "voicecast.db"
GEN_DIR     = UPLOADS_DIR / "generated"

for d in [DATA_DIR, PUBLIC_DIR, UPLOADS_DIR,
          UPLOADS_DIR/"avatars", UPLOADS_DIR/"roles", GEN_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ─── Config ───────────────────────────────────────────────────────────────────
MODEL_ID   = str(BASE_DIR / "VoxCPM2")
GPU_MEM    = 0.75
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
        srv = get_nano()
        with get_db() as conn:
            roles = conn.execute(
                "SELECT id, character_name, lora_path FROM roles WHERE lora_path != ''"
            ).fetchall()
        for role in roles:
            lora_path = role["lora_path"].strip()
            if not lora_path or not os.path.exists(lora_path):
                continue
            try:
                lora_name = f"lora_{hash(lora_path) & 0xFFFFFF:06x}"
                if hasattr(srv, 'list_loras') and hasattr(srv, 'register_lora'):
                    registered = [l.name for l in srv.list_loras()]
                    if lora_name not in registered:
                        srv.register_lora(name=lora_name, path=lora_path)
                else:
                    logger.info(f"[LoRA] Version này không hỗ trợ register_lora, bỏ qua preload")
                    break
                    char_name = role["character_name"]
                    logger.info(f"[LoRA] Preloaded: {char_name} → {lora_name}")
            except Exception as e:
                char_name = role["character_name"]
                logger.warning(f"[LoRA] Preload failed {char_name}: {e}")
    except Exception as e:
        logger.warning(f"[LoRA] Preload all failed: {e}")

# ─── Database ─────────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS admins (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            username   TEXT UNIQUE NOT NULL,
            password   TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS actors (
            id         TEXT PRIMARY KEY,
            name       TEXT NOT NULL,
            gender     TEXT NOT NULL DEFAULT 'nam',
            birth_year INTEGER,
            avatar     TEXT DEFAULT '',
            bio        TEXT DEFAULT '',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS roles (
            id                   TEXT PRIMARY KEY,
            actor_id             TEXT NOT NULL,
            character_name       TEXT NOT NULL,
            show_name            TEXT DEFAULT '',
            type                 TEXT DEFAULT 'chinh',
            genre                TEXT DEFAULT 'hien-dai',
            description          TEXT DEFAULT '',
            audio                TEXT DEFAULT '',
            reference_audio_text TEXT DEFAULT '',
            lora_path            TEXT DEFAULT '',
            sort_order           INTEGER DEFAULT 0,
            created_at           DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(actor_id) REFERENCES actors(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS role_images (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            role_id    TEXT NOT NULL,
            url        TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            FOREIGN KEY(role_id) REFERENCES roles(id) ON DELETE CASCADE
        );
        """)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(roles)")]
        if "lora_path" not in cols:
            conn.execute("ALTER TABLE roles ADD COLUMN lora_path TEXT DEFAULT ''")
        conn.commit()

def seed_admin():
    username = os.environ.get("ADMIN_USERNAME", "admin")
    password = os.environ.get("ADMIN_PASSWORD", "admin123")
    with get_db() as conn:
        exists = conn.execute(
            "SELECT id FROM admins WHERE username=?", (username,)
        ).fetchone()
        if not exists:
            hashed = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            conn.execute(
                "INSERT INTO admins (username, password) VALUES (?,?)",
                (username, hashed)
            )
            conn.commit()
            logger.info(f"✅ Admin tạo thành công: {username}")

def uid():
    return hex(int(time.time() * 1000))[2:] + hex(int.from_bytes(
        os.urandom(3), 'big'))[2:]

# ─── DB Helpers ───────────────────────────────────────────────────────────────
def _get_roles(conn, actor_id: str):
    roles = conn.execute(
        "SELECT * FROM roles WHERE actor_id=? ORDER BY sort_order, created_at",
        (actor_id,)
    ).fetchall()
    result = []
    for r in roles:
        r = dict(r)
        imgs = conn.execute(
            "SELECT url FROM role_images WHERE role_id=? ORDER BY sort_order",
            (r["id"],)
        ).fetchall()
        r["images"] = [i["url"] for i in imgs]
        result.append(r)
    return result

def _get_actor(conn, actor_id: str):
    a = conn.execute("SELECT * FROM actors WHERE id=?", (actor_id,)).fetchone()
    if not a:
        return None
    a = dict(a)
    a["roles"] = _get_roles(conn, actor_id)
    return a

def _get_all_actors(conn):
    actors = conn.execute("SELECT * FROM actors ORDER BY name ASC").fetchall()
    result = []
    for a in actors:
        a = dict(a)
        a["roles"] = _get_roles(conn, a["id"])
        result.append(a)
    return result

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
    c = (control or "").strip()
    t = (text or "").strip()
    return f"({c}){t}" if c else t

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
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from dubeditor.database import init_db as dub_init_db
    dub_init_db()
    seed_admin()
    logger.info(f"✅ Server: http://{HOST}:{PORT}")
    yield

app = FastAPI(title="VoiceCast + VoxCPM2", version="3.0.0", lifespan=lifespan)

app.add_middleware(CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

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
    with get_db() as conn:
        admin = conn.execute(
            "SELECT * FROM admins WHERE username=?", (body.username,)
        ).fetchone()
    if not admin:
        raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng")
    if not bcrypt.checkpw(body.password.encode(), admin["password"].encode()):
        raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng")
    token = sign_token({"id": admin["id"], "username": admin["username"]})
    response.set_cookie("token", token, httponly=True,
                        max_age=JWT_EXPIRE * 86400)
    return {"token": token, "message": "Đăng nhập thành công"}

@app.post("/admin/logout")
async def do_logout(response: Response):
    response.delete_cookie("token")
    return {"message": "Đã đăng xuất"}

@app.post("/api/admin/change-password")
async def change_password(request: Request, admin=Depends(require_auth_api)):
    body = await request.json()
    with get_db() as conn:
        a = conn.execute(
            "SELECT * FROM admins WHERE username=?", (admin["username"],)
        ).fetchone()
        if not bcrypt.checkpw(body.get("current","").encode(),
                               a["password"].encode()):
            raise HTTPException(400, "Mật khẩu hiện tại không đúng")
        hashed = bcrypt.hashpw(
            body.get("newPass","").encode(), bcrypt.gensalt()).decode()
        conn.execute("UPDATE admins SET password=? WHERE id=?",
                     (hashed, a["id"]))
        conn.commit()
    return {"message": "Đã đổi mật khẩu"}

# ─── Public API ───────────────────────────────────────────────────────────────
@app.get("/api/actors")
async def api_actors():
    with get_db() as conn:
        return {"actors": _get_all_actors(conn)}

@app.get("/api/actors/{actor_id}")
async def api_actor(actor_id: str):
    with get_db() as conn:
        a = _get_actor(conn, actor_id)
    if not a:
        raise HTTPException(404, "Không tìm thấy")
    return a

# ─── Admin: Actors ────────────────────────────────────────────────────────────
@app.post("/api/admin/actors")
async def create_actor(request: Request, admin=Depends(require_auth_api)):
    body = await request.json()
    if not body.get("name", "").strip():
        raise HTTPException(400, "Tên là bắt buộc")
    new_id = uid()
    with get_db() as conn:
        conn.execute(
            "INSERT INTO actors (id,name,gender,birth_year,avatar,bio) VALUES (?,?,?,?,?,?)",
            (new_id, body["name"].strip(), body.get("gender","nam"),
             int(body.get("birth_year", 1990)),
             body.get("avatar",""), body.get("bio",""))
        )
        conn.commit()
    return {"id": new_id, "message": "Đã tạo diễn viên"}

@app.put("/api/admin/actors/{actor_id}")
async def update_actor(actor_id: str, request: Request,
                       admin=Depends(require_auth_api)):
    body = await request.json()
    if not body.get("name","").strip():
        raise HTTPException(400, "Tên là bắt buộc")
    with get_db() as conn:
        conn.execute(
            """UPDATE actors SET name=?,gender=?,birth_year=?,avatar=?,bio=?,
               updated_at=CURRENT_TIMESTAMP WHERE id=?""",
            (body["name"].strip(), body.get("gender","nam"),
             int(body.get("birth_year",1990)),
             body.get("avatar",""), body.get("bio",""), actor_id)
        )
        conn.commit()
    return {"message": "Đã cập nhật"}

@app.delete("/api/admin/actors/{actor_id}")
async def delete_actor(actor_id: str, admin=Depends(require_auth_api)):
    with get_db() as conn:
        conn.execute("DELETE FROM actors WHERE id=?", (actor_id,))
        conn.commit()
    return {"message": "Đã xóa"}

# ─── Admin: Roles ─────────────────────────────────────────────────────────────
@app.post("/api/admin/actors/{actor_id}/roles")
async def create_role(actor_id: str, request: Request,
                      admin=Depends(require_auth_api)):
    body = await request.json()
    new_id = uid()
    with get_db() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM roles WHERE actor_id=?", (actor_id,)
        ).fetchone()[0]
        conn.execute(
            """INSERT INTO roles
               (id,actor_id,character_name,show_name,type,genre,
                description,audio,reference_audio_text,lora_path,sort_order)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (new_id, actor_id,
             body.get("character_name",""), body.get("show_name",""),
             body.get("type","chinh"),      body.get("genre","hien-dai"),
             body.get("description",""),    body.get("audio",""),
             body.get("reference_audio_text",""),
             body.get("lora_path",""),      count)
        )
        if body.get("images"):
            for i, url in enumerate(body["images"]):
                conn.execute(
                    "INSERT INTO role_images (role_id,url,sort_order) VALUES (?,?,?)",
                    (new_id, url, i)
                )
        conn.commit()
    return {"id": new_id, "message": "Đã thêm vai"}

@app.put("/api/admin/roles/{role_id}")
async def update_role(role_id: str, request: Request,
                      admin=Depends(require_auth_api)):
    body = await request.json()
    with get_db() as conn:
        conn.execute(
            """UPDATE roles SET character_name=?,show_name=?,type=?,genre=?,
               description=?,audio=?,reference_audio_text=?,lora_path=?
               WHERE id=?""",
            (body.get("character_name",""), body.get("show_name",""),
             body.get("type","chinh"),      body.get("genre","hien-dai"),
             body.get("description",""),    body.get("audio",""),
             body.get("reference_audio_text",""),
             body.get("lora_path",""),      role_id)
        )
        conn.execute("DELETE FROM role_images WHERE role_id=?", (role_id,))
        if body.get("images"):
            for i, url in enumerate(body["images"]):
                conn.execute(
                    "INSERT INTO role_images (role_id,url,sort_order) VALUES (?,?,?)",
                    (role_id, url, i)
                )
        conn.commit()
    return {"message": "Đã cập nhật vai"}

@app.delete("/api/admin/roles/{role_id}")
async def delete_role(role_id: str, admin=Depends(require_auth_api)):
    with get_db() as conn:
        conn.execute("DELETE FROM roles WHERE id=?", (role_id,))
        conn.commit()
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

# ─── TTS API ──────────────────────────────────────────────────────────────────
class TTSRequest(BaseModel):
    role_id: str
    text: str
    mode: str = "clone"           # "clone" | "ultimate"
    control_instruction: str = ""
    cfg_value: float = 3.0
    locdit_steps: int = 40
    use_lora: bool = False

@app.post("/api/tts/generate")
async def tts_generate(body: TTSRequest):
    with get_db() as conn:
        role = conn.execute(
            "SELECT * FROM roles WHERE id=?", (body.role_id,)
        ).fetchone()
    if not role:
        raise HTTPException(404, f"Không tìm thấy role: {body.role_id}")
    role = dict(role)

    audio_url = role.get("audio", "")
    ref_text  = role.get("reference_audio_text", "")
    lora_path = role.get("lora_path", "").strip() or None

    # URL → absolute path
    audio_path = None
    if audio_url:
        candidate = PUBLIC_DIR / audio_url.lstrip("/")
        if candidate.exists():
            audio_path = str(candidate)

    # Tự động dùng LoRA nếu role có lora_path (không cần use_lora=true)
    # if not body.use_lora:
    #     lora_path = None
    if lora_path and not os.path.exists(lora_path):
        logger.warning(f"LoRA path không tồn tại: {lora_path}")
        lora_path = None

    if not audio_path and not lora_path:
        raise HTTPException(400,
            "Role này chưa có audio mẫu hoặc LoRA. Không thể generate.")

    target_text = _build_text(body.text, body.control_instruction)

    # Chạy trong thread riêng — tránh block asyncio event loop
    loop = asyncio.get_event_loop()
    try:
        if body.mode == "ultimate" and audio_path and ref_text:
            wav = await loop.run_in_executor(None, lambda: _generate_sync(
                target_text=body.text.strip(),
                reference_wav_path=audio_path,
                prompt_wav_path=audio_path,
                prompt_text=ref_text,
                cfg_value=body.cfg_value,
                lora_path=lora_path,
            ))
            mode_used = "ultimate"
        elif audio_path:
            wav = await loop.run_in_executor(None, lambda: _generate_sync(
                target_text=target_text,
                reference_wav_path=audio_path,
                cfg_value=body.cfg_value,
                lora_path=lora_path,
            ))
            mode_used = "clone" + (" + lora" if lora_path else "")
        else:
            wav = await loop.run_in_executor(None, lambda: _generate_sync(
                target_text=target_text,
                cfg_value=body.cfg_value,
                lora_path=lora_path,
            ))
            mode_used = "lora_only"

        url = _save_generated(wav)
        return {
            "url": url,
            "mode": mode_used,
            "role_id": body.role_id,
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