"""Extract bounded document text; originals are never written to disk."""
import csv
import io
import hashlib
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.models import User, Attachment, Chat
from app.core.database import get_db
from app.services.attachments import csv_statistics

router = APIRouter(prefix="/api/files", tags=["Files"])
MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 40000


def extract_text(filename: str, data: bytes) -> str:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted or len(reader.pages) > 50:
                raise ValueError("Use an unencrypted PDF with at most 50 pages.")
            parts = []
            for page in reader.pages:
                parts.append(page.extract_text() or "")
                if sum(map(len, parts)) > MAX_TEXT:
                    raise ValueError("Document exceeds 40,000 characters.")
            text = "\n".join(parts)
        elif suffix in {".txt", ".md", ".csv"}:
            text = data.decode("utf-8-sig")
            if suffix == ".csv":
                # Validate quoted records while preserving the original tabular data.
                list(csv.reader(io.StringIO(text), strict=True))
        else:
            raise HTTPException(415, "Supported files: PDF, CSV, TXT, and Markdown.")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(422, "Cannot read this file. Use UTF-8 text/CSV or an unencrypted text PDF (up to 50 pages).") from None
    if not text.strip():
        raise HTTPException(422, "No readable text found. Scanned PDFs require OCR.")
    if len(text) > MAX_TEXT:
        raise HTTPException(413, "Document exceeds 40,000 characters.")
    return text


@router.post("/extract")
def extract(file: UploadFile, chat_id: int | None = Form(default=None, ge=1),
            db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if chat_id is not None and db.scalar(select(Chat.id).where(Chat.id == chat_id, Chat.user_id == current_user.id)) is None:
        raise HTTPException(404, "Chat not found")
    data = file.file.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise HTTPException(413, "File exceeds the 5 MB limit.")
    filename = (file.filename or "document").replace("\\", "/").split("/")[-1][:255]
    text = extract_text(filename, data)
    extension = Path(filename).suffix.lower()
    media_type = {".pdf": "application/pdf", ".csv": "text/csv", ".txt": "text/plain", ".md": "text/markdown"}[extension]
    attachment = Attachment(user_id=current_user.id, chat_id=chat_id, filename=filename,
        media_type=media_type, size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), text=text)
    db.add(attachment)
    db.commit()
    db.refresh(attachment)
    return {"id": attachment.id, "chat_id": chat_id, "filename": filename, "text": text,
            "size_bytes": len(data), "media_type": media_type,
            "statistics": csv_statistics(text) if extension == ".csv" else None}


@router.get("")
def list_files(chat_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if db.scalar(select(Chat.id).where(Chat.id == chat_id, Chat.user_id == current_user.id)) is None:
        raise HTTPException(404, "Chat not found")
    rows = db.scalars(select(Attachment).where(Attachment.chat_id == chat_id, Attachment.user_id == current_user.id)
                      .order_by(Attachment.id)).all()
    return [{"id": row.id, "filename": row.filename, "size_bytes": row.size_bytes,
             "media_type": row.media_type, "created_at": row.created_at} for row in rows]
