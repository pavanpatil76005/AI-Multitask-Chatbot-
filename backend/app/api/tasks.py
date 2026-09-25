from typing import Annotated


from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.chat import Chat
from app.models.task import Task
from app.models import TaskRun, Message
from app.models.user import User
from app.schemas.task import TaskCreate, TaskResponse, TaskUpdate
from app.schemas.task import PlanRequest
from app.services.task_service import plan_tasks, execute_task
from app.services.ai_service import log_ai_error
from app.services.task_lifecycle import execute_run, expire_runs, finish_run
from app.services.attachments import attach_context


router = APIRouter(
    prefix="/api/chats",
    tags=["Tasks"],
)


def get_user_chat(
    chat_id: Annotated[int, Path(ge=1, le=2147483647)],
    user_id: int,
    db: Session,
):
    chat = db.scalar(
        select(Chat).where(
            Chat.id == chat_id,
            Chat.user_id == user_id,
        )
    )

    if chat is None:
        raise HTTPException(status_code=404, detail="Chat not found")

    return chat


@router.post(
    "/{chat_id}/tasks",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_task(
    chat_id: Annotated[int, Path(ge=1, le=2147483647)],
    data: TaskCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    chat = get_user_chat(chat_id, current_user.id, db)

    task = Task(
        chat_id=chat.id,
        title=data.title,
        description=attach_context(db, current_user.id, chat_id, data.description or data.title, data.attachment_ids),
        status=data.status,
        progress=data.progress,
        order=data.order,
    )

    db.add(task)
    db.commit()
    db.refresh(task)

    return task


@router.get(
    "/{chat_id}/tasks",
    response_model=list[TaskResponse],
)
def list_tasks(
    chat_id: Annotated[int, Path(ge=1, le=2147483647)],
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_user_chat(chat_id, current_user.id, db)

    expire_runs(db, chat_id)
    return db.scalars(
        select(Task)
        .where(Task.chat_id == chat_id)
        .order_by(Task.order.asc(), Task.id.asc())
    ).all()


@router.patch(
    "/{chat_id}/tasks/{task_id}",
    response_model=TaskResponse,
)
def update_task(
    chat_id: Annotated[int, Path(ge=1, le=2147483647)],
    task_id: Annotated[int, Path(ge=1, le=2147483647)],
    data: TaskUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    get_user_chat(chat_id, current_user.id, db)

    task = db.scalar(
        select(Task).where(
            Task.id == task_id,
            Task.chat_id == chat_id,
        )
    )

    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    if task.status == "in_progress":
        raise HTTPException(409, "This task is running.")
    if task.run_id is not None:
        raise HTTPException(409, "Planned tasks are updated by the runner. Use Retry or create a new plan.")

    if "status" in data.model_fields_set and data.status == "in_progress":
        raise HTTPException(409, "Running status is managed by the task executor.")

    for field, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(task, field, value)

    db.commit()
    db.refresh(task)
    return task


@router.post("/{chat_id}/tasks/plan", response_model=list[TaskResponse], status_code=201)
def plan(chat_id: Annotated[int, Path(ge=1, le=2147483647)], data: PlanRequest,
         db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    prompt = attach_context(db, current_user.id, chat_id, data.prompt, data.attachment_ids)
    db.commit()
    try:
        planned = plan_tasks(prompt)
    except Exception as exc:
        log_ai_error(exc)
        raise HTTPException(502, "Task planning failed. Please retry.") from None
    # Persist only a fully validated plan.
    get_user_chat(chat_id, current_user.id, db)
    from app.api.messages import create_turn
    create_turn(db, chat_id)
    user = Message(chat_id=chat_id, role="user", content=prompt, status="completed")
    db.add(user)
    db.flush()
    run = TaskRun(chat_id=chat_id, prompt=prompt, user_message_id=user.id)
    db.add(run)
    db.flush()
    tasks = [Task(chat_id=chat_id, run_id=run.id, title=item.title, description=item.description,
                  status="pending", progress=0, order=index)
             for index, item in enumerate(planned.tasks)]
    db.add_all(tasks)
    db.commit()
    return tasks


@router.post("/{chat_id}/tasks/run", response_model=list[TaskResponse])
def run_tasks(chat_id: Annotated[int, Path(ge=1, le=2147483647)], run_id: int | None = None,
              db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    return execute_run(db, chat_id, execute_task, run_id=run_id)


@router.post("/{chat_id}/tasks/{task_id}/retry", response_model=list[TaskResponse])
def retry_task(chat_id: Annotated[int, Path(ge=1, le=2147483647)], task_id: Annotated[int, Path(ge=1)],
               db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    return execute_run(db, chat_id, execute_task, task_id=task_id)


@router.post("/{chat_id}/tasks/cancel", response_model=list[TaskResponse])
def cancel_tasks(chat_id: Annotated[int, Path(ge=1, le=2147483647)],
                 db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    get_user_chat(chat_id, current_user.id, db)
    runs = db.scalars(select(TaskRun).where(TaskRun.chat_id == chat_id, TaskRun.status == "running").with_for_update()).all()
    for run in runs:
        token = run.generation_token
        db.execute(update(Task).where(Task.run_id == run.id, Task.status.in_(["in_progress", "pending"]))
                   .values(status="cancelled", progress=0, generation_token=None, error="Task cancelled."))
        finish_run(db, run.id, token)
    db.commit()
    return db.scalars(select(Task).where(Task.chat_id == chat_id).order_by(Task.order, Task.id)).all()
