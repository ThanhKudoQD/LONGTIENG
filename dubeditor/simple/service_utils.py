"""
Utility functions chung cho Simple pipeline.

Chứa:
  - load_prompt_template     : đọc template từ file
  - format_srt_for_prompt    : convert Subtitle → format text cho prompt
  - parse_bible_json         : parse + validate Bible JSON response
  - parse_translation_array  : parse [[id, speaker, vi], ...] response
  - strip_markdown_wrapper   : xóa ```json wrapper nếu LLM trả về
  - count_tokens_estimate    : ước tính tokens (rough)
  - extract_active_bible     : build subset Bible chỉ chứa nhân vật xuất hiện
"""
from __future__ import annotations
import json
import re
from pathlib import Path
from typing import Optional, Iterable
import logging

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────────

# Special speaker codes — không cần trong Bible.c
SPECIAL_SPEAKERS = {'UNKNOWN', 'CROWD', 'NARRATOR', 'OFF_SCREEN', 'PHONE'}

# Regex detect chữ Trung (CJK Unified Ideographs)
CHINESE_CHAR_RE = re.compile(r'[\u4e00-\u9fff]')

# Path tới folder prompts
_PROMPTS_DIR = Path(__file__).parent / "prompts"


# ─── Template loader ─────────────────────────────────────────────────────────

def load_prompt_template(name: str) -> str:
    """Đọc prompt template. `name` không gồm .txt extension."""
    path = _PROMPTS_DIR / f"{name}.txt"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding='utf-8')


def fill_placeholder(template: str, key: str, value: str) -> str:
    """Thay placeholder trong template. Chấp nhận cả 2 format:
      - {KEY}   (single brace — convention pipeline mới)
      - {{KEY}} (double brace — convention file gốc user upload)

    Để tránh edge case user upload prompt với double brace nhưng code chỉ
    thay single brace → placeholder không được thay → LLM nhận prompt với
    raw `{KEY}` literal.

    Quan trọng: thay {{KEY}} TRƯỚC, vì sau khi thay {KEY} thì {{KEY}} sẽ
    không còn match (vì { trong {{ đã được consume).
    """
    if value is None:
        value = ''
    # Replace double brace first
    template = template.replace('{{' + key + '}}', value)
    # Then single brace
    template = template.replace('{' + key + '}', value)
    return template


def fill_placeholders(template: str, mapping: dict[str, str]) -> str:
    """Apply fill_placeholder cho nhiều key một lúc."""
    for key, value in mapping.items():
        template = fill_placeholder(template, key, value)
    return template


# ─── SRT formatter ───────────────────────────────────────────────────────────

def format_srt_for_bible_prompt(subtitles: list) -> str:
    """Format subtitles cho Bible prompt — compact, KHÔNG có timestamp.

    Bible task không cần biết timing — chỉ cần text để trích nhân vật, alias,
    quan hệ, thuật ngữ. Bỏ timestamp tiết kiệm ~30-40% tokens.

    Format: `id | zh` (giống translate prompt, đồng nhất pipeline).

    Args:
        subtitles: list các Subtitle ORM với fields: index, original_text
    """
    lines = []
    for s in subtitles:
        zh = (s.original_text or '').strip().replace('\n', ' ')
        if not zh:
            continue
        lines.append(f"{s.index} | {zh}")
    return '\n'.join(lines)


def format_lines_for_translate_prompt(subtitles: list) -> str:
    """Format dạng `id | zh` cho translate batch prompt.

    Compact hơn SRT full vì translate đã có timing trong DB.
    """
    lines = []
    for s in subtitles:
        zh = (s.original_text or '').strip().replace('\n', ' ')
        if not zh:
            continue
        lines.append(f"{s.index} | {zh}")
    return '\n'.join(lines)


