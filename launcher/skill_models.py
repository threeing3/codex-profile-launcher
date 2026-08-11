from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path


SYSTEM_DEFAULT_PROFILE_ID = "__system_default__"
SHARED_LIBRARY_PROFILE_ID = "__shared_library__"


class SkillState(StrEnum):
    SHARED = "shared"
    IDENTICAL = "identical"
    UNIQUE = "unique"
    CONFLICT = "conflict"
    INVALID = "invalid"
    BROKEN = "broken"


@dataclass(frozen=True, slots=True)
class SkillLocation:
    profile_id: str
    profile_name: str
    name: str
    path: Path
    digest: str
    modified_at: float
    is_junction: bool = False
    valid: bool = True
    sensitive_findings: tuple[str, ...] = ()


@dataclass(slots=True)
class SkillPlan:
    name: str
    state: SkillState
    sources: list[SkillLocation] = field(default_factory=list)
    recommended_profile_id: str | None = None

    @property
    def requires_choice(self) -> bool:
        return self.state is SkillState.CONFLICT


@dataclass(slots=True)
class MigrationPreview:
    plans: list[SkillPlan]
    profile_ids: tuple[str, ...]

    @property
    def conflicts(self) -> list[SkillPlan]:
        return [plan for plan in self.plans if plan.requires_choice]

    @property
    def valid_plans(self) -> list[SkillPlan]:
        return [plan for plan in self.plans if plan.state is not SkillState.INVALID]


@dataclass(frozen=True, slots=True)
class SkillSnapshot:
    id: str
    skill_name: str
    path: Path
    digest: str
    created_at: str
    reason: str
