from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


TaskStatus = Literal["pending", "in_progress", "completed", "failed", "cancelled"]


class TaskBase(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    status: TaskStatus = Field(default="pending")
    progress: int = Field(default=0, ge=0, le=100)
    order: int = Field(default=0, ge=0)

    @field_validator("title")
    @classmethod
    def nonblank_title(cls, value):
        if not value.strip():
            raise ValueError("Task title must not be blank")
        return value.strip()

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value):
        return value.strip().lower() if isinstance(value, str) else value


class TaskCreate(TaskBase):
    attachment_ids: list[int] = Field(default_factory=list, max_length=1)
    @field_validator("status")
    @classmethod
    def pending_only(cls, value):
        if value != "pending":
            raise ValueError("New tasks must be pending")
        return value


class TaskUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    status: TaskStatus | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    order: int | None = Field(default=None, ge=0)

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value):
        if isinstance(value, str):
            value = value.strip().lower()
            if value not in {"pending", "in_progress", "completed", "failed", "cancelled"}:
                raise ValueError("Invalid task status")
            return value
        return value


class TaskResponse(TaskBase):
    run_id: int | None = None
    result: str | None = None
    error: str | None = None
    id: int
    chat_id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlanRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=60000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=1)

    @field_validator("prompt")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Enter a task request")
        return value


class PlannedTask(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1, max_length=8000)

    @field_validator("title", "description")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Plan contains a blank task")
        return value.strip()


class TaskPlan(BaseModel):
    tasks: list[PlannedTask] = Field(min_length=1, max_length=8)
