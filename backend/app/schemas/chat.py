from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatTitle(BaseModel):
    @field_validator("title", mode="before", check_fields=False)
    @classmethod
    def trim_title(cls, value):
        return value.strip() if isinstance(value, str) else value


class ChatCreate(ChatTitle):
    title: str = Field(default="New Chat", min_length=1, max_length=255)


class ChatRename(ChatTitle):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    is_pinned: bool | None = None
    is_archived: bool | None = None


class ChatResponse(BaseModel):
    id: int
    user_id: int
    title: str
    model: str | None = None
    is_pinned: bool
    is_archived: bool
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
