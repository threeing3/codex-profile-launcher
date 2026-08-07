from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from .skill_models import SkillSnapshot


class SkillRepository:
    SCHEMA_VERSION = 1

    def __init__(self, database: Path) -> None:
        self.database = database

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_versions (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_skill_policies (
                    profile_id TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS shared_skills (
                    skill_name TEXT PRIMARY KEY COLLATE NOCASE,
                    content_hash TEXT NOT NULL,
                    source_profile_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS profile_skill_bindings (
                    profile_id TEXT NOT NULL,
                    skill_name TEXT NOT NULL COLLATE NOCASE,
                    state TEXT NOT NULL,
                    original_path TEXT NOT NULL DEFAULT '',
                    backup_path TEXT NOT NULL DEFAULT '',
                    applied_at TEXT NOT NULL,
                    PRIMARY KEY (profile_id, skill_name)
                );
                CREATE TABLE IF NOT EXISTS skill_snapshots (
                    id TEXT PRIMARY KEY,
                    skill_name TEXT NOT NULL COLLATE NOCASE,
                    path TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    reason TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT OR IGNORE INTO schema_versions(version, applied_at) VALUES (?, ?)",
                (self.SCHEMA_VERSION, self._now()),
            )

    def set_policy(self, profile_id: str, enabled: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO profile_skill_policies(profile_id, enabled, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                (profile_id, int(enabled), self._now()),
            )

    def policy_enabled(self, profile_id: str, default: bool = True) -> bool:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT enabled FROM profile_skill_policies WHERE profile_id=?",
                (profile_id,),
            ).fetchone()
        return default if row is None else bool(row[0])

    def enabled_profile_ids(self) -> set[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT profile_id FROM profile_skill_policies WHERE enabled=1"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def upsert_shared_skill(self, name: str, digest: str, source_profile_id: str) -> None:
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO shared_skills(skill_name, content_hash, source_profile_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(skill_name) DO UPDATE SET
                    content_hash=excluded.content_hash,
                    source_profile_id=excluded.source_profile_id,
                    updated_at=excluded.updated_at
                """,
                (name, digest, source_profile_id, now, now),
            )

    def shared_skill_records(self) -> dict[str, dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM shared_skills").fetchall()
        return {str(row["skill_name"]).casefold(): dict(row) for row in rows}

    def record_binding(
        self,
        profile_id: str,
        skill_name: str,
        state: str,
        original_path: Path | None = None,
        backup_path: Path | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO profile_skill_bindings(
                    profile_id, skill_name, state, original_path, backup_path, applied_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(profile_id, skill_name) DO UPDATE SET
                    state=excluded.state,
                    original_path=excluded.original_path,
                    backup_path=excluded.backup_path,
                    applied_at=excluded.applied_at
                """,
                (
                    profile_id,
                    skill_name,
                    state,
                    str(original_path or ""),
                    str(backup_path or ""),
                    self._now(),
                ),
            )

    def bindings_for_profile(self, profile_id: str) -> list[dict[str, str]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM profile_skill_bindings WHERE profile_id=? ORDER BY skill_name COLLATE NOCASE",
                (profile_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def remove_bindings_for_profile(self, profile_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM profile_skill_bindings WHERE profile_id=?", (profile_id,)
            )
            connection.execute(
                "DELETE FROM profile_skill_policies WHERE profile_id=?", (profile_id,)
            )

    def add_snapshot(self, snapshot: SkillSnapshot) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO skill_snapshots(id, skill_name, path, content_hash, created_at, reason)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.id,
                    snapshot.skill_name,
                    str(snapshot.path),
                    snapshot.digest,
                    snapshot.created_at,
                    snapshot.reason,
                ),
            )

    def commit_migration(
        self,
        profile_ids: list[str],
        shared_skills: list[tuple[str, str, str]],
        bindings: list[tuple[str, str, str, Path, Path | None]],
        snapshots: list[SkillSnapshot],
    ) -> None:
        now = self._now()
        with self._connect() as connection:
            for profile_id in profile_ids:
                connection.execute(
                    """
                    INSERT INTO profile_skill_policies(profile_id, enabled, updated_at)
                    VALUES (?, 1, ?)
                    ON CONFLICT(profile_id) DO UPDATE SET enabled=1, updated_at=excluded.updated_at
                    """,
                    (profile_id, now),
                )
            for name, digest, source_profile_id in shared_skills:
                connection.execute(
                    """
                    INSERT INTO shared_skills(skill_name, content_hash, source_profile_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(skill_name) DO UPDATE SET
                        content_hash=excluded.content_hash,
                        source_profile_id=excluded.source_profile_id,
                        updated_at=excluded.updated_at
                    """,
                    (name, digest, source_profile_id, now, now),
                )
            for profile_id, skill_name, state, original_path, backup_path in bindings:
                connection.execute(
                    """
                    INSERT INTO profile_skill_bindings(
                        profile_id, skill_name, state, original_path, backup_path, applied_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(profile_id, skill_name) DO UPDATE SET
                        state=excluded.state,
                        original_path=excluded.original_path,
                        backup_path=excluded.backup_path,
                        applied_at=excluded.applied_at
                    """,
                    (
                        profile_id,
                        skill_name,
                        state,
                        str(original_path),
                        str(backup_path or ""),
                        now,
                    ),
                )
            for snapshot in snapshots:
                connection.execute(
                    """
                    INSERT INTO skill_snapshots(id, skill_name, path, content_hash, created_at, reason)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.id,
                        snapshot.skill_name,
                        str(snapshot.path),
                        snapshot.digest,
                        snapshot.created_at,
                        snapshot.reason,
                    ),
                )

    def latest_snapshot(self, skill_name: str) -> SkillSnapshot | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM skill_snapshots
                WHERE skill_name=? COLLATE NOCASE
                ORDER BY created_at DESC LIMIT 1
                """,
                (skill_name,),
            ).fetchone()
        if not row:
            return None
        return SkillSnapshot(
            id=row["id"],
            skill_name=row["skill_name"],
            path=Path(row["path"]),
            digest=row["content_hash"],
            created_at=row["created_at"],
            reason=row["reason"],
        )

    def snapshot_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) FROM skill_snapshots").fetchone()
        return int(row[0])

    def remove_shared_skill_records(self, skill_name: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM profile_skill_bindings WHERE skill_name=? COLLATE NOCASE",
                (skill_name,),
            )
            connection.execute(
                "DELETE FROM shared_skills WHERE skill_name=? COLLATE NOCASE",
                (skill_name,),
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
