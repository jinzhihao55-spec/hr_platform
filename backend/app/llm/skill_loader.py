"""从 SKILLS_DIR 加载 skill 提示词文件。

Skill（LLM 的系统提示词）单独维护，存放在 `docs/skills/` 目录，当前留空。
本加载器仅解析 `<skills_dir>/<name>.md`。文件缺失或为空时，调用方必须把对应 LLM
场景视为不可用并做确定性回退。
"""
from __future__ import annotations

from pathlib import Path

from app.config import settings


def load_skill(name: str) -> str | None:
    path = Path(settings.skills_dir) / f"{name}.md"
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None
