from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base, utcnow


class Chat(Base):
    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        index=True
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    title: Mapped[str] = mapped_column(
        String(255),
        default="New Chat",
        nullable=False
    )

    model: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True
    )

    is_pinned: Mapped[bool] = mapped_column(
        Boolean,
        default=False
    )

    is_archived: Mapped[bool] = mapped_column(
        Boolean,
        default=False
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

    user = relationship(
        "User",
        back_populates="chats"
    )

    messages = relationship(
        "Message",
        back_populates="chat",
        cascade="all, delete-orphan"
    )

    tasks = relationship(
        "Task",
        back_populates="chat",
        cascade="all, delete-orphan"
    )
