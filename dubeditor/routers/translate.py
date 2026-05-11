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
                req.concurrency, req.enable_qc)
    return {"ok": True}


async def _run_pass3_bg(pid: int, api_key: str, model: str,
                         concurrency: int, enable_qc: bool):
    db = SessionLocal()
    try:
        t     = _load_translator()
        p     = db.query(Project).filter(Project.id == pid).first()
        bible = json.loads(p.bible_json)

        subs      = db.query(Subtitle).filter(
            Subtitle.project_id == pid
        ).order_by(Subtitle.index).all()
        srt_blocks = _subs_to_blocks(subs)

        chunks = t.build_chunks_from_bible(srt_blocks, bible)
        total  = len(chunks)
        done   = 0

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
                    # Lưu prompt/response vào translate_chunks
                    try:
                        tc = db.query(TranslateChunk).filter(
                            TranslateChunk.project_id  == pid,
                            TranslateChunk.chunk_index == chunk_idx,
                        ).first()
                        if tc:
                            tc.prompt     = call_info.get("prompt", "")
                            tc.response   = call_info.get("response", "")
                            tc.tokens_in  = call_info.get("tokens_in", 0)
                            tc.tokens_out = call_info.get("tokens_out", 0)
                            tc.timing_ms  = call_info.get("timing_ms", 0)
                            tc.model      = model
                        else:
                            blocks = chunk.get("blocks") or []
                            s_line = blocks[0]["index"]  if blocks else 0
                            e_line = blocks[-1]["index"] if blocks else 0
                            db.add(TranslateChunk(
                                project_id  = pid,
                                chunk_index = chunk_idx,
                                start_line  = s_line,
                                end_line    = e_line,
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

        await asyncio.gather(*[do_chunk(chunk, i) for i, chunk in enumerate(chunks)])

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
                    if '"done"' in msg or '"error"' in msg:
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
    """Load prompt/response đã lưu cho tất cả chunks của project."""
    chunks = db.query(TranslateChunk).filter(
        TranslateChunk.project_id == pid
    ).order_by(TranslateChunk.chunk_index).all()
    return [{
        "chunk_index": c.chunk_index,
        "start_line":  c.start_line,
        "end_line":    c.end_line,
        "prompt":      c.prompt or "",
        "response":    c.response or "",
        "tokens_in":   c.tokens_in,
        "tokens_out":  c.tokens_out,
        "timing_ms":   c.timing_ms,
        "model":       c.model or "",
    } for c in chunks]




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
    index: int
    original: str
    translated: str

class ReviewChunkRequest(BaseModel):
    api_key:     str
    model:       str = "gemini-2.5-flash"
    chunk_index: int
    entries:     list[ReviewEntry]

@router.post("/projects/{pid}/translate/review-chunk")
async def review_chunk(pid: int, req: ReviewChunkRequest, db: Session = Depends(get_db)):
    """QC Review 1 chunk — dùng pass4_review_chunk từ translator."""
    p = db.query(Project).filter(Project.id == pid).first()
    if not p or not p.bible_json:
        raise HTTPException(400, "Project chưa có Bible")

    try:
        t = _load_translator()
    except RuntimeError as e:
        raise HTTPException(503, str(e))

    bible = json.loads(p.bible_json)

    # Build chunk object đơn giản để truyền vào pass4
    chunk = {
        "index":      req.chunk_index,
        "blocks":     [],
        "scene_info": None,
        "tom_tat":    "",
    }
    # entries format cho pass4: [{index, original_text, translated_text}]
    entries_for_p4 = [
        {"index": e.index, "original_text": e.original, "translated_text": e.translated}
        for e in req.entries
    ]

    result = await t.pass4_review_chunk(
        chunk=chunk,
        bible=bible,
        entries=entries_for_p4,
        api_key=req.api_key,
        model=req.model,
    )
    if not result:
        raise HTTPException(500, "Pass 4 không trả về kết quả")

    # Chuyển format pass4 → FE format
    # pass4 trả: {tong_ket, van_de: [{dong, goc, dich_hien_tai, loai_loi, mo_ta, goi_y_sua}]}
    van_de = result.get("van_de") or []
    tong_ket = result.get("tong_ket") or {}

    fe_entries = []
    issue_map = {v["dong"]: v for v in van_de}
    for e in req.entries:
        issue = issue_map.get(e.index)
        fe_entries.append({
            "index":      e.index,
            "original":   e.original,
            "translated": e.translated,
            "fixed":      issue["goi_y_sua"] if issue else e.translated,
            "issue":      f"[{issue.get('loai_loi','')}] {issue.get('mo_ta','')}" if issue else "",
        })

    return {
        "entries":      fe_entries,
        "tong_ket":     tong_ket,
        "raw_response": json.dumps(result, ensure_ascii=False),
        "tokens_in":    result.get("_tokens_in", 0),
        "tokens_out":   result.get("_tokens_out", 0),
        "timing_ms":    result.get("_timing_ms", 0),
    }