"""Path security helpers for artifact download endpoints.

When the deployment directory changes (e.g. v1_7.20 -> v1_7.21_new),
database records still hold absolute paths from the old location.
:func:`resolve_protected_path` rebases such stale paths onto the
current ``output_root`` so that downloads continue to work without
a manual database migration.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path

_log = logging.getLogger(__name__)


def resolve_protected_path(protected_path: str, output_root: Path) -> Path | None:
    """Resolve an artifact path, handling deployment directory relocations.

    1. If the path is already inside *output_root* and the file exists,
       return it directly.
    2. Otherwise, look for a ``published`` path segment and rebase the
       tail onto *output_root*.  If the file already exists at the new
       location, return it.
    3. If the file exists at the *old* location, copy it to the new
       location (self-heal) and return the new path.

    Returns ``None`` when the file cannot be reached by any strategy.
    """
    path = Path(protected_path).resolve()

    # Fast path: path is already within output_root
    try:
        path.relative_to(output_root)
        return path if path.is_file() else None
    except ValueError:
        pass

    # Relocation: rebase from the 'published' subdirectory onward
    parts = path.parts
    for i, part in enumerate(parts):
        if part != "published":
            continue
        tail = Path(*parts[i:])
        rebased = (output_root / tail).resolve()
        try:
            rebased.relative_to(output_root)
        except ValueError:
            continue
        # File already exists at the new location
        if rebased.is_file():
            return rebased
        # File exists at old location -- copy it to the new location
        if path.is_file():
            try:
                rebased.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(path), str(rebased))
                _log.info("relocated artifact %s -> %s", path, rebased)
                if rebased.is_file():
                    return rebased
            except OSError as exc:
                _log.warning("failed to relocate artifact %s: %s", path, exc)
        break
    return None
