import json
from datetime import datetime, timezone
from threading import Event, Lock
from typing import Annotated
from uuid import uuid4

import anyio
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models import Chat, Message, User, TaskRun
from app.schemas.message import MessageCreate, MessageResponse
from app.services.ai_service import generate_chat_response, generate_chat_response_stream, log_ai_error
from app.services.attachments import attach_context

router = APIRouter(prefix="/api/chats", tags=["Messages"])
Id = Annotated[int, Path(ge=1, le=2147483647)]
RETRYABLE_STATUSES = {"failed", "interrupted", "incomplete", "stopped"}
FAILURE_TEXT = "Response generation failed."


def get_user_chat(chat_id: int, user_id: int, db: Session):
    chat = db.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id))
    if chat is None:
        raise HTTPException(404, "Chat not found")
    return chat


def serialize(message):
    return MessageResponse.model_validate(message).model_dump(mode="json")


def event(kind, **data):
    return f"event: {kind}\ndata: {json.dumps({'type': kind, **data})}\n\n"


def context_before(db, chat_id, message_id):
    return db.scalars(select(Message).where(Message.chat_id == chat_id, Message.id < message_id)
                      .order_by(Message.created_at, Message.id)).all()


def create_turn(db, chat_id):
    # Serialize creation/claims within a chat to prevent overlapping turns.
    db.execute(select(Chat.id).where(Chat.id == chat_id).with_for_update()).one()
    active = db.scalar(select(Message.id).where(Message.chat_id == chat_id, Message.status == "generating"))
    if active is not None:
        raise HTTPException(409, "Stop the current response before starting another.")


def new_messages(db, chat_id, content):
    create_turn(db, chat_id)
    user = Message(chat_id=chat_id, role="user", content=content, status="completed")
    assistant = Message(chat_id=chat_id, role="assistant", content="", status="generating",
                        generation_started_at=datetime.now(timezone.utc).replace(tzinfo=None),
                        generation_token=str(uuid4()), model=get_settings().GEMINI_MODEL)
    db.add(user)
    db.flush()
    db.add(assistant)
    db.commit()
    db.refresh(user)
    db.refresh(assistant)
    return user, assistant


def save_attempt(db, message_id, token, content, message_status):
    result = db.execute(update(Message).where(Message.id == message_id,
        Message.generation_token == token, Message.status == "generating")
        .values(content=content, status=message_status))
    if result.rowcount:
        chat_id = db.scalar(select(Message.chat_id).where(Message.id == message_id))
        db.execute(update(Chat).where(Chat.id == chat_id).values(updated_at=datetime.now(timezone.utc).replace(tzinfo=None)))
    db.commit()
    db.expire_all()
    return bool(result.rowcount)


@router.get("/{chat_id}/messages", response_model=list[MessageResponse])
def get_messages(chat_id: Id, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    from app.services.task_lifecycle import expire_runs
    expire_runs(db, chat_id)
    return db.scalars(select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at, Message.id)).all()


