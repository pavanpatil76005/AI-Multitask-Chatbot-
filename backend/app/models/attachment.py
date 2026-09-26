from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base, utcnow


class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[int | None] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int]
    sha256: Mapped[str] = mapped_column(String(64))
    text: Mapped[str] = mapped_column(Text)
    storage_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    upload_status: Mapped[str] = mapped_column(String(50), default="completed")  # completed, pending, failed
    processing_status: Mapped[str] = mapped_column(String(50), default="completed")  # completed, in_progress, failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
