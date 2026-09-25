from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=60000)
    attachment_ids: list[int] = Field(default_factory=list, max_length=1)

    @field_validator("content")
    @classmethod
    def nonblank_content(cls, value):
        if not value.strip():
            raise ValueError("Message content must not be blank")
        return value


class MessageResponse(BaseModel):
    task_run_id: int | None = None
    id: int
    chat_id: int
    role: str
    content: str
    status: str
    model: str | None = None
    token_count: int | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