@router.post("/{chat_id}/messages", response_model=list[MessageResponse], status_code=201)
def send_message(chat_id: Id, data: MessageCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    content = attach_context(db, current_user.id, chat_id, data.content, data.attachment_ids)
    user, assistant = new_messages(db, chat_id, content)
    message_id, token = assistant.id, assistant.generation_token
    try:
        answer = generate_chat_response(context_before(db, chat_id, message_id))
        if not answer.strip():
            raise RuntimeError("Empty AI response")
        message_status = "completed"
    except Exception as exc:
        log_ai_error(exc)
        answer, message_status = FAILURE_TEXT, "failed"
    save_attempt(db, message_id, token, answer, message_status)
    return [user, db.get(Message, message_id)]


def stream_attempt(request, db, chat_id, assistant, user=None, previous=""):
    message_id, token = assistant.id, assistant.generation_token
    messages = context_before(db, chat_id, message_id)
    initial = serialize(assistant)
    user_data = serialize(user) if user else None

    async def events():
        chunks = []
        terminal = False
        cancelled = Event()
        source_lock = Lock()
        source = None
        def next_chunk():
            with source_lock:
                try:
                    item = next(source)
                    if cancelled.is_set():
                        getattr(source, "close", lambda: None)()
                        return False, None
                    return True, item
                except StopIteration:
                    return False, None
        try:
            yield event("started", message=initial, user_message=user_data)
            source = generate_chat_response_stream(messages)
            while True:
                available, chunk = await anyio.to_thread.run_sync(next_chunk, abandon_on_cancel=True)
                if not available:
                    break
                if await request.is_disconnected():
                    return
                chunks.append(chunk)
                text = "".join(chunks)
                if not save_attempt(db, message_id, token, text, "generating"):
                    terminal = True
                    return
                yield event("chunk", content=chunk)
            answer = "".join(chunks).strip()
            if not answer:
                raise RuntimeError("Empty AI response")
            if save_attempt(db, message_id, token, answer, "completed"):
                terminal = True
                yield event("done", content=answer, message=serialize(db.get(Message, message_id)))
        except Exception as exc:
            log_ai_error(exc)
            answer = "".join(chunks) or previous or FAILURE_TEXT
            if save_attempt(db, message_id, token, answer, "interrupted" if (chunks or previous) else "failed"):
                terminal = True
                yield event("error", detail=FAILURE_TEXT, content=answer, message=serialize(db.get(Message, message_id)))
        finally:
            cancelled.set()
            # Close promptly on Stop; if next() is still blocked, that worker
            # closes the generator when its provider call returns.
            if source is not None and source_lock.acquire(blocking=False):
                try:
                    getattr(source, "close", lambda: None)()
                finally:
                    source_lock.release()
            if not terminal:
                # This also runs when AbortController closes the HTTP connection.
                save_attempt(db, message_id, token, "".join(chunks) or previous, "interrupted")
    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


@router.post("/{chat_id}/messages/stream")
def stream_message(request: Request, chat_id: Id, data: MessageCreate, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    content = attach_context(db, current_user.id, chat_id, data.content, data.attachment_ids)
    user, assistant = new_messages(db, chat_id, content)
    return stream_attempt(request, db, chat_id, assistant, user)


@router.delete("/{chat_id}/messages/{message_id}", status_code=204)
def delete_failed_response(chat_id: Id, message_id: Id, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    chat = get_user_chat(chat_id, current_user.id, db)
    create_turn(db, chat_id)
    assistant = db.scalar(select(Message).where(
        Message.id == message_id, Message.chat_id == chat_id, Message.role == "assistant"))
    if assistant is None:
        raise HTTPException(404, "Assistant response not found")
    if assistant.status != "failed" or assistant.task_run_id:
        raise HTTPException(409, "Only failed regular responses can be deleted.")
    db.delete(assistant)
    chat.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return Response(status_code=204)


@router.post("/{chat_id}/messages/{message_id}/retry")
def retry_message(request: Request, chat_id: Id, message_id: Id, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    create_turn(db, chat_id)
    assistant = db.scalar(select(Message).where(Message.id == message_id, Message.chat_id == chat_id, Message.role == "assistant"))
    if assistant is None:
        raise HTTPException(404, "Assistant response not found")
    if assistant.status not in RETRYABLE_STATUSES:
        raise HTTPException(409, "Only failed or stopped responses can be retried.")
    if assistant.task_run_id:
        raise HTTPException(409, "Retry failed tasks in Task Activity to update this result.")
    previous = assistant.content if assistant.status != "failed" else ""
    assistant.status = "generating"
    assistant.generation_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    assistant.generation_token = str(uuid4())
    db.commit()
    db.refresh(assistant)
    return stream_attempt(request, db, chat_id, assistant, previous=previous)


@router.post("/{chat_id}/messages/{message_id}/stop", response_model=MessageResponse)
def stop_message(chat_id: Id, message_id: Id, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    assistant = db.scalar(select(Message).where(Message.id == message_id, Message.chat_id == chat_id, Message.role == "assistant"))
    if assistant is None:
        raise HTTPException(404, "Assistant response not found")
    if assistant.task_run_id:
        from app.api.tasks import cancel_tasks
        cancel_tasks(chat_id, db, current_user)
        db.refresh(assistant)
        return assistant
    db.execute(update(Message).where(Message.id == message_id, Message.status == "generating")
               .values(status="interrupted", generation_token=None))
    db.commit()
    db.refresh(assistant)
    return assistant


@router.post("/{chat_id}/messages/{message_id}/regenerate")
def regenerate(request: Request, chat_id: Id, message_id: Id, db: Session = Depends(get_db),
               current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    create_turn(db, chat_id)
    assistant = db.scalar(select(Message).where(Message.chat_id == chat_id, Message.role == "assistant").order_by(Message.id.desc()))
    if assistant is None or assistant.id != message_id or assistant.task_run_id:
        raise HTTPException(409, "Only the latest regular assistant answer can be regenerated.")
    previous = assistant.content if assistant.status == "completed" else ""
    assistant.status, assistant.generation_token = "generating", str(uuid4())
    assistant.generation_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return stream_attempt(request, db, chat_id, assistant, previous=previous)


@router.patch("/{chat_id}/messages/{message_id}", response_model=MessageResponse)
def edit_answer(chat_id: Id, message_id: Id, data: MessageCreate, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    create_turn(db, chat_id)
    assistant = db.scalar(select(Message).where(Message.id == message_id, Message.chat_id == chat_id, Message.role == "assistant"))
    if assistant is None:
        raise HTTPException(404, "Assistant response not found")
    if assistant.task_run_id:
        raise HTTPException(409, "Task results are updated by the task runner.")
    assistant.content, assistant.status = data.content, "completed"
    db.commit()
    db.refresh(assistant)
    return assistant


@router.post("/{chat_id}/messages/{message_id}/edit")
def edit_question(request: Request, chat_id: Id, message_id: Id, data: MessageCreate,
                  db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    create_turn(db, chat_id)
    user = db.scalar(select(Message).where(Message.chat_id == chat_id, Message.role == "user").order_by(Message.id.desc()))
    if user is None or user.id != message_id:
        raise HTTPException(409, "Only the latest question can be edited.")
    if db.scalar(select(TaskRun.id).where(TaskRun.user_message_id == user.id)):
        raise HTTPException(409, "Create a new task plan to change this request.")
    assistant = db.scalar(select(Message).where(Message.chat_id == chat_id, Message.role == "assistant", Message.id > user.id).order_by(Message.id))
    if assistant is None:
        raise HTTPException(409, "No answer exists for this question.")
    user.content = attach_context(db, current_user.id, chat_id, data.content, data.attachment_ids)
    assistant.content, assistant.status, assistant.generation_token = "", "generating", str(uuid4())
    assistant.generation_started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return stream_attempt(request, db, chat_id, assistant, user)