def format_context_previous(subtitles: list) -> str:
    """Format previous context: `[[id, speaker, text], ...]`

    text = bản dịch vi nếu đã có, fallback sang zh (kèm chú thích) nếu chưa dịch.
    speaker = simple_speaker_zh nếu có, ngược lại "" (rỗng, không phải UNKNOWN).
    """
    out = []
    for s in subtitles:
        speaker = s.simple_speaker_zh or ''
        vi = (s.simple_text_vi or '').strip()
        if vi:
            text = vi.replace('"', '\\"')
        else:
            # Chưa dịch → dùng zh để LLM ít nhất hiểu nội dung
            zh = (s.original_text or '').strip().replace('"', '\\"')
            text = zh
        speaker_q = speaker.replace('"', '\\"')
        out.append(f'[{s.index}, "{speaker_q}", "{text}"]')
    if not out:
        return '[]'
    return '[\n  ' + ',\n  '.join(out) + '\n]'


def format_context_after(subtitles: list) -> str:
    """Format after context (dòng tương lai chưa dịch): `[[id, zh], ...]`

    Chỉ zh vì các dòng này chưa dịch — giúp LLM hiểu hội thoại dẫn tới đâu.
    """
    out = []
    for s in subtitles:
        zh = (s.original_text or '').strip().replace('"', '\\"')
        out.append(f'[{s.index}, "{zh}"]')
    if not out:
        return '[]'
    return '[\n  ' + ',\n  '.join(out) + '\n]'


# ─── Response parser ─────────────────────────────────────────────────────────

_MARKDOWN_JSON_RE = re.compile(
    r'^\s*```(?:json)?\s*\n?(.*?)\n?\s*```\s*$',
    re.DOTALL | re.IGNORECASE,
)


def strip_markdown_wrapper(text: str) -> str:
    """Xóa ```json ... ``` wrapper nếu có."""
    if not text:
        return text
    m = _MARKDOWN_JSON_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return text.strip()


def parse_bible_json(response: str) -> dict:
    """Parse Bible response. Raise ValueError nếu invalid.

    Validate:
      - Là dict
      - Có key "c" (characters)
      - Mỗi entry c[name] là list 4 phần tử [hanviet, gender, role, aliases]

    Returns:
        Bible dict đã validate.
    """
    if not response or not response.strip():
        raise ValueError("Empty Bible response")

    cleaned = strip_markdown_wrapper(response)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Fallback: tìm JSON object đầu tiên trong text
        m = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON: {e}")
        else:
            raise ValueError(f"No JSON object found: {e}")

    if not isinstance(data, dict):
        raise ValueError(f"Bible response is not an object (got {type(data).__name__})")

    # Đảm bảo có "c" (characters dict)
    if 'c' not in data or not isinstance(data['c'], dict):
        # Auto-fix: tạo c rỗng nếu missing để không crash pipeline
        logger.warning("Bible missing 'c' key, defaulting to {}")
        data['c'] = {}

    # Validate format c[name] = [hanviet, gender, role, aliases]
    cleaned_c = {}
    for name, entry in data.get('c', {}).items():
        if not isinstance(entry, list) or len(entry) < 4:
            logger.warning(f"Bible.c[{name}] has invalid format: {entry}")
            continue
        # Coerce aliases về list
        aliases = entry[3] if isinstance(entry[3], list) else []
        cleaned_c[name] = [
            str(entry[0]),                    # hanviet
            str(entry[1]) if entry[1] in ('F', 'M', 'U') else 'U',  # gender
            str(entry[2]) if entry[2] in ('core', 'support') else 'support',  # role
            [str(a) for a in aliases],        # aliases
        ]
    data['c'] = cleaned_c

    # Đảm bảo các key optional tồn tại
    for k in ['speech', 'self', 'r', 'dynamics', 't']:
        if k not in data or not isinstance(data[k], dict):
            data[k] = {}
    if 'rules' not in data or not isinstance(data['rules'], list):
        data['rules'] = []
    if 'unknowns' not in data or not isinstance(data['unknowns'], list):
        data['unknowns'] = []
    for k in ['genre', 'setting', 'period', 'sum']:
        if k not in data:
            data[k] = ''
        elif not isinstance(data[k], str):
            data[k] = str(data[k])

    return data


