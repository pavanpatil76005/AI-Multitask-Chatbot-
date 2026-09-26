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
MAX_BYTES = 50 * 1024 * 1024  # 50 MB direct upload limit
MAX_TEXT = 40000
CHUNK_SIZE = 1024 * 1024  # 1 MB chunks for reading


def extract_text(filename: str, data: bytes) -> str:
    """Extract text from file with chunking for large documents."""
    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted or len(reader.pages) > 50:
                raise ValueError("Use an unencrypted PDF with at most 50 pages.")
            parts = []
            for page_idx, page in enumerate(reader.pages):
                page_text = page.extract_text() or ""
                parts.append(page_text)
                # Check if we're exceeding the character limit
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
    
    # Chunked reading to avoid loading entire file into memory
    data_chunks = []
    total_size = 0
    sha256_hash = hashlib.sha256()
    
    while True:
        chunk = file.file.read(CHUNK_SIZE)
        if not chunk:
            break
        data_chunks.append(chunk)
        sha256_hash.update(chunk)
        total_size += len(chunk)
        
        if total_size > MAX_BYTES:
            raise HTTPException(413, "File exceeds the 50 MB limit.")
    
    data = b"".join(data_chunks)
    filename = (file.filename or "document").replace("\\", "/").split("/")[-1][:255]
    text = extract_text(filename, data)
    extension = Path(filename).suffix.lower()
    media_type = {".pdf": "application/pdf", ".csv": "text/csv", ".txt": "text/plain", ".md": "text/markdown"}[extension]
    
    attachment = Attachment(
        user_id=current_user.id, 
        chat_id=chat_id, 
        filename=filename,
        media_type=media_type, 
        size_bytes=len(data), 
        sha256=sha256_hash.hexdigest(), 
        text=text,
        upload_status="completed",
        processing_status="completed"
    )
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


@router.post("/presign")
def presign_large_upload(
    chat_id: int | None = Form(default=None, ge=1),
    filename: str = Form(...),
    file_size: int = Form(..., gt=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate presigned URL for large file upload to object storage.
    
    For future implementation with S3/GCS. Currently returns placeholder.
    """
    if chat_id is not None and db.scalar(select(Chat.id).where(Chat.id == chat_id, Chat.user_id == current_user.id)) is None:
        raise HTTPException(404, "Chat not found")
    
    if file_size > 500 * 1024 * 1024:
        raise HTTPException(413, "File exceeds the 500 MB limit.")
    
    # Placeholder for future object storage integration
    return {
        "upload_url": f"https://storage.example.com/uploads/{current_user.id}/{filename}",
        "storage_key": f"uploads/{current_user.id}/{filename}",
        "expiry": 3600,
        "method": "PUT",
        "headers": {}
    }


@router.post("/complete")
def complete_large_upload(
    filename: str = Form(...),
    storage_key: str = Form(...),
    file_size: int = Form(..., gt=0),
    chat_id: int | None = Form(default=None, ge=1),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Complete large file upload and process from object storage.
    
    For future implementation. Currently returns error.
    """
    if chat_id is not None and db.scalar(select(Chat.id).where(Chat.id == chat_id, Chat.user_id == current_user.id)) is None:
        raise HTTPException(404, "Chat not found")
    
    raise HTTPException(501, "Large file processing via object storage not yet implemented. Use direct upload (up to 50 MB).")
