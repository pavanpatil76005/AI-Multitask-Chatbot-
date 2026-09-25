from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'failed', 'cancelled')",
            name="ck_tasks_status",
        ),
    )

    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("task_runs.id", ondelete="CASCADE"), nullable=True, index=True)
    generation_token: Mapped[str | None] = mapped_column(String(36), nullable=True)

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    chat_id: Mapped[int] = mapped_column(
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        default=None
    )

    status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        nullable=False
    )

    progress: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )

    order: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=utcnow,
        onupdate=utcnow
    )

    chat = relationship(
        "Chat",
        back_populates="tasks"
    )
