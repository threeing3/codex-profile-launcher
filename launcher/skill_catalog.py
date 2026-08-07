from __future__ import annotations

import hashlib
import os
import re
from collections import defaultdict
from pathlib import Path

from .models import Profile
from .skill_models import (
    MigrationPreview,
    SHARED_LIBRARY_PROFILE_ID,
    SkillLocation,
    SkillPlan,
    SkillState,
)


REPARSE_POINT_ATTRIBUTE = 0x400
SENSITIVE_FILE_NAMES = {
    ".env",
    ".env.local",
    "credentials.json",
    "secrets.json",
    "id_rsa",
    "id_ed25519",
}
SENSITIVE_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}
SENSITIVE_TEXT = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|client[_-]?secret|private[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_\-/.+=]{12,}"
)


def is_junction(path: Path) -> bool:
    try:
        return bool(path.lstat().st_file_attributes & REPARSE_POINT_ATTRIBUTE)
    except (AttributeError, FileNotFoundError, OSError):
        return path.is_symlink()


def hash_directory(path: Path) -> str:
    digest = hashlib.sha256()
    for file_path in sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix().casefold(),
    ):
        relative = file_path.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with file_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def find_sensitive_content(path: Path) -> tuple[str, ...]:
    findings: list[str] = []
    for file_path in sorted(item for item in path.rglob("*") if item.is_file()):
        relative = file_path.relative_to(path).as_posix()
        lowered = file_path.name.casefold()
        if lowered in SENSITIVE_FILE_NAMES or file_path.suffix.casefold() in SENSITIVE_SUFFIXES:
            findings.append(f"敏感文件名：{relative}")
            continue
        if file_path.stat().st_size > 1024 * 1024:
            continue
        try:
            content = file_path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if SENSITIVE_TEXT.search(content):
            findings.append(f"疑似凭据内容：{relative}")
    return tuple(findings)


class SkillCatalog:
    def __init__(self, shared_skills: Path) -> None:
        self.shared_skills = shared_skills

    def build_preview(self, profiles: list[Profile]) -> MigrationPreview:
        grouped: dict[str, list[SkillLocation]] = defaultdict(list)
        for profile in profiles:
            for location in self.scan_directory(profile.id, profile.name, profile.codex_home / "skills"):
                grouped[location.name.casefold()].append(location)
        for location in self.scan_directory(
            SHARED_LIBRARY_PROFILE_ID,
            "中央共享库",
            self.shared_skills,
        ):
            grouped[location.name.casefold()].append(location)

        plans = [self._make_plan(locations) for locations in grouped.values()]
        plans.sort(key=lambda plan: plan.name.casefold())
        return MigrationPreview(plans, tuple(profile.id for profile in profiles))

    @staticmethod
    def scan_directory(profile_id: str, profile_name: str, skills_dir: Path) -> list[SkillLocation]:
        if not skills_dir.exists():
            return []
        locations: list[SkillLocation] = []
        for path in sorted(skills_dir.iterdir(), key=lambda item: item.name.casefold()):
            if path.name == ".system" or not (path.is_dir() or is_junction(path)):
                continue
            valid = (path / "SKILL.md").is_file()
            try:
                digest = hash_directory(path) if valid else ""
                modified_at = max(
                    (item.stat().st_mtime for item in path.rglob("*") if item.is_file()),
                    default=path.stat().st_mtime,
                )
                findings = find_sensitive_content(path) if valid else ()
            except OSError:
                digest, modified_at, findings, valid = "", 0.0, (), False
            locations.append(
                SkillLocation(
                    profile_id=profile_id,
                    profile_name=profile_name,
                    name=path.name,
                    path=path,
                    digest=digest,
                    modified_at=modified_at,
                    is_junction=is_junction(path),
                    valid=valid,
                    sensitive_findings=findings,
                )
            )
        return locations

    @staticmethod
    def _make_plan(locations: list[SkillLocation]) -> SkillPlan:
        name = locations[0].name
        valid = [location for location in locations if location.valid]
        if not valid:
            return SkillPlan(name, SkillState.INVALID, locations)
        if any(not location.valid for location in locations):
            return SkillPlan(name, SkillState.INVALID, locations)
        digests = {location.digest for location in valid}
        shared = next(
            (item for item in valid if item.profile_id == SHARED_LIBRARY_PROFILE_ID),
            None,
        )
        if len(digests) > 1:
            recommended = max(valid, key=lambda item: item.modified_at).profile_id
            return SkillPlan(name, SkillState.CONFLICT, valid, recommended)
        if shared and all(
            item.profile_id == SHARED_LIBRARY_PROFILE_ID or item.is_junction
            for item in valid
        ):
            return SkillPlan(name, SkillState.SHARED, valid, shared.profile_id)
        if len(valid) > 1:
            recommended = shared.profile_id if shared else valid[0].profile_id
            return SkillPlan(name, SkillState.IDENTICAL, valid, recommended)
        return SkillPlan(name, SkillState.UNIQUE, valid, valid[0].profile_id)
