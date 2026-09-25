from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    role: Mapped[str] = mapped_column(
        String(30),
        nullable=False
    )

    content: Mapped[str] = mapped_column(
        Text,
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="completed"
    )

    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    token_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True
    )

    generation_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    generation_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow
    )

    chat = relationship(
        "Chat",
        back_populates="messages"
    )

    task_result_run = relationship("TaskRun", foreign_keys="TaskRun.result_message_id", uselist=False, viewonly=True)
    task_request_run = relationship("TaskRun", foreign_keys="TaskRun.user_message_id", uselist=False, viewonly=True)

    @property
    def task_run_id(self):
        run = self.task_result_run or self.task_request_run
        return run.id if run else None