def parse_translation_array(response: str) -> list[tuple[int, str, str]]:
    """Parse `[[id, speaker, vi], ...]` response. Trả list of tuples.

    Raise ValueError nếu invalid. Mỗi entry phải là [int, str, str].
    """
    if not response or not response.strip():
        raise ValueError("Empty translation response")

    cleaned = strip_markdown_wrapper(response)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # Fallback: tìm array đầu tiên
        m = re.search(r'\[.*\]', cleaned, re.DOTALL)
        if m:
            try:
                data = json.loads(m.group(0))
            except json.JSONDecodeError:
                raise ValueError(f"Invalid JSON array: {e}")
        else:
            raise ValueError(f"No JSON array found: {e}")

    if not isinstance(data, list):
        # gpt-5-nano / 1 số model trả dict thay vì array thuần.
        # Thử tìm array bên trong: {"translations":[...]}, {"lines":[...]}, {"result":[...]}
        if isinstance(data, dict):
            logger.warning(
                f"Response là dict (keys={list(data.keys())}), thử tìm array bên trong"
            )
            found = None
            # Ưu tiên các key thường gặp
            for key in ('translations', 'lines', 'result', 'data', 'items', 'subtitles', 'output'):
                if key in data and isinstance(data[key], list):
                    found = data[key]
                    logger.info(f"Tìm thấy array ở key '{key}'")
                    break
            # Fallback: lấy value list đầu tiên
            if found is None:
                for k, v in data.items():
                    if isinstance(v, list) and v:
                        found = v
                        logger.info(f"Dùng array ở key '{k}' (fallback)")
                        break
            if found is not None:
                data = found
            else:
                raise ValueError(
                    f"Response là dict không chứa array. Keys: {list(data.keys())}"
                )
        else:
            raise ValueError(f"Response is not an array (got {type(data).__name__})")

    out: list[tuple[int, str, str]] = []
    for i, entry in enumerate(data):
        # Hỗ trợ cả entry dạng list [id, speaker, vi] VÀ dict {"id":.., "speaker":.., "vi":..}
        if isinstance(entry, dict):
            sid = entry.get('id', entry.get('index'))
            speaker = entry.get('speaker', entry.get('spk', ''))
            vi = entry.get('vi', entry.get('text', entry.get('vietnamese', '')))
            if sid is None:
                logger.warning(f"Entry [{i}] dict thiếu id: {entry}")
                continue
            try:
                sub_id = int(sid)
            except (TypeError, ValueError):
                logger.warning(f"Entry [{i}] id không phải số: {sid}")
                continue
            out.append((sub_id, str(speaker).strip(), str(vi).strip()))
            continue

        if not isinstance(entry, list) or len(entry) < 3:
            logger.warning(f"Entry [{i}] invalid format: {entry}")
            continue
        try:
            sub_id = int(entry[0])
        except (TypeError, ValueError):
            logger.warning(f"Entry [{i}] has non-int id: {entry[0]}")
            continue
        speaker = str(entry[1]).strip()
        vi = str(entry[2]).strip()
        out.append((sub_id, speaker, vi))

    if not out:
        raise ValueError("No valid entries in translation response")

    return out


# ─── Active Bible extraction ─────────────────────────────────────────────────

