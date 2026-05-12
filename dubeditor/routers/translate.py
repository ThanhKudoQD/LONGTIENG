"""
dubeditor/routers/translate.py
Pipeline dịch thuật tích hợp vào DubEditor.

Endpoints:
  GET  /dub/api/projects/{pid}/bible
  POST /dub/api/projects/{pid}/translate/analyze   → Pass 1
  POST /dub/api/projects/{pid}/translate/run       → Pass 3 (background + SSE)
  GET  /dub/api/projects/{pid}/translate/progress  → SSE stream
  POST /dub/api/projects/{pid}/translate/retranslate
  POST /dub/api/projects/{pid}/translate/cancel
  POST /dub/api/projects/{pid}/translate/reset
"""
import asyncio, json, logging, sys, time
from pathlib import Path
from pydantic import BaseModel
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from dubeditor.database import get_db, SessionLocal
from dubeditor.models import Project, Subtitle, Character, TranslateChunk
from dubeditor.schemas import (
    TranslateAnalyzeRequest, TranslateRunRequest, RetranslateRequest,
    TranslateRunChunksRequest,
)

logger = logging.getLogger(__name__)
router = APIRouter()

BASE_DIR = Path(__file__).parent.parent.parent

# SSE subscriber queues — project_id → list[Queue]
_progress: dict[int, list[asyncio.Queue]] = {}

CHAR_COLORS = [
    '#185FA5','#993C1D','#0F6E56','#854F0B','#534AB7',
    '#D4537E','#3B6D11','#0C6E7A','#7A2D6E','#5F5E5A',
]


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _pub(pid: int, data: dict):
    msg = f"event: progress\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
    for q in list(_progress.get(pid, [])):
        try:
            await q.put(msg)
        except Exception:
            pass


def _sec_to_srt_time(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    ms = int(round((sec - int(sec)) * 1000))
    return f"{h:02d}:{m:02d}:{int(sec):02d},{ms:03d}"


def _subs_to_blocks(subs: list[Subtitle]) -> list[dict]:
    return [
        {
            "index": s.index,
            "start": _sec_to_srt_time(s.start_time),
            "end":   _sec_to_srt_time(s.end_time),
            "text":  s.original_text or s.text or "",
        }
        for s in sorted(subs, key=lambda x: x.index)
    ]


def _load_translator():
    """Import translator.py từ dự án dịch đặt tại srt_translator/backend/."""
    trans_dir = BASE_DIR / "srt_translator" / "backend"
    if trans_dir.exists() and str(trans_dir) not in sys.path:
        sys.path.insert(0, str(trans_dir))
    try:
        import translator as t
        return t
    except ImportError:
        raise RuntimeError(
            "Chưa tích hợp module dịch. "
            "Copy thư mục backend/ của dự án SRT Translator vào srt_translator/backend/"
        )


def _build_retranslate_prompt(original: str, current: str, bible: dict,
                               ctx_before: list, ctx_after: list, hint: str) -> str:
    chars_str = "\n".join(
        f"- {c.get('vi','?')} ({c.get('zh','?')}): tự xưng \"{c.get('tu_xung','?')}\""
        for c in (bible.get("nhan_vat") or [])[:10]
    )
    terms_str = "\n".join(
        f"- {zh} → {vi}"
        for zh, vi in list((bible.get("thuat_ngu") or {}).items())[:10]
    )
    return f"""Dịch lại 1 dòng phụ đề tiếng Trung sang tiếng Việt.

NGUYÊN BẢN: {original}
BẢN HIỆN TẠI: {current}
YÊU CẦU: {hint}

NHÂN VẬT:
{chars_str or "(chưa có)"}

THUẬT NGỮ:
{terms_str or "(chưa có)"}

MẠCH TRƯỚC: {" | ".join(ctx_before) if ctx_before else "(đầu cảnh)"}
MẠCH SAU:   {" | ".join(ctx_after)  if ctx_after  else "(cuối cảnh)"}

Chỉ trả về bản dịch, không giải thích, không dấu ngoặc kép."""


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/projects/{pid}/bible")
def get_bible(pid: int, db: Session = Depends(get_db)):
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "Project not found")
    if not p.bible_json:
        return {"bible": None}
    try:
        return {"bible": json.loads(p.bible_json), "source_lang": p.source_lang}
    except Exception:
        return {"bible": None}


