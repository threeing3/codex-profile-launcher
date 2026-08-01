from __future__ import annotations

import os
import re
import shutil
import tomllib
from pathlib import Path

from .models import Profile, ProfileKind


def initialize_provider_config(profile: Profile) -> bool:
    """Create a minimal provider config without overwriting existing Codex state."""
    if profile.kind is not ProfileKind.PROVIDER:
        return False

    config_path = profile.codex_home / "config.toml"
    if config_path.exists():
        return False

    profile.codex_home.mkdir(parents=True, exist_ok=True)
    rendered = render_provider_config(profile)
    tomllib.loads(rendered)
    config_path.write_text(rendered, encoding="utf-8")
    return True


def sync_provider_config(profile: Profile) -> None:
    """Update launcher-owned keys while preserving the rest of config.toml."""
    if profile.kind is not ProfileKind.PROVIDER:
        return

    config_path = profile.codex_home / "config.toml"
    if not config_path.exists():
        initialize_provider_config(profile)
        return

    original = config_path.read_text(encoding="utf-8")
    updated = _upsert_top_level_string(original, "openai_base_url", profile.base_url)
    if profile.model:
        updated = _upsert_top_level_string(updated, "model", profile.model)
    else:
        updated = _remove_top_level_key(updated, "model")
    if updated == original:
        return

    tomllib.loads(updated)
    backup_path = config_path.with_suffix(".toml.bak")
    shutil.copy2(config_path, backup_path)
    temporary_path = config_path.with_suffix(".toml.tmp")
    temporary_path.write_text(updated, encoding="utf-8")
    os.replace(temporary_path, config_path)


def render_provider_config(profile: Profile) -> str:
    lines = [
        "# Created for this isolated Codex desktop profile.",
        "# API keys are intentionally not stored by Codex Profile Launcher.",
    ]
    if profile.model:
        lines.append(f'model = "{_toml_string(profile.model)}"')
    lines.append(f'openai_base_url = "{_toml_string(profile.base_url)}"')
    return "\n".join(lines) + "\n"


def _toml_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "")


def _upsert_top_level_string(content: str, key: str, value: str) -> str:
    rendered = f'{key} = "{_toml_string(value)}"'
    pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=.*$")
    if pattern.search(content):
        return pattern.sub(rendered, content, count=1)
    separator = "" if not content or content.endswith("\n") else "\n"
    return f"{rendered}\n{separator}{content}"


def _remove_top_level_key(content: str, key: str) -> str:
    pattern = re.compile(rf"(?m)^{re.escape(key)}\s*=.*\n?")
    return pattern.sub("", content, count=1)
