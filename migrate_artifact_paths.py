"""一次性迁移脚本：修复部署目录变更后 ReportArtifact.protected_path 过期问题。

问题：部署从 v1_7.20 迁移到 v1_7.21_new 后，数据库里的产物绝对路径
     仍指向旧目录，下载时 path.relative_to(output_root) 校验失败 (403)。

本脚本做两件事：
  1. 将旧目录下的 published/ 产物文件复制到当前 output_dir 下
  2. 将数据库中的 protected_path 更新为新路径

用法（在 Windows 服务器 backend 目录下执行）：
  cd C:\\Users\\Administrator\\Desktop\\v1_7.21_new\\backend
  C:\\Python314\\python.exe migrate_artifact_paths.py

安全说明：
  - 只处理包含 'published' 路径段的记录
  - 新路径必须在当前 output_dir 内
  - 如果文件在新位置已存在则跳过复制
  - dry-run 模式：python migrate_artifact_paths.py --dry-run
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

from sqlalchemy import select

from app.config import settings
from app.core.database import SessionLocal
from app.models.publication import ReportArtifact


def _rebase(old_path: Path, output_root: Path) -> Path | None:
    """将旧绝对路径重定位到当前 output_root 下。"""
    parts = old_path.parts
    for i, part in enumerate(parts):
        if part == "published":
            tail = Path(*parts[i:])
            rebased = (output_root / tail).resolve()
            try:
                rebased.relative_to(output_root)
            except ValueError:
                return None
            return rebased
    return None


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    output_root = Path(settings.output_dir).resolve()
    print(f"OUTPUT_ROOT = {output_root}")
    print(f"Mode        = {'DRY-RUN' if dry_run else 'EXECUTE'}")
    print()

    db = SessionLocal()
    try:
        artifacts = db.scalars(
            select(ReportArtifact).where(ReportArtifact.is_deleted == 0)
        ).all()

        migrated = 0
        skipped_ok = 0
        failed = 0

        for art in artifacts:
            old = Path(art.protected_path).resolve()
            # 已经在 output_root 内，无需处理
            try:
                old.relative_to(output_root)
                skipped_ok += 1
                continue
            except ValueError:
                pass

            rebased = _rebase(old, output_root)
            if rebased is None:
                print(f"  SKIP  {art.artifact_kind:20s}  无法重定位  {old}")
                failed += 1
                continue

            # 复制文件（如果新位置不存在但旧位置有文件）
            if not rebased.is_file() and old.is_file():
                if dry_run:
                    print(f"  COPY  {art.artifact_kind:20s}  {old}")
                    print(f"      -> {rebased}")
                else:
                    rebased.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(old), str(rebased))
                    print(f"  COPIED {art.artifact_kind:20s}  {old.name}")
            elif rebased.is_file():
                print(f"  EXISTS {art.artifact_kind:20s}  {rebased.name}")
            else:
                print(f"  MISS  {art.artifact_kind:20s}  旧文件不存在  {old}")
                failed += 1
                continue

            # 更新数据库
            if not dry_run:
                art.protected_path = str(rebased)
                db.commit()
            migrated += 1

        print()
        print(f"总计: 迁移 {migrated} 条, 已在正确位置 {skipped_ok} 条, 失败 {failed} 条")
        if dry_run:
            print("(dry-run 模式，未实际执行)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