@router.post("/projects/{pid}/translate/analyze")
async def analyze(pid: int, req: TranslateAnalyzeRequest, db: Session = Depends(get_db)):
    """Pass 1 — phân tích phim, xây Bible, tự tạo Characters."""
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "Project not found")

    subs = db.query(Subtitle).filter(
        Subtitle.project_id == pid
    ).order_by(Subtitle.index).all()

    if not subs:
        raise HTTPException(400, "Project chưa có subtitle nào.")

    try:
        t = _load_translator()
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    srt_blocks = _subs_to_blocks(subs)

    try:
        bible, api_result = await t.pass1_analyze(
            srt_blocks=srt_blocks,
            api_key=req.api_key,
            model=req.model,
        )
    except Exception as e:
        logger.error(f"Pass1 pid={pid}: {e}", exc_info=True)
        raise HTTPException(500, f"Pass 1 lỗi: {e}")

    # Lưu Bible
    p.bible_json  = json.dumps(bible, ensure_ascii=False)
    p.source_lang = req.source_lang
    db.commit()

    # Tạo Characters từ nhan_vat trong Bible
    existing_names = {c.name for c in db.query(Character).filter(Character.project_id == pid).all()}
    created = []
    for i, nv in enumerate(bible.get("nhan_vat") or []):
        name = (nv.get("vi") or "").strip()
        if not name or name in existing_names:
            continue
        db.add(Character(
            project_id=pid,
            name=name,
            description=nv.get("than_phan", ""),
            color=CHAR_COLORS[i % len(CHAR_COLORS)],
        ))
        existing_names.add(name)
        created.append(name)
    db.commit()

    return {
        "bible":         bible,
        "chars_created": created,
        "tokens_in":     api_result.get("tokens_in", 0),
        "tokens_out":    api_result.get("tokens_out", 0),
        "timing_ms":     api_result.get("timing_ms", 0),
    }


