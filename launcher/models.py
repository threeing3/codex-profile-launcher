from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import os
from pathlib import Path
from uuid import uuid4


class ProfileKind(StrEnum):
    SYSTEM_DEFAULT = "system_default"
    ACCOUNT = "account"
    PROVIDER = "provider"


@dataclass(frozen=True, slots=True)
class Profile:
    id: str
    name: str
    kind: ProfileKind
    codex_home: Path
    user_data_dir: Path
    provider_name: str = ""
    base_url: str = ""
    model: str = ""
    color: str = "#4F7467"
    created_at: str = ""

    @classmethod
    def system_default(cls) -> "Profile":
        app_data = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return cls(
            id="__system_default__",
            name="系统默认 Codex",
            kind=ProfileKind.SYSTEM_DEFAULT,
            codex_home=Path.home() / ".codex",
            user_data_dir=app_data / "Codex" / "web" / "Codex",
            provider_name="本机已有账号与聊天记录",
            color="#354F66",
        )

    @classmethod
    def create(
        cls,
        *,
        name: str,
        kind: ProfileKind,
        profiles_root: Path,
        provider_name: str = "",
        base_url: str = "",
        model: str = "",
        color: str = "#4F7467",
    ) -> "Profile":
        profile_id = uuid4().hex
        profile_root = profiles_root / profile_id
        return cls(
            id=profile_id,
            name=name.strip(),
            kind=kind,
            codex_home=profile_root / "codex-home",
            user_data_dir=profile_root / "user-data",
            provider_name=provider_name.strip(),
            base_url=base_url.strip(),
            model=model.strip(),
            color=color,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

    @property
    def subtitle(self) -> str:
        if self.kind is ProfileKind.SYSTEM_DEFAULT:
            return "已有账号与聊天记录"
        if self.kind is ProfileKind.ACCOUNT:
            return "ChatGPT account"
        return self.provider_name or "Custom provider"

    @property
    def is_system_default(self) -> bool:
        return self.kind is ProfileKind.SYSTEM_DEFAULT

    def validate(self) -> None:
        if self.is_system_default:
            return
        if not self.name:
            raise ValueError("Profile name is required.")
        if self.kind is ProfileKind.PROVIDER and not self.base_url:
            raise ValueError("Provider profiles require a Base URL.")
