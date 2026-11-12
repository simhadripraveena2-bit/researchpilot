"""API request/response models (kept separate from database models)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from researchpilot.domain.enums import (
    CheckpointStatus,
    ExpertiseLevel,
    ProjectGoal,
    ProjectStatus,
    RunStatus,
    Workflow,
)


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    topic: str = Field(min_length=3, max_length=500)
    expertise_level: ExpertiseLevel
    goal: ProjectGoal
    title: str | None = Field(default=None, max_length=200)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=200)
    expertise_level: ExpertiseLevel | None = None
    goal: ProjectGoal | None = None
    status: ProjectStatus | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    title: str
    topic: str
    expertise_level: ExpertiseLevel
    goal: ProjectGoal
    status: ProjectStatus
    created_at: datetime
    updated_at: datetime


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workflow: Workflow
    config: dict[str, Any] = Field(default_factory=dict)


class RunOut(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    workflow: Workflow
    status: RunStatus
    config: dict[str, Any]
    manifest: dict[str, Any]
    error: dict[str, Any] | None
    objective_version: int | None = None  # the objective version this run used
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class RunEventOut(BaseModel):
    id: int
    ts: datetime
    level: str
    type: str
    message: str
    data: dict[str, Any]


class CheckpointOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    name: str
    payload: dict[str, Any]
    status: CheckpointStatus
    decision: dict[str, Any] | None
    comment: str | None
    created_at: datetime
    decided_at: datetime | None


class CheckpointDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: CheckpointStatus
    decision: dict[str, Any] | None = None
    comment: str | None = Field(default=None, max_length=2000)


class Created(BaseModel):
    id: uuid.UUID
