"""
Service đồng bộ Characters từ Bible (Simple pipeline → Editor cũ).

Functions:
  - sync_characters_from_bible(db, project_id): tạo/update đủ nhân vật từ Bible.c
  - build_alias_map(master_bible): map mọi alias + tên chính → tên chính (canonical)
  - resolve_speaker(speaker, alias_map): resolve speaker (có thể là alias) → tên chính

Khi LLM trả speaker là alias (vd 小寒) → resolve về tên chính (颜寒) để map đúng Character.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import Character
from dubeditor.simple.service_bible import get_master_bible_dict

logger = logging.getLogger(__name__)

# Palette màu cho nhân vật
_CHAR_COLORS = [
    '#378ADD', '#E0567A', '#46A758', '#E5A000', '#9B59B6',
    '#16A2A2', '#E67E22', '#D9534F', '#5BC0DE', '#7E57C2',
    '#EC407A', '#26A69A',
]

_GENDER_MAP = {'M': 'nam', 'F': 'nu', 'U': '?'}


def _get_aliases(data) -> list:
    """Lấy aliases từ entry (index 4 nếu format mới, 3 nếu cũ)."""
    if not isinstance(data, list):
        return []
    if len(data) >= 5 and isinstance(data[4], list):
        return data[4]
    if len(data) >= 4 and isinstance(data[3], list):
        return data[3]
    return []


def _get_side(data) -> str:
    """Lấy side (main/anta/neutral). index 3 nếu là string, ngược lại neutral."""
    if isinstance(data, list) and len(data) >= 4 and isinstance(data[3], str):
        s = data[3]
        if s in ('main', 'anta', 'neutral'):
            return s
    return 'neutral'

# role mapping: importance core/support → role Editor
# (Editor dùng nam_chinh/nu_chinh/phu... — ta map đơn giản)
def _infer_role(importance: str, gender: str, side: str = 'neutral') -> str:
    # Phản diện → role riêng
    if side == 'anta':
        return 'phan_dien'
    if importance == 'core':
        if gender == 'F':
            return 'nu_chinh'
        if gender == 'M':
            return 'nam_chinh'
        return 'chinh'
    return 'phu'


def build_alias_map(master_bible: Optional[dict]) -> dict[str, str]:
    """Build map: alias hoặc tên chính → tên chính (canonical name_zh).

    Vd Bible.c = {"颜寒": ["Nhan Hàn","M","support",["小寒","三哥"]]}
    → {"颜寒":"颜寒", "小寒":"颜寒", "三哥":"颜寒"}

    Nếu 1 alias trùng ở nhiều nhân vật → bỏ (ambiguous).
    """
    if not master_bible:
        return {}

    chars = master_bible.get('c', {})
    alias_to_canon: dict[str, str] = {}
    seen_alias_count: dict[str, int] = {}

    # Pass 1: tên chính luôn map về chính nó
    for name_zh in chars.keys():
        alias_to_canon[name_zh] = name_zh

    # Pass 2: aliases
    for name_zh, data in chars.items():
        aliases = _get_aliases(data)
        for al in aliases:
            al = str(al).strip()
            if not al:
                continue
            # Nếu alias trùng tên chính của nhân vật khác → ưu tiên tên chính, skip
            if al in chars:
                continue
            seen_alias_count[al] = seen_alias_count.get(al, 0) + 1
            alias_to_canon[al] = name_zh

    # Loại alias ambiguous (xuất hiện ở >1 nhân vật)
    for al, cnt in seen_alias_count.items():
        if cnt > 1:
            alias_to_canon.pop(al, None)

    return alias_to_canon


def resolve_speaker(speaker: str, alias_map: dict[str, str]) -> str:
    """Resolve speaker (có thể là alias) → tên chính. Nếu không match, giữ nguyên."""
    if not speaker:
        return speaker
    return alias_map.get(speaker, speaker)


def sync_characters_from_bible(db: Session, project_id: int) -> dict:
    """Tạo/update Characters từ Bible.c — ĐẦY ĐỦ tất cả nhân vật.

    Core trước (importance='core'), support sau.
    Map name_zh, aliases, gender, role, speech_style.

    Returns {created, updated, total}.
    """
    master = get_master_bible_dict(db, project_id)
    if not master:
        return {"created": 0, "updated": 0, "total": 0, "error": "Chưa có Bible"}

    chars = master.get('c', {})
    speech = master.get('speech', {})

    # Sort: core trước, support sau; giữ thứ tự xuất hiện trong Bible
    def sort_key(item):
        name_zh, data = item
        importance = data[2] if isinstance(data, list) and len(data) >= 3 else 'support'
        return 0 if importance == 'core' else 1

    sorted_chars = sorted(chars.items(), key=sort_key)

    created = 0
    updated = 0
    existing_count = db.query(Character).filter(
        Character.project_id == project_id
    ).count()
    color_idx = existing_count

    for name_zh, data in sorted_chars:
        if not isinstance(data, list) or len(data) < 3:
            continue
        name_vi = data[0] or name_zh
        gender_code = data[1] if len(data) >= 2 else 'U'
        importance = data[2] if len(data) >= 3 else 'support'
        aliases = _get_aliases(data)
        side = _get_side(data)

        gender = _GENDER_MAP.get(gender_code, '?')
        role = _infer_role(importance, gender_code, side)
        speech_style = speech.get(name_zh, '')

        # Tìm Character có sẵn theo name_zh
        char = db.query(Character).filter(
            Character.project_id == project_id,
            Character.name_zh == name_zh,
        ).first()

        if char:
            # Update các field (không ghi đè name nếu user đã đổi)
            char.aliases_zh = json.dumps(aliases, ensure_ascii=False)
            if not char.gender or char.gender == '?':
                char.gender = gender
            if not char.speaking_style:
                char.speaking_style = speech_style
            updated += 1
        else:
            char = Character(
                project_id=project_id,
                name=name_vi,
                name_zh=name_zh,
                color=_CHAR_COLORS[color_idx % len(_CHAR_COLORS)],
                gender=gender,
                role=role,
                aliases_zh=json.dumps(aliases, ensure_ascii=False),
                speaking_style=speech_style,
                description='Tự tạo từ pipeline dịch Simple',
            )
            db.add(char)
            color_idx += 1
            created += 1

    db.commit()

    return {
        "created": created,
        "updated": updated,
        "total": len(sorted_chars),
    }