def extract_active_bible(master_bible: dict, zh_texts: Iterable[str]) -> dict:
    """Build ACTIVE_BIBLE subset chỉ chứa nhân vật xuất hiện trong batch.

    Cách detect: với mỗi character name (tên Trung) trong master_bible.c,
    check xem text ZH của batch có chứa tên đó hoặc 1 alias không (substring match).

    Args:
        master_bible: Bible JSON master
        zh_texts: iterable của text tiếng Trung (các dòng trong batch)

    Returns:
        Active bible dict — same schema, nhỏ hơn nhiều.
    """
    if not master_bible:
        return {}

    all_zh = ' '.join(zh_texts)

    active_chars: dict[str, list] = {}
    char_dict = master_bible.get('c', {})

    for name, entry in char_dict.items():
        # entry = [hanviet, gender, role, aliases]
        names_to_check = [name] + (entry[3] if len(entry) > 3 else [])
        for n in names_to_check:
            if n and n in all_zh:
                active_chars[name] = entry
                break

    # Build active bible subset
    active = {
        'c': active_chars,
        'speech': {k: v for k, v in master_bible.get('speech', {}).items() if k in active_chars},
        'self': {k: v for k, v in master_bible.get('self', {}).items() if k in active_chars},
        'r': {},
        'dynamics': {},
        't': master_bible.get('t', {}),   # giữ nguyên thuật ngữ (ít token)
        'rules': master_bible.get('rules', []),  # rules toàn cục
        'sum': master_bible.get('sum', ''),
    }

    # Filter r: chỉ giữ cặp mà cả 2 nhân vật đều active
    # Format key trong Bible.r: "A>B" (theo prompt gốc)
    for key, v in master_bible.get('r', {}).items():
        if '>' in key:
            a, b = key.split('>', 1)
            a, b = a.strip(), b.strip()
            if a in active_chars and b in active_chars:
                active['r'][key] = v

    for key, v in master_bible.get('dynamics', {}).items():
        # key format: "A-B"
        if '-' in key:
            parts = key.split('-')
            if len(parts) == 2 and parts[0] in active_chars and parts[1] in active_chars:
                active['dynamics'][key] = v

    return active


# ─── Token counter (rough estimate) ──────────────────────────────────────────

def estimate_tokens(text: str) -> int:
    """Ước tính tokens (rough — không chính xác như tiktoken).

    Rule of thumb:
      - 1 token ≈ 4 ký tự cho text Latin
      - 1 token ≈ 1.5 ký tự cho tiếng Trung
    """
    if not text:
        return 0
    n_chinese = len(CHINESE_CHAR_RE.findall(text))
    n_other = len(text) - n_chinese
    return int(n_chinese / 1.5 + n_other / 4)


# ─── Helpers cho speaker validation ──────────────────────────────────────────

def is_valid_speaker(speaker: str, master_bible: dict) -> bool:
    """True nếu speaker hợp lệ:
      - Là special speaker (UNKNOWN, CROWD, ...)
      - Hoặc có trong master_bible.c
    """
    if not speaker:
        return False
    if speaker in SPECIAL_SPEAKERS:
        return True
    if master_bible and speaker in master_bible.get('c', {}):
        return True
    return False


def has_chinese_chars(text: str) -> bool:
    """True nếu text còn ký tự Trung Quốc."""
    if not text:
        return False
    return bool(CHINESE_CHAR_RE.search(text))


def calculate_cps(text: str, duration_seconds: float, fallback_chars: int = 50) -> float:
    """Tính characters-per-second.

    Trả về số float. Nếu duration <= 0, fallback dùng len(text) / fallback_chars.
    """
    if not text:
        return 0.0
    if duration_seconds and duration_seconds > 0:
        return len(text) / duration_seconds
    # Fallback: scale theo độ dài so với threshold
    return float(len(text)) / fallback_chars if fallback_chars > 0 else 0.0


# ─── Auto-fix helpers cho Filter step ────────────────────────────────────────

# Mapping dấu câu Trung → Việt
PUNCT_ZH_TO_VN = {
    '，': ',', '。': '.', '？': '?', '！': '!',
    '；': ';', '：': ':', '"': '"', '"': '"',
    ''': "'", ''': "'", '、': ',', '…': '...',
    '（': '(', '）': ')', '《': '"', '》': '"',
}


def auto_fix_text(vi: str) -> tuple[str, list[str]]:
    """Auto-fix các lỗi format dễ. Trả (fixed_text, applied_fixes).

    Fixes:
      - Strip whitespace
      - Replace dấu câu Trung → Việt
      - Bỏ markdown wrapper nếu là cả dòng
    """
    if not vi:
        return vi, []

    fixes = []
    out = vi.strip()
    if out != vi:
        fixes.append('whitespace')

    # Punct map
    new = out
    for zh_p, vn_p in PUNCT_ZH_TO_VN.items():
        if zh_p in new:
            new = new.replace(zh_p, vn_p)
    if new != out:
        fixes.append('punctuation')
        out = new

    return out, fixes
