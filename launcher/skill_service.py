from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
import ctypes
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from collections.abc import Callable, Iterator
from typing import Any, TypeVar

from .models import Profile
from .paths import AppPaths
from .skill_catalog import SkillCatalog, hash_directory, is_junction
from .skill_links import create_junction, detach_junction, remove_junction
from .skill_models import (
    MigrationPreview,
    SHARED_LIBRARY_PROFILE_ID,
    SkillLocation,
    SkillSnapshot,
    SkillState,
)
from .skill_repository import SkillRepository


class SkillSharingError(RuntimeError):
    pass


class SkillConflictError(SkillSharingError):
    pass


class SensitiveSkillError(SkillSharingError):
    pass


class RunningProfilesError(SkillSharingError):
    def __init__(self, profile_names: list[str]) -> None:
        self.profile_names = profile_names
        super().__init__("请先关闭以下 Codex 窗口：" + "、".join(profile_names))


Result = TypeVar("Result")


def guarded_mutation(method: Callable[..., Result]) -> Callable[..., Result]:
    @wraps(method)
    def wrapper(self: "SkillService", *args: Any, **kwargs: Any) -> Result:
        with self._mutation_guard():
            return method(self, *args, **kwargs)

    return wrapper


class SkillService:
    def __init__(
        self,
        paths: AppPaths,
        repository: SkillRepository,
        launcher: object,
    ) -> None:
        self.paths = paths
        self.repository = repository
        self.launcher = launcher
        self.catalog = SkillCatalog(paths.shared_skills)
        self._operation_lock = threading.RLock()

    def initialize(self) -> None:
        self.repository.initialize()

    @guarded_mutation
    def preview(self, profiles: list[Profile]) -> MigrationPreview:
        self._restore_unexpected_deletions()
        self._snapshot_external_changes()
        return self.catalog.build_preview(profiles)

    @guarded_mutation
    def apply_initial_migration(
        self,
        preview: MigrationPreview,
        profiles: list[Profile],
        selections: dict[str, str],
        *,
        allow_sensitive: bool = False,
    ) -> str:
        with self._operation_lock:
            self._ensure_profiles_stopped(profiles)
            chosen = self._resolve_sources(preview, selections)
            findings = {
                name: source.sensitive_findings
                for name, source in chosen.items()
                if source.sensitive_findings
            }
            if findings and not allow_sensitive:
                details = "\n".join(
                    f"{name}: " + "；".join(items) for name, items in findings.items()
                )
                raise SensitiveSkillError(
                    "发现疑似敏感内容，已阻止共享。确认风险后可强制继续：\n" + details
                )

            operation_id = self._operation_id("migration")
            operation_backup = self.paths.skill_backups / operation_id
            operation_staging = self.paths.skill_staging / operation_id
            operation_backup.mkdir(parents=True, exist_ok=False)
            operation_staging.mkdir(parents=True, exist_ok=False)
            self._write_operation_log(
                operation_id,
                "开始首次共享技能迁移",
                {
                    "profiles": [profile.id for profile in profiles],
                    "skills": sorted(chosen),
                },
            )

            moved_profiles: list[tuple[Path, Path]] = []
            moved_shared: list[tuple[Path, Path]] = []
            created_links: list[Path] = []
            installed_shared: list[tuple[Path, Path]] = []
            binding_records: list[tuple[str, str, str, Path, Path | None]] = []
            try:
                staged_sources = self._stage_sources(chosen, operation_staging)
                for name, staged in staged_sources.items():
                    shared_target = self.paths.shared_skills / name
                    if shared_target.exists() or is_junction(shared_target):
                        previous = operation_backup / "shared-library" / name
                        previous.parent.mkdir(parents=True, exist_ok=True)
                        os.replace(shared_target, previous)
                        moved_shared.append((previous, shared_target))
                    os.replace(staged, shared_target)
                    installed_shared.append((shared_target, operation_staging / "installed" / name))

                for profile in profiles:
                    skills_dir = profile.codex_home / "skills"
                    skills_dir.mkdir(parents=True, exist_ok=True)
                    for name, source in chosen.items():
                        target = skills_dir / name
                        shared_target = self.paths.shared_skills / name
                        original_backup: Path | None = None
                        if is_junction(target):
                            remove_junction(target)
                        elif target.exists():
                            original_backup = operation_backup / profile.id / name
                            original_backup.parent.mkdir(parents=True, exist_ok=True)
                            os.replace(target, original_backup)
                            moved_profiles.append((original_backup, target))
                        create_junction(target, shared_target)
                        created_links.append(target)
                        binding_records.append(
                            (profile.id, name, "shared", target, original_backup)
                        )

                shared_records: list[tuple[str, str, str]] = []
                snapshots: list[SkillSnapshot] = []
                for name, source in chosen.items():
                    digest = hash_directory(self.paths.shared_skills / name)
                    shared_records.append((name, digest, source.profile_id))
                    snapshots.append(self._create_snapshot(name, "首次迁移", record=False))
                self.repository.commit_migration(
                    [profile.id for profile in profiles],
                    shared_records,
                    binding_records,
                    snapshots,
                )
                self._write_operation_log(operation_id, "首次迁移完成", {"result": "success"})
                return operation_id
            except Exception as error:
                self._rollback_filesystem(
                    operation_id,
                    created_links,
                    moved_profiles,
                    installed_shared,
                    moved_shared,
                )
                self._write_operation_log(
                    operation_id,
                    "首次迁移失败并执行回滚",
                    {"error": f"{type(error).__name__}: {error}"},
                )
                raise

    @guarded_mutation
    def enroll_profile(self, profile: Profile) -> None:
        self.repository.set_policy(profile.id, True)
        if not self.paths.shared_skills.exists():
            return
        skills_dir = profile.codex_home / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        for shared in sorted(self.paths.shared_skills.iterdir(), key=lambda item: item.name.casefold()):
            if not shared.is_dir() or shared.name == ".system":
                continue
            target = skills_dir / shared.name
            if target.exists() or is_junction(target):
                continue
            create_junction(target, shared)
            self.repository.record_binding(profile.id, shared.name, "shared", target, None)

    @guarded_mutation
    def detach_profile(self, profile: Profile) -> None:
        self._ensure_profiles_stopped([profile])
        operation_id = self._operation_id("detach")
        operation_staging = self.paths.skill_staging / operation_id / profile.id
        operation_staging.mkdir(parents=True, exist_ok=False)
        skills_dir = profile.codex_home / "skills"
        junctions: list[tuple[Path, Path, Path]] = []
        if skills_dir.exists():
            for path in sorted(skills_dir.iterdir(), key=lambda item: item.name.casefold()):
                if path.name == ".system" or not is_junction(path):
                    continue
                source = path.resolve(strict=True)
                staged = operation_staging / path.name
                shutil.copytree(source, staged)
                junctions.append((path, source, staged))
        detached: list[tuple[Path, Path]] = []
        try:
            for path, source, staged in junctions:
                remove_junction(path)
                os.replace(staged, path)
                detached.append((path, source))
            self.repository.remove_bindings_for_profile(profile.id)
        except Exception:
            rollback_root = self.paths.skill_backups / operation_id / "rollback-detached"
            for path, source in reversed(detached):
                if path.exists() and not is_junction(path):
                    destination = rollback_root / path.name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(path, destination)
                    create_junction(path, source)
            raise
        self._write_operation_log(
            operation_id,
            "账户解除全部共享并保留独立副本",
            {"profile_id": profile.id},
        )

    @guarded_mutation
    def set_profile_sharing(self, profile: Profile, enabled: bool) -> None:
        if not enabled:
            self.detach_profile(profile)
            self.repository.set_policy(profile.id, False)
            return
        self._ensure_profiles_stopped([profile])
        operation_id = self._operation_id("enable-profile")
        backup_root = self.paths.skill_backups / operation_id / profile.id
        backup_root.mkdir(parents=True, exist_ok=False)
        skills_dir = profile.codex_home / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        shared_directories = [
            shared
            for shared in sorted(self.paths.shared_skills.iterdir(), key=lambda item: item.name.casefold())
            if shared.is_dir() and shared.name != ".system"
        ]
        for shared in shared_directories:
            target = skills_dir / shared.name
            if is_junction(target):
                if target.resolve(strict=True) != shared.resolve(strict=True):
                    raise SkillConflictError(f"目录联接指向其他位置：{target}")
            elif target.exists() and hash_directory(target) != hash_directory(shared):
                raise SkillConflictError(
                    f"账户 {profile.name} 中的 {shared.name} 与共享版不同，请先在迁移预览中解决冲突。"
                )

        moved: list[tuple[Path, Path]] = []
        created: list[Path] = []
        bindings: list[tuple[str, str, str, Path, Path | None]] = []
        try:
            for shared in shared_directories:
                target = skills_dir / shared.name
                if is_junction(target):
                    bindings.append((profile.id, shared.name, "shared", target, None))
                    continue
                backup: Path | None = None
                if target.exists():
                    backup = backup_root / shared.name
                    os.replace(target, backup)
                    moved.append((backup, target))
                create_junction(target, shared)
                created.append(target)
                bindings.append((profile.id, shared.name, "shared", target, backup))
            self.repository.commit_migration([profile.id], [], bindings, [])
        except Exception:
            for target in reversed(created):
                if is_junction(target):
                    remove_junction(target)
            for backup, target in reversed(moved):
                if backup.exists() and not target.exists():
                    os.replace(backup, target)
            raise
        self._write_operation_log(
            operation_id,
            "账户启用共享技能",
            {"profile_id": profile.id},
        )

    @guarded_mutation
    def set_skill_binding(self, profile: Profile, skill_name: str, enabled: bool) -> None:
        self._ensure_profiles_stopped([profile])
        shared = self.paths.shared_skills / skill_name
        target = profile.codex_home / "skills" / skill_name
        if not shared.is_dir():
            raise SkillSharingError(f"共享库中不存在技能：{skill_name}")
        operation_id = self._operation_id("skill-binding")
        staging = self.paths.skill_staging / operation_id / profile.id / skill_name
        backup = self.paths.skill_backups / operation_id / profile.id / skill_name
        if enabled:
            if is_junction(target):
                return
            moved = False
            if target.exists():
                if hash_directory(target) != hash_directory(shared):
                    raise SkillConflictError(
                        f"账户 {profile.name} 中的 {skill_name} 与共享版不同。"
                    )
                backup.parent.mkdir(parents=True, exist_ok=True)
                os.replace(target, backup)
                moved = True
            try:
                create_junction(target, shared)
                self.repository.record_binding(profile.id, skill_name, "shared", target, backup)
            except Exception:
                if is_junction(target):
                    remove_junction(target)
                if moved and backup.exists() and not target.exists():
                    os.replace(backup, target)
                raise
            action = "启用单技能共享"
        else:
            if not is_junction(target):
                return
            staging.parent.mkdir(parents=True, exist_ok=True)
            detach_junction(target, staging)
            self.repository.record_binding(profile.id, skill_name, "local", target, None)
            action = "解除单技能共享并保留独立副本"
        self._write_operation_log(
            operation_id,
            action,
            {"profile_id": profile.id, "skill": skill_name},
        )

    def validate_profile(self, profile: Profile) -> list[str]:
        if not self.repository.policy_enabled(profile.id):
            return []
        issues: list[str] = []
        for binding in self.repository.bindings_for_profile(profile.id):
            name = binding["skill_name"]
            target = profile.codex_home / "skills" / name
            shared = self.paths.shared_skills / name
            if not shared.is_dir():
                issues.append(f"共享技能源目录不存在：{name}")
            elif not is_junction(target):
                issues.append(f"共享技能入口损坏：{name}")
            else:
                try:
                    if target.resolve(strict=True) != shared.resolve(strict=True):
                        issues.append(f"共享技能入口指向错误位置：{name}")
                except OSError:
                    issues.append(f"共享技能入口无法解析：{name}")
        return issues

    def status_for_profile(self, profile: Profile) -> tuple[bool, int, int]:
        enabled = self.repository.policy_enabled(profile.id)
        bindings = self.repository.bindings_for_profile(profile.id)
        issues = self.validate_profile(profile) if enabled else []
        return enabled, len(bindings), len(issues)

    @guarded_mutation
    def restore_latest_snapshot(self, skill_name: str, profiles: list[Profile]) -> None:
        self._ensure_profiles_stopped(profiles)
        snapshot = self.repository.latest_snapshot(skill_name)
        if not snapshot or not snapshot.path.is_dir():
            raise SkillSharingError(f"没有可恢复的快照：{skill_name}")
        target = self.paths.shared_skills / skill_name
        if target.is_dir():
            self._create_snapshot(skill_name, "恢复前自动快照")
        operation_id = self._operation_id("restore")
        backup = self.paths.skill_backups / operation_id / skill_name
        backup.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            os.replace(target, backup)
        try:
            shutil.copytree(snapshot.path, target)
        except Exception:
            if backup.exists() and not target.exists():
                os.replace(backup, target)
            raise
        digest = hash_directory(target)
        self.repository.upsert_shared_skill(skill_name, digest, "snapshot")
        self._write_operation_log(
            operation_id,
            "恢复共享技能快照",
            {"skill": skill_name, "snapshot": snapshot.id},
        )

    @guarded_mutation
    def remove_shared_skill(self, skill_name: str, profiles: list[Profile]) -> str:
        self._ensure_profiles_stopped(profiles)
        shared = self.paths.shared_skills / skill_name
        if not shared.is_dir():
            raise SkillSharingError(f"共享库中不存在技能：{skill_name}")
        operation_id = self._operation_id("global-remove")
        backup_root = self.paths.skill_backups / operation_id
        backup_root.mkdir(parents=True, exist_ok=False)
        self._create_snapshot(skill_name, "全局移除前最后快照")

        removed_links: list[tuple[Path, Path]] = []
        moved_local: list[tuple[Path, Path]] = []
        moved_shared: Path | None = None
        try:
            for profile in profiles:
                target = profile.codex_home / "skills" / skill_name
                if is_junction(target):
                    source = target.resolve(strict=True)
                    remove_junction(target)
                    removed_links.append((target, source))
                elif target.exists():
                    backup = backup_root / "account-local" / profile.id / skill_name
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(target, backup)
                    moved_local.append((backup, target))
            moved_shared = backup_root / "shared-library" / skill_name
            moved_shared.parent.mkdir(parents=True, exist_ok=True)
            os.replace(shared, moved_shared)
            self.repository.remove_shared_skill_records(skill_name)
        except Exception:
            if moved_shared and moved_shared.exists() and not shared.exists():
                os.replace(moved_shared, shared)
            for backup, target in reversed(moved_local):
                if backup.exists() and not target.exists():
                    os.replace(backup, target)
            for target, source in reversed(removed_links):
                if not target.exists() and source.exists():
                    create_junction(target, source)
            raise
        self._write_operation_log(
            operation_id,
            "全局移除共享技能并永久保留最后快照",
            {"skill": skill_name, "affected_profiles": [item.id for item in profiles]},
        )
        return operation_id

    def snapshot_count(self) -> int:
        return self.repository.snapshot_count()

    def _resolve_sources(
        self,
        preview: MigrationPreview,
        selections: dict[str, str],
    ) -> dict[str, SkillLocation]:
        chosen: dict[str, SkillLocation] = {}
        for plan in preview.valid_plans:
            selected_id = selections.get(plan.name)
            if plan.requires_choice and not selected_id:
                raise SkillConflictError(f"尚未选择冲突技能版本：{plan.name}")
            selected_id = selected_id or plan.recommended_profile_id
            source = next(
                (item for item in plan.sources if item.profile_id == selected_id),
                None,
            )
            if source is None or not source.valid:
                raise SkillConflictError(f"技能 {plan.name} 的来源选择无效。")
            chosen[plan.name] = source
        return chosen

    @staticmethod
    def _stage_sources(
        chosen: dict[str, SkillLocation], operation_staging: Path
    ) -> dict[str, Path]:
        staged: dict[str, Path] = {}
        source_root = operation_staging / "sources"
        source_root.mkdir(parents=True, exist_ok=True)
        for name, source in chosen.items():
            target = source_root / name
            shutil.copytree(source.path.resolve(strict=True), target)
            staged[name] = target
        return staged

    def _create_snapshot(
        self, skill_name: str, reason: str, *, record: bool = True
    ) -> SkillSnapshot:
        source = self.paths.shared_skills / skill_name
        digest = hash_directory(source)
        snapshot_id = self._operation_id("snapshot")
        destination = self.paths.skill_snapshots / skill_name / snapshot_id
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        snapshot = SkillSnapshot(
            id=snapshot_id,
            skill_name=skill_name,
            path=destination,
            digest=digest,
            created_at=datetime.now(timezone.utc).isoformat(),
            reason=reason,
        )
        if record:
            self.repository.add_snapshot(snapshot)
        return snapshot

    def _snapshot_external_changes(self) -> None:
        records = self.repository.shared_skill_records()
        if not self.paths.shared_skills.exists():
            return
        for source in self.paths.shared_skills.iterdir():
            if not source.is_dir() or source.name == ".system":
                continue
            digest = hash_directory(source)
            previous = records.get(source.name.casefold())
            if previous is None or previous["content_hash"] != digest:
                self._create_snapshot(source.name, "检测到外部修改")
                self.repository.upsert_shared_skill(
                    source.name,
                    digest,
                    previous["source_profile_id"] if previous else "external",
                )

    def _restore_unexpected_deletions(self) -> None:
        for record in self.repository.shared_skill_records().values():
            name = record["skill_name"]
            target = self.paths.shared_skills / name
            if target.exists():
                continue
            snapshot = self.repository.latest_snapshot(name)
            if snapshot and snapshot.path.is_dir():
                shutil.copytree(snapshot.path, target)
                self._write_operation_log(
                    self._operation_id("auto-restore"),
                    "检测到共享技能意外删除，已从最近快照恢复",
                    {"skill": name, "snapshot": snapshot.id},
                )

    def _ensure_profiles_stopped(self, profiles: list[Profile]) -> None:
        running: list[str] = []
        checker = getattr(self.launcher, "is_profile_process_running", None)
        for profile in profiles:
            is_running = checker(profile) if checker else getattr(self.launcher, "is_running")(profile.id)
            if is_running:
                running.append(profile.name)
        if running:
            raise RunningProfilesError(running)

    def _rollback_filesystem(
        self,
        operation_id: str,
        created_links: list[Path],
        moved_profiles: list[tuple[Path, Path]],
        installed_shared: list[tuple[Path, Path]],
        moved_shared: list[tuple[Path, Path]],
    ) -> None:
        rollback_root = self.paths.skill_backups / operation_id / "rollback-new-content"
        for path in reversed(created_links):
            if is_junction(path):
                remove_junction(path)
        for backup, original in reversed(moved_profiles):
            if backup.exists() and not original.exists():
                os.replace(backup, original)
        for current, fallback in reversed(installed_shared):
            if current.exists():
                fallback.parent.mkdir(parents=True, exist_ok=True)
                destination = rollback_root / current.name
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(current, destination)
        for backup, original in reversed(moved_shared):
            if backup.exists() and not original.exists():
                os.replace(backup, original)

    def _write_operation_log(self, operation_id: str, event: str, details: dict[str, object]) -> None:
        self.paths.skill_logs.mkdir(parents=True, exist_ok=True)
        path = self.paths.skill_logs / f"{operation_id}.log"
        record = {
            "time": datetime.now(timezone.utc).isoformat(),
            "event": event,
            "details": details,
        }
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, indent=2) + "\n")

    @contextmanager
    def _mutation_guard(self) -> Iterator[None]:
        with self._operation_lock:
            if os.name != "nt":
                yield
                return
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.CreateMutexW(
                None,
                False,
                "Local\\CodexProfileLauncherSkillMutation",
            )
            if not handle:
                raise SkillSharingError("无法创建共享技能操作锁。")
            wait_object_0 = 0x00000000
            try:
                result = kernel32.WaitForSingleObject(handle, 0)
                if result != wait_object_0:
                    raise SkillSharingError("另一个多开器窗口正在修改共享技能，请稍后重试。")
                try:
                    yield
                finally:
                    kernel32.ReleaseMutex(handle)
            finally:
                kernel32.CloseHandle(handle)

    @staticmethod
    def _operation_id(prefix: str) -> str:
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        return f"{prefix}-{timestamp}-{uuid.uuid4().hex[:8]}"