@router.post("/projects/{pid}/translate/run")
async def run_translation(pid: int, req: TranslateRunRequest,
                           bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Pass 3 — dịch song song theo chunks, stream progress qua SSE."""
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "Project not found")
    if not p.bible_json:
        raise HTTPException(400, "Chưa có Bible. Hãy chạy Pass 1 trước.")

    bg.add_task(_run_pass3_bg, pid, req.api_key, req.model,
                req.concurrency, req.enable_qc, None)
    return {"ok": True}


@router.post("/projects/{pid}/translate/run-chunks")
async def run_translation_chunks(pid: int, req: TranslateRunChunksRequest,
                                  bg: BackgroundTasks, db: Session = Depends(get_db)):
    """Dịch lại một số chunk cụ thể (theo index trong scene_map).

    Dùng để cho phép FE bấm nút "Dịch lại chunk này" mà không phải
    chạy lại toàn bộ Pass 3.
    """
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "Project not found")
    if not p.bible_json:
        raise HTTPException(400, "Chưa có Bible. Hãy chạy Pass 1 trước.")
    if not req.chunk_indices:
        raise HTTPException(400, "chunk_indices rỗng — không có chunk nào để dịch.")

    only_set = set(int(i) for i in req.chunk_indices)
    bg.add_task(_run_pass3_bg, pid, req.api_key, req.model,
                req.concurrency, False, only_set)
    return {"ok": True, "chunk_indices": sorted(only_set)}


async def _run_pass3_bg(pid: int, api_key: str, model: str,
                         concurrency: int, enable_qc: bool,
                         only_indices: set | None = None):
    db = SessionLocal()
    try:
        t     = _load_translator()
        p     = db.query(Project).filter(Project.id == pid).first()
        bible = json.loads(p.bible_json)

        subs      = db.query(Subtitle).filter(
            Subtitle.project_id == pid
        ).order_by(Subtitle.index).all()
        srt_blocks = _subs_to_blocks(subs)

        all_chunks = t.build_chunks_from_bible(srt_blocks, bible)

        # Nếu chỉ định only_indices → giữ index gốc nhưng chỉ chạy các chunk được chọn.
        # Quan trọng: chunk_idx truyền vào do_chunk phải khớp với index trong scene_map
        # để FE update đúng chunk.
        if only_indices is not None:
            chunks_to_run = [(i, c) for i, c in enumerate(all_chunks) if i in only_indices]
        else:
            chunks_to_run = list(enumerate(all_chunks))

        total  = len(chunks_to_run)
        done   = 0

        if total == 0:
            await _pub(pid, {
                "stage": "done", "message": "Không có chunk nào để dịch.",
                "percent": 100, "chunks_total": 0, "chunks_done": 0,
            })
            return

        await _pub(pid, {
            "stage": "pass3", "message": f"Bắt đầu dịch {total} chunks...",
            "percent": 0, "chunks_total": total, "chunks_done": 0,
        })

        # Map tên → character_id
        chars        = db.query(Character).filter(Character.project_id == pid).all()
        name_to_char = {c.name: c.id for c in chars}

        sem = asyncio.Semaphore(concurrency)

        async def do_chunk(chunk: dict, chunk_idx: int):
            nonlocal done
            async with sem:
                # Notify FE: chunk bắt đầu
                await _pub(pid, {
                    "stage": "chunk_start",
                    "chunk_index": chunk_idx,
                    "message": f"Đang dịch chunk {chunk_idx + 1}...",
                })
                # Pre-mark status='run' trong DB để khi user F5 thấy chunk đang chạy
                try:
                    tc_run = db.query(TranslateChunk).filter(
                        TranslateChunk.project_id  == pid,
                        TranslateChunk.chunk_index == chunk_idx,
                    ).first()
                    if tc_run:
                        tc_run.status = "run"
                        tc_run.error  = None
                    db.commit()
                except Exception:
                    db.rollback()
                try:
                    # pass3_translate_chunk trả tuple (entries, call_info)
                    entries, call_info = await t.pass3_translate_chunk(
                        chunk=chunk, bible=bible,
                        api_key=api_key, model=model,
                    )
                    # entries: [{index, original_text, translated_text, ...}]
                    fe_entries = []
                    # Build name→char_id map từ Bible nhan_vat
                    bible_chars = bible.get("nhan_vat") or []
                    vi_to_char = {}
                    for nv in bible_chars:
                        vi_name = (nv.get("vi") or "").strip()
                        if vi_name and vi_name in name_to_char:
                            vi_to_char[vi_name] = name_to_char[vi_name]

                    fe_entries = []
                    for entry in (entries or []):
                        idx      = entry.get("index")
                        raw_text = (entry.get("translated_text") or "").strip()
                        original = (entry.get("original_text") or "").strip()
                        # speaker từ entry (nếu translator đã parse) hoặc tự split từ raw_text
                        speaker  = (entry.get("speaker") or "").strip()
                        new_text = raw_text

                        # Nếu chưa có speaker, thử split "SpeakerName|actual text"
                        if not speaker and "|" in raw_text:
                            parts = raw_text.split("|", 1)
                            candidate = parts[0].strip()
                            # Luôn split nếu phần trước | trông như tên (ngắn, không có dấu câu lạ)
                            if candidate and len(candidate) <= 30 and not any(x in candidate for x in ['.', '!', '?', '…', '\n']):
                                speaker  = candidate
                                new_text = parts[1].strip() if parts[1].strip() else raw_text

                        char_id = vi_to_char.get(speaker) if speaker else None

                        sub = next((s for s in subs if s.index == idx), None)
                        if sub and new_text:
                            sub.text = new_text
                            sub.original_text = original or sub.original_text
                            if char_id and not sub.character_id:
                                sub.character_id = char_id

                        fe_entries.append({
                            "index":      idx,
                            "original":   original,
                            "translated": new_text,
                            "speaker":    speaker,
                        })

                    # Fallback: scene chỉ có 1 nhân vật → gán dòng chưa có
                    scene_info = chunk.get("scene_info") or {}
                    scene_nv_list = scene_info.get("nhan_vat") or []
                    if len(scene_nv_list) == 1:
                        single_char_id = vi_to_char.get(scene_nv_list[0])
                        if single_char_id:
                            for entry in fe_entries:
                                sub = next((s for s in subs if s.index == entry["index"]), None)
                                if sub and not sub.character_id:
                                    sub.character_id = single_char_id
                                    entry["speaker"] = scene_nv_list[0]
                    # Lưu prompt/response vào translate_chunks + đánh dấu status='done'
                    try:
                        tc = db.query(TranslateChunk).filter(
                            TranslateChunk.project_id  == pid,
                            TranslateChunk.chunk_index == chunk_idx,
                        ).first()
                        if tc:
                            tc.status     = "done"
                            tc.error      = None
                            tc.prompt     = call_info.get("prompt", "")
                            tc.response   = call_info.get("response", "")
                            tc.tokens_in  = call_info.get("tokens_in", 0)
                            tc.tokens_out = call_info.get("tokens_out", 0)
                            tc.timing_ms  = call_info.get("timing_ms", 0)
                            tc.model      = model
                            # Bản dịch đã thay đổi → invalidate QC cũ (kết quả review
                            # dựa trên bản dịch trước đó không còn đúng nữa).
                            tc.qc_response   = None
                            tc.qc_van_de     = None
                            tc.qc_tong_ket   = None
                            tc.qc_tokens_in  = 0
                            tc.qc_tokens_out = 0
                            tc.qc_timing_ms  = 0
                            tc.qc_run_at     = None
                        else:
                            blocks = chunk.get("blocks") or []
                            s_line = blocks[0]["index"]  if blocks else 0
                            e_line = blocks[-1]["index"] if blocks else 0
                            db.add(TranslateChunk(
                                project_id  = pid,
                                chunk_index = chunk_idx,
                                start_line  = s_line,
                                end_line    = e_line,
                                status      = "done",
                                prompt      = call_info.get("prompt", ""),
                                response    = call_info.get("response", ""),
                                tokens_in   = call_info.get("tokens_in", 0),
                                tokens_out  = call_info.get("tokens_out", 0),
                                timing_ms   = call_info.get("timing_ms", 0),
                                model       = model,
                            ))
                        db.commit()
                    except Exception as tc_err:
                        logger.warning(f"[TranslateChunk save] {tc_err}")
                        db.rollback()

                    done += 1
                    await _pub(pid, {
                        "stage":       "chunk_done",
                        "chunk_index": chunk_idx,
                        "message":     f"Chunk {done}/{total} xong",
                        "percent":     round(done / total * 100, 1),
                        "chunks_total": total,
                        "chunks_done":  done,
                        "tokens_in":   call_info.get("tokens_in", 0),
                        "tokens_out":  call_info.get("tokens_out", 0),
                        "timing_ms":   call_info.get("timing_ms", 0),
                        "response":    call_info.get("response", ""),   # raw AI response
                        "prompt":      call_info.get("prompt", ""),
                        "entries":     fe_entries,
                    })
                except Exception as e:
                    logger.error(f"[Pass3 pid={pid} chunk={chunk_idx}] {e}", exc_info=True)
                    # Lưu status='err' + error message vào DB
                    try:
                        tc_err_row = db.query(TranslateChunk).filter(
                            TranslateChunk.project_id  == pid,
                            TranslateChunk.chunk_index == chunk_idx,
                        ).first()
                        if tc_err_row:
                            tc_err_row.status = "err"
                            tc_err_row.error  = str(e)[:500]
                        else:
                            blocks = chunk.get("blocks") or []
                            s_line = blocks[0]["index"]  if blocks else 0
                            e_line = blocks[-1]["index"] if blocks else 0
                            db.add(TranslateChunk(
                                project_id  = pid,
                                chunk_index = chunk_idx,
                                start_line  = s_line,
                                end_line    = e_line,
                                status      = "err",
                                error       = str(e)[:500],
                                model       = model,
                            ))
                        db.commit()
                    except Exception:
                        db.rollback()
                    done += 1
                    await _pub(pid, {
                        "stage":       "chunk_error",
                        "chunk_index": chunk_idx,
                        "message":     f"Chunk {chunk_idx + 1} lỗi",
                        "percent":     round(done / total * 100, 1),
                        "chunks_total": total,
                        "chunks_done":  done,
                        "error":       str(e)[:200],
                    })

        await asyncio.gather(*[do_chunk(chunk, idx) for idx, chunk in chunks_to_run])

        await _pub(pid, {
            "stage": "done",
            "message": f"Dịch xong {total} chunks!",
            "percent": 100,
            "chunks_total": total, "chunks_done": total,
        })

    except Exception as e:
        logger.error(f"[Pass3 bg pid={pid}] {e}", exc_info=True)
        await _pub(pid, {
            "stage": "error", "message": str(e),
            "percent": 0, "chunks_total": 0, "chunks_done": 0,
        })
    finally:
        db.close()


@router.get("/projects/{pid}/translate/progress")
async def progress_stream(pid: int):
    """SSE — stream tiến trình dịch."""
    q: asyncio.Queue = asyncio.Queue()
    _progress.setdefault(pid, []).append(q)

    async def gen():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=5.0)
                    yield msg
                    # Chỉ đóng SSE khi gặp event 'done' / 'error' của Pass 3 (cấp pipeline).
                    # Các stage QC như qc_done / chunk_done / qc_error KHÔNG đóng,
                    # vì FE còn cần lắng nghe tiếp event sau đó (QC chunk khác,
                    # hoặc tiếp tục Pass 3).
                    if '"stage": "done"' in msg or '"stage": "error"' in msg:
                        break
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            try:
                _progress.get(pid, []).remove(q)
            except ValueError:
                pass

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/projects/{pid}/translate/retranslate")
async def retranslate(pid: int, req: RetranslateRequest, db: Session = Depends(get_db)):
    """Dịch lại 1 dòng — trả N bản alternative dùng Bible context."""
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "Project not found")

    bible = {}
    if p.bible_json:
        try:
            bible = json.loads(p.bible_json)
        except Exception:
            pass

    try:
        t = _load_translator()
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    # Context trước/sau
    subs = db.query(Subtitle).filter(
        Subtitle.project_id == pid
    ).order_by(Subtitle.index).all()
    idx = next((i for i, s in enumerate(subs) if s.id == req.subtitle_id), 0)
    ctx_before = [s.text for s in subs[max(0, idx-3):idx] if s.text]
    ctx_after  = [s.text for s in subs[idx+1:idx+4] if s.text]

    hints = [
        "Tự nhiên, gần gũi hơn với khán giả Việt",
        "Trung thành hơn với nguyên bản, giữ sắc thái",
    ]

    results = []
    for i in range(min(req.variants, 2)):
        try:
            res = await t._call_api(
                prompt=_build_retranslate_prompt(
                    original=req.original_text,
                    current=req.current_text,
                    bible=bible,
                    ctx_before=ctx_before,
                    ctx_after=ctx_after,
                    hint=hints[i],
                ),
                api_key=req.api_key,
                model=req.model,
                temperature=0.4 + i * 0.2,
            )
            results.append({
                "text": res["text"].strip(),
                "note": hints[i],
            })
        except Exception as e:
            results.append({"text": f"[Lỗi: {e}]", "note": None})

    return {"alternatives": results}


def _extract_api_key_from_project(p: Project) -> str:
    """Placeholder — api_key đến từ FE request, không lưu trong DB."""
    return ""


@router.post("/projects/{pid}/translate/cancel")
async def cancel(pid: int):
    for q in list(_progress.get(pid, [])):
        await q.put(
            'event: progress\ndata: {"stage":"error","message":"Đã hủy.","percent":0,"chunks_total":0,"chunks_done":0}\n\n'
        )
    _progress.pop(pid, None)
    return {"ok": True}


@router.post("/projects/{pid}/translate/reset")
async def reset(pid: int, db: Session = Depends(get_db)):
    """Xóa bản dịch, giữ Bible + original_text."""
    subs = db.query(Subtitle).filter(Subtitle.project_id == pid).all()
    for s in subs:
        s.text        = ""
        s.tts_done    = False
        s.audio_path  = None
        s.wav_duration = None
    db.commit()
    return {"ok": True, "reset_count": len(subs)}


# ─── Get saved chunks (prompt/response từ DB) ────────────────────────────────

@router.get("/projects/{pid}/translate/chunks")
def get_translate_chunks(pid: int, db: Session = Depends(get_db)):
    """Load trạng thái + prompt/response + QC snapshot của tất cả chunks."""
    chunks = db.query(TranslateChunk).filter(
        TranslateChunk.project_id == pid
    ).order_by(TranslateChunk.chunk_index).all()
    out = []
    for c in chunks:
        # Parse QC JSON nếu có
        qc_van_de   = None
        qc_tong_ket = None
        try:
            if c.qc_van_de:
                qc_van_de = json.loads(c.qc_van_de)
        except Exception:
            qc_van_de = None
        try:
            if c.qc_tong_ket:
                qc_tong_ket = json.loads(c.qc_tong_ket)
        except Exception:
            qc_tong_ket = None

        out.append({
            "chunk_index":  c.chunk_index,
            "start_line":   c.start_line,
            "end_line":     c.end_line,
            "status":       c.status or "wait",
            "error":        c.error or "",
            "prompt":       c.prompt or "",
            "response":     c.response or "",
            "tokens_in":    c.tokens_in,
            "tokens_out":   c.tokens_out,
            "timing_ms":    c.timing_ms,
            "model":        c.model or "",
            # QC snapshot
            "qc_response":   c.qc_response or "",
            "qc_van_de":     qc_van_de,
            "qc_tong_ket":   qc_tong_ket,
            "qc_tokens_in":  c.qc_tokens_in or 0,
            "qc_tokens_out": c.qc_tokens_out or 0,
            "qc_timing_ms":  c.qc_timing_ms or 0,
            "qc_model":      c.qc_model or "",
            "qc_run_at":     c.qc_run_at.isoformat() if c.qc_run_at else "",
        })
    return out


@router.delete("/projects/{pid}/translate/chunks/{chunk_index}")
def delete_translate_chunk(pid: int, chunk_index: int, db: Session = Depends(get_db)):
    """Xóa bản dịch của 1 chunk:
      - Xóa row trong translate_chunks (prompt, response, QC...)
      - Reset Subtitle trong phạm vi chunk: clear text dịch, clear character_id
        (giữ original_text vì đó là gốc tiếng Trung, không phải bản dịch).

    Sau khi xóa: chunk sẽ về trạng thái 'wait' (chưa dịch).
    """
    p = db.query(Project).filter(Project.id == pid).first()
    if not p:
        raise HTTPException(404, "Project not found")

    # Lấy phạm vi dòng từ scene_map (nếu có) hoặc từ row translate_chunks
    bible = json.loads(p.bible_json) if p.bible_json else {}
    scene_map = bible.get("scene_map") or []

    start_line = end_line = None
    if 0 <= chunk_index < len(scene_map):
        scene = scene_map[chunk_index]
        start_line = scene.get("tu_dong")
        end_line   = scene.get("den_dong")

    # Fallback: lấy từ row translate_chunks
    tc = db.query(TranslateChunk).filter(
        TranslateChunk.project_id  == pid,
        TranslateChunk.chunk_index == chunk_index,
    ).first()
    if tc and (start_line is None or end_line is None):
        start_line = tc.start_line
        end_line   = tc.end_line

    if start_line is None or end_line is None:
        raise HTTPException(400, "Không xác định được phạm vi dòng của chunk này")

    # Reset subtitles trong phạm vi chunk
    subs = db.query(Subtitle).filter(
        Subtitle.project_id == pid,
        Subtitle.index >= start_line,
        Subtitle.index <= end_line,
    ).all()
    reset_count = 0
    for s in subs:
        # Restore text về original (gốc tiếng Trung) nếu đã có original_text,
        # ngược lại để text rỗng. KHÔNG xóa original_text vì đó là gốc, không phải bản dịch.
        if s.original_text:
            s.text = s.original_text
        else:
            s.text = ""
        s.character_id = None
        reset_count += 1

    # Xóa row translate_chunks (hoặc reset về wait nếu muốn giữ history)
    if tc:
        db.delete(tc)

    db.commit()
    return {
        "ok": True,
        "chunk_index": chunk_index,
        "start_line":  start_line,
        "end_line":    end_line,
        "subs_reset":  reset_count,
    }




@router.post("/projects/{pid}/translate/fix-speaker-text")
async def fix_speaker_text(pid: int, db: Session = Depends(get_db)):
    """Fix subtitles bị lưu dạng 'Speaker|text' — tách ra lưu đúng."""
    subs = db.query(Subtitle).filter(Subtitle.project_id == pid).all()
    chars = db.query(Character).filter(Character.project_id == pid).all()
    name_to_char = {c.name: c.id for c in chars}
    
    fixed = 0
    for s in subs:
        if not s.text or '|' not in s.text:
            continue
        parts = s.text.split('|', 1)
        candidate = parts[0].strip()
        actual_text = parts[1].strip() if len(parts) > 1 else ''
        # Chỉ fix nếu phần trước | trông như tên (ngắn, không có dấu câu)
        if (candidate and actual_text and len(candidate) <= 30
                and not any(x in candidate for x in ['.', '!', '?', '…'])):
            s.text = actual_text
            # Thử gán character nếu chưa có
            if not s.character_id and candidate in name_to_char:
                s.character_id = name_to_char[candidate]
            fixed += 1
    
    db.commit()
    return {"fixed": fixed, "total": len(subs)}

# ─── QC Review endpoint ────────────────────────────────────────────────────────

class ReviewEntry(BaseModel):
    index:      int
    original:   str
    translated: str
    speaker:    str = ""    # tên Hán Việt của nhân vật đang được gán cho dòng này

class ReviewChunkRequest(BaseModel):
    api_key:     str
    model:       str = "gemini-2.5-flash"
    chunk_index: int
    entries:     list[ReviewEntry]

@router.post("/projects/{pid}/translate/review-chunk")
async def review_chunk(pid: int, req: ReviewChunkRequest, db: Session = Depends(get_db)):
    """QC Review 1 chunk — dùng pass4_review_chunk từ translator.

    Publish SSE events trong các stage để FE hiển thị trạng thái rõ ràng:
      - qc_start:      bắt đầu (đã build prompt, ước tính ETA)
      - qc_calling:    đang gọi API
      - qc_retrying:   gặp retry (kèm wait & error)
      - qc_responding: đã nhận response, đang parse
      - qc_done:       hoàn tất (kèm tokens, timing)
      - qc_error:      lỗi

    Output mỗi entry FE: {
      index, original, translated,
      fixed, issue,                        # backward-compat (cho bảng cũ)
      loai_loi,                            # speaker|van_phong|xung_ho|...
      speaker_hien_tai, speaker_de_xuat,
      speaker_de_xuat_char_id,             # resolve qua bảng Characters
      bang_chung, do_tin_cay,
    }
    """
    p = db.query(Project).filter(Project.id == pid).first()
    if not p or not p.bible_json:
        raise HTTPException(400, "Project chưa có Bible")

    try:
        t = _load_translator()
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    bible = json.loads(p.bible_json)

    # Lookup scene_info thật từ Bible.scene_map theo chunk_index.
    scene_map = bible.get("scene_map") or []
    scene_info = None
    if 0 <= req.chunk_index < len(scene_map):
        scene_info = scene_map[req.chunk_index]

    chunk = {
        "index":      req.chunk_index,
        "blocks":     [],
        "scene_info": scene_info,
        "tom_tat":    (scene_info or {}).get("tom_tat", ""),
    }
    entries_for_p4 = [
        {
            "index":           e.index,
            "original_text":   e.original,
            "translated_text": e.translated,
            "speaker":         e.speaker,
        }
        for e in req.entries
    ]

    # ETA dự đoán: dựa trên số dòng × hệ số kinh nghiệm (model output ~10-15 token/giây
    # cho Gemini Flash, ~5 token/giây cho Pro). Mỗi dòng ~30 token output → 2-6s/dòng.
    n_lines = len(req.entries)
    is_pro_model = "pro" in (req.model or "").lower() or "gpt-4" in (req.model or "").lower() or "gpt-5" in (req.model or "").lower()
    eta_seconds = int(n_lines * (4.5 if is_pro_model else 2.0)) + 5  # +5s overhead

    # SSE: qc_start
    await _pub(pid, {
        "stage":       "qc_start",
        "chunk_index": req.chunk_index,
        "message":     f"Đang chuẩn bị Pass 4 cho {n_lines} dòng...",
        "n_lines":     n_lines,
        "model":       req.model,
        "eta_seconds": eta_seconds,
    })

    # Callback từ translator khi retry — forward thành event qc_retrying
    async def on_retry(attempt: int, max_retry: int, wait: int, err: str):
        await _pub(pid, {
            "stage":       "qc_retrying",
            "chunk_index": req.chunk_index,
            "attempt":     attempt,
            "max_retry":   max_retry,
            "wait":        wait,
            "error":       str(err)[:200],
            "message":     f"Retry {attempt}/{max_retry} sau {wait}s ({str(err)[:60]})",
        })

    # SSE: qc_calling
    await _pub(pid, {
        "stage":       "qc_calling",
        "chunk_index": req.chunk_index,
        "message":     f"Đang gọi {req.model}... (ETA ~{eta_seconds}s)",
        "eta_seconds": eta_seconds,
    })

    try:
        result = await t.pass4_review_chunk(
            chunk=chunk,
            bible=bible,
            entries=entries_for_p4,
            api_key=req.api_key,
            model=req.model,
            on_retry=on_retry,
        )
    except Exception as e:
        logger.error(f"pass4 error: {e}", exc_info=True)
        await _pub(pid, {
            "stage":       "qc_error",
            "chunk_index": req.chunk_index,
            "message":     f"Lỗi: {str(e)[:200]}",
            "error":       str(e),
        })
        raise HTTPException(500, f"Pass 4 lỗi: {e}")

    if not result:
        await _pub(pid, {
            "stage":       "qc_error",
            "chunk_index": req.chunk_index,
            "message":     "Pass 4 không trả về kết quả",
        })
        raise HTTPException(500, "Pass 4 không trả về kết quả")

    # SSE: qc_responding — đã nhận response, đang xử lý
    await _pub(pid, {
        "stage":       "qc_responding",
        "chunk_index": req.chunk_index,
        "message":     "Đã nhận phản hồi, đang phân tích...",
        "tokens_out":  result.get("_tokens_out", 0),
    })

    van_de   = result.get("van_de") or []
    tong_ket = result.get("tong_ket") or {}

    # Resolve speaker_de_xuat → character_id
    chars = db.query(Character).filter(Character.project_id == pid).all()
    name_to_id = {c.name: c.id for c in chars}

    issue_map = {v.get("dong"): v for v in van_de if v.get("dong") is not None}
    fe_entries = []
    for e in req.entries:
        issue = issue_map.get(e.index)
        if not issue:
            fe_entries.append({
                "index":                    e.index,
                "original":                 e.original,
                "translated":               e.translated,
                "speaker":                  e.speaker,
                "fixed":                    e.translated,
                "issue":                    "",
                "loai_loi":                 "",
                "speaker_hien_tai":         e.speaker,
                "speaker_de_xuat":          "",
                "speaker_de_xuat_char_id":  None,
                "bang_chung":               "",
                "do_tin_cay":               "",
            })
            continue

        loai_loi     = (issue.get("loai_loi") or "").strip()
        speaker_de_x = (issue.get("speaker_de_xuat") or "").strip()
        char_id      = name_to_id.get(speaker_de_x) if speaker_de_x else None
        goi_y        = (issue.get("goi_y_sua") or "").strip() or e.translated
        bang_chung   = (issue.get("bang_chung") or issue.get("mo_ta") or "").strip()
        do_tin_cay   = (issue.get("do_tin_cay") or "").strip().lower()
        issue_text   = f"[{loai_loi}] {bang_chung}" if loai_loi else bang_chung

        fe_entries.append({
            "index":                    e.index,
            "original":                 e.original,
            "translated":               e.translated,
            "speaker":                  e.speaker,
            "fixed":                    goi_y,
            "issue":                    issue_text,
            "loai_loi":                 loai_loi,
            "speaker_hien_tai":         (issue.get("speaker_hien_tai") or e.speaker or ""),
            "speaker_de_xuat":          speaker_de_x,
            "speaker_de_xuat_char_id":  char_id,
            "bang_chung":               bang_chung,
            "do_tin_cay":               do_tin_cay,
        })

    # SSE: qc_done
    await _pub(pid, {
        "stage":          "qc_done",
        "chunk_index":    req.chunk_index,
        "message":        f"Xong! {len(van_de)} vấn đề phát hiện.",
        "tokens_in":      result.get("_tokens_in", 0),
        "tokens_out":     result.get("_tokens_out", 0),
        "timing_ms":      result.get("_timing_ms", 0),
        "dong_co_van_de": len(van_de),
    })

    # Snapshot kết quả QC vào DB để khi user chuyển chunk khác rồi quay lại
    # (hoặc F5) vẫn còn — không phải chạy lại Pass 4 tốn tiền.
    try:
        from datetime import datetime
        tc_qc = db.query(TranslateChunk).filter(
            TranslateChunk.project_id  == pid,
            TranslateChunk.chunk_index == req.chunk_index,
        ).first()
        # van_de lưu kèm các field đã resolve (char_id) để FE không phải resolve lại
        van_de_to_save = []
        for e in fe_entries:
            if e.get("loai_loi"):
                van_de_to_save.append({
                    "index":                    e["index"],
                    "loai_loi":                 e["loai_loi"],
                    "speaker_hien_tai":         e["speaker_hien_tai"],
                    "speaker_de_xuat":          e["speaker_de_xuat"],
                    "speaker_de_xuat_char_id":  e["speaker_de_xuat_char_id"],
                    "bang_chung":               e["bang_chung"],
                    "do_tin_cay":               e["do_tin_cay"],
                    "fixed":                    e["fixed"],
                    "original":                 e["original"],
                    "translated":               e["translated"],
                    "speaker":                  e["speaker"],
                    "issue":                    e["issue"],
                })
        if tc_qc:
            tc_qc.qc_response   = json.dumps(result, ensure_ascii=False)
            tc_qc.qc_van_de     = json.dumps(van_de_to_save, ensure_ascii=False)
            tc_qc.qc_tong_ket   = json.dumps(tong_ket, ensure_ascii=False)
            tc_qc.qc_tokens_in  = result.get("_tokens_in", 0)
            tc_qc.qc_tokens_out = result.get("_tokens_out", 0)
            tc_qc.qc_timing_ms  = result.get("_timing_ms", 0)
            tc_qc.qc_model      = req.model
            tc_qc.qc_run_at     = datetime.utcnow()
            db.commit()
    except Exception as save_err:
        logger.warning(f"[QC snapshot save] {save_err}")
        db.rollback()

    return {
        "entries":      fe_entries,
        "tong_ket":     tong_ket,
        "raw_response": json.dumps(result, ensure_ascii=False),
        "tokens_in":    result.get("_tokens_in", 0),
        "tokens_out":   result.get("_tokens_out", 0),
        "timing_ms":    result.get("_timing_ms", 0),
    }