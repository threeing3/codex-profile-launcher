from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .skill_catalog import is_junction


CREATE_NO_WINDOW = 0x08000000


class SkillLinkError(RuntimeError):
    pass


def ensure_safe_skill_name(name: str) -> None:
    if not name or name in {".", "..", ".system"}:
        raise SkillLinkError(f"不允许共享技能名称：{name!r}")
    if Path(name).name != name or any(separator in name for separator in ("/", "\\")):
        raise SkillLinkError(f"技能名称不能包含路径分隔符：{name!r}")


def create_junction(target: Path, source: Path) -> None:
    ensure_safe_skill_name(target.name)
    if target.exists() or is_junction(target):
        raise SkillLinkError(f"目标已存在，无法建立目录联接：{target}")
    if not source.is_dir():
        raise SkillLinkError(f"共享技能源目录不存在：{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(target), str(source)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        check=False,
    )
    if result.returncode != 0 or not is_junction(target):
        raise SkillLinkError(
            f"无法建立目录联接：{target} -> {source}\n{result.stderr or result.stdout}"
        )


def remove_junction(path: Path) -> None:
    if not is_junction(path):
        raise SkillLinkError(f"拒绝移除非目录联接：{path}")
    os.rmdir(path)


def detach_junction(path: Path, staging: Path) -> None:
    if not is_junction(path):
        return
    source = path.resolve(strict=True)
    if staging.exists():
        raise SkillLinkError(f"暂存目录已存在：{staging}")
    shutil.copytree(source, staging)
    remove_junction(path)
    os.replace(staging, path)
