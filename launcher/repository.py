from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from .models import Profile, ProfileKind


class ProfileRepository:
    def __init__(self, database: Path) -> None:
        self.database = database

    def initialize(self) -> None:
        self.database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    codex_home TEXT NOT NULL,
                    user_data_dir TEXT NOT NULL,
                    provider_name TEXT NOT NULL DEFAULT '',
                    base_url TEXT NOT NULL DEFAULT '',
                    model TEXT NOT NULL DEFAULT '',
                    color TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )

    def list(self) -> list[Profile]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM profiles ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def get(self, profile_id: str) -> Profile | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        return self._from_row(row) if row else None

    def save(self, profile: Profile) -> None:
        profile.validate()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO profiles (
                    id, name, kind, codex_home, user_data_dir,
                    provider_name, base_url, model, color, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind,
                    provider_name = excluded.provider_name,
                    base_url = excluded.base_url,
                    model = excluded.model,
                    color = excluded.color
                """,
                (
                    profile.id,
                    profile.name,
                    profile.kind.value,
                    str(profile.codex_home),
                    str(profile.user_data_dir),
                    profile.provider_name,
                    profile.base_url,
                    profile.model,
                    profile.color,
                    profile.created_at,
                ),
            )

    def remove_record(self, profile_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM profiles WHERE id = ?", (profile_id,))

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
    def _from_row(row: sqlite3.Row) -> Profile:
        return Profile(
            id=row["id"],
            name=row["name"],
            kind=ProfileKind(row["kind"]),
            codex_home=Path(row["codex_home"]),
            user_data_dir=Path(row["user_data_dir"]),
            provider_name=row["provider_name"],
            base_url=row["base_url"],
            model=row["model"],
            color=row["color"],
            created_at=row["created_at"],
        )
