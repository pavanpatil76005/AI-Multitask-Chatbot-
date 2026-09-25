from typing import Annotated
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from sqlalchemy import select, or_, exists
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.chat import Chat
from app.models.user import User
from app.models.message import Message
from app.schemas.chat import (
    ChatCreate,
    ChatRename,
    ChatResponse,
)


router = APIRouter(
    prefix="/api/chats",
    tags=["Chats"]
)


@router.post(
    "",
    response_model=ChatResponse,
    status_code=status.HTTP_201_CREATED
)
def create_chat(
    data: ChatCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    chat = Chat(
        user_id=current_user.id,
        title=data.title
    )

    db.add(chat)
    db.commit()
    db.refresh(chat)

    return chat


@router.get(
    "",
    response_model=list[ChatResponse]
)
def get_chats(
    q: str = Query(default="", max_length=200),
    archived: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    query = select(Chat).where(Chat.user_id == current_user.id, Chat.is_archived == archived)
    if q.strip():
        query = query.where(or_(Chat.title.icontains(q.strip(), autoescape=True),
            exists(select(Message.id).where(Message.chat_id == Chat.id, Message.content.icontains(q.strip(), autoescape=True)))))
    chats = db.scalars(query.order_by(Chat.is_pinned.desc(), Chat.updated_at.desc(), Chat.id.desc())).all()

    return chats


@router.get(
    "/{chat_id}",
    response_model=ChatResponse
)
def get_chat(
    chat_id: Annotated[int, Path(ge=1, le=2147483647)],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    chat = db.scalar(
        select(Chat).where(
            Chat.id == chat_id,
            Chat.user_id == current_user.id
        )
    )

    if chat is None:
        raise HTTPException(
            status_code=404,
            detail="Chat not found"
        )

    return chat


@router.patch(
    "/{chat_id}",
    response_model=ChatResponse
)
def rename_chat(
    chat_id: Annotated[int, Path(ge=1, le=2147483647)],
    data: ChatRename,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    chat = db.scalar(
        select(Chat).where(
            Chat.id == chat_id,
            Chat.user_id == current_user.id
        )
    )

    if chat is None:
        raise HTTPException(
            status_code=404,
            detail="Chat not found"
        )

    changes = data.model_dump(exclude_none=True)
    if not changes:
        raise HTTPException(422, "Provide a title, pin, or archive change")
    for field, value in changes.items():
        setattr(chat, field, value)

    db.commit()
    db.refresh(chat)

    return chat


@router.delete(
    "/{chat_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
def delete_chat(
    chat_id: Annotated[int, Path(ge=1, le=2147483647)],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):

    chat = db.scalar(
        select(Chat).where(
            Chat.id == chat_id,
            Chat.user_id == current_user.id
        )
    )

    if chat is None:
        raise HTTPException(
            status_code=404,
            detail="Chat not found"
        )

    db.delete(chat)
    db.commit()
