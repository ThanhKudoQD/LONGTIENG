"""
Per-project config service.

Lưu config trong `AppSetting` table với key pattern `simple_config:{project_id}`.
AppSetting model đã có sẵn trong dubeditor/models.py.
"""
from __future__ import annotations
import json
import logging
from typing import Optional

from sqlalchemy.orm import Session

from dubeditor.models import AppSetting
from dubeditor.simple.schemas import (
    SimpleConfigSchema, ProviderApiKeys, TaskModelConfig,
)

logger = logging.getLogger(__name__)


def _key(project_id: int) -> str:
    return f"simple_config:{project_id}"


def default_config() -> SimpleConfigSchema:
    """Default config — match với defaultSimpleConfig() ở FE."""
    return SimpleConfigSchema(
        api_keys=ProviderApiKeys(),
        tasks={
            'bible':     TaskModelConfig(provider='gemini', model='gemini-2.5-pro',   thinking=True),
            'translate': TaskModelConfig(provider='gemini', model='gemini-2.5-pro',   thinking=True),
            'qa':        TaskModelConfig(provider='gemini', model='gemini-2.5-flash', thinking=False),
        },
    )


def load_config(db: Session, project_id: int) -> SimpleConfigSchema:
    """Load config từ AppSetting. Trả default nếu chưa có."""
    setting = (
        db.query(AppSetting)
        .filter(AppSetting.key == _key(project_id))
        .first()
    )
    if not setting or not setting.value:
        return default_config()

    try:
        data = json.loads(setting.value)
        # Bỏ task 'repair' khỏi config cũ (đã không dùng nữa, schema mới không chấp nhận)
        if isinstance(data.get('tasks'), dict):
            data['tasks'].pop('repair', None)
        # Merge với default để tránh missing keys
        defaults = default_config().model_dump()
        # Shallow merge — keep nested defaults if missing
        for k, v in defaults.items():
            data.setdefault(k, v)
        return SimpleConfigSchema(**data)
    except Exception as e:
        logger.warning(f"Cannot parse config for project {project_id}: {e}")
        return default_config()


def save_config(
    db: Session,
    project_id: int,
    config: SimpleConfigSchema,
) -> None:
    """Save config vào AppSetting."""
    setting = (
        db.query(AppSetting)
        .filter(AppSetting.key == _key(project_id))
        .first()
    )

    data = config.model_dump()
    value = json.dumps(data, ensure_ascii=False)

    if setting:
        setting.value = value
    else:
        setting = AppSetting(key=_key(project_id), value=value)
        db.add(setting)

    db.commit()


# ─── API key resolver ────────────────────────────────────────────────────────
# Khi FE chưa nhập key qua /config, có thể fallback sang global setting cũ
# (settings router của project). Tạm thời chỉ dùng key per-project.

def get_api_key_for_provider(
    config: SimpleConfigSchema,
    provider: str,
) -> str:
    """Lấy API key cho provider. Raise ValueError nếu rỗng."""
    if provider not in ('gemini', 'openai', 'deepseek'):
        raise ValueError(f"Unknown provider: {provider}")
    key = getattr(config.api_keys, provider, '')
    if not key:
        raise ValueError(
            f"API key for '{provider}' is not set. "
            f"Vui lòng cấu hình API key ở tab Cấu hình."
        )
    return key
