"""Bounded task execution with persisted deadlines and guarded late results."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from app.models import Chat, Message, Task, TaskRun
from app.services.ai_service import log_ai_error

EXECUTOR = ThreadPoolExecutor(max_workers=6, thread_name_prefix="ai-task")
RUN_SLOTS = BoundedSemaphore(2)
RUN_TIMEOUT_SECONDS = 180
STREAM_TIMEOUT_SECONDS = 15 * 60


def utcnow() -> datetime:
    """Return naive UTC for the project's existing DateTime columns."""
    return datetime.now(UTC).replace(tzinfo=None)


def aggregate_results(tasks):
    completed = sum(task.status == "completed" for task in tasks)
    sections = [f"## Task results\n\n{completed} / {len(tasks)} complete"]
    for task in tasks:
        content = (task.result or "Task completed without a saved result."
                   if task.status == "completed" else
                   task.error or f"Task {task.status}.")
        sections.append(f"### {task.title}\n\n{content}")
    return "\n\n---\n\n".join(sections)


def finish_run(db, run_id, token):
    run = db.scalar(select(TaskRun).where(TaskRun.id == run_id).with_for_update().execution_options(populate_existing=True))
    if run is None or run.generation_token != token or run.status != "running":
        return
    tasks = db.scalars(select(Task).where(Task.run_id == run.id).order_by(Task.order, Task.id)
                       .execution_options(populate_existing=True)).all()
    all_done = bool(tasks) and all(task.status == "completed" for task in tasks)
    partial = any(task.status == "completed" for task in tasks)
    run.status = "completed" if all_done else "cancelled" if any(t.status == "cancelled" for t in tasks) else "failed"
    text = aggregate_results(tasks)
    db.execute(update(Message).where(Message.id == run.result_message_id,
        Message.generation_token == token, Message.status == "generating").values(
            content=text, status="completed" if all_done else "interrupted" if partial else "failed",
            generation_token=None))
    run.generation_token = None
    run.deadline_at = None
    db.execute(update(Chat).where(Chat.id == run.chat_id).values(updated_at=utcnow()))
    db.commit()


def fail_run(db, run_id, token, error):
    """Fail every unfinished task in a run, then persist one guarded result."""
    run = db.scalar(select(TaskRun).where(TaskRun.id == run_id).with_for_update()
                    .execution_options(populate_existing=True))
    if run is None or run.generation_token != token or run.status != "running":
        return False
    db.execute(update(Task).where(
        Task.run_id == run.id, Task.status.in_(["pending", "in_progress"])
    ).values(status="failed", progress=0, generation_token=None, error=error))
    finish_run(db, run.id, token)
    return True


def expire_runs(db, chat_id=None):
    query = select(TaskRun).where(
        TaskRun.status == "running",
        or_(TaskRun.deadline_at.is_(None), TaskRun.deadline_at <= utcnow()),
    )
    if chat_id is not None:
        query = query.where(TaskRun.chat_id == chat_id)
    for run in db.scalars(query.with_for_update()).all():
        fail_run(db, run.id, run.generation_token, "Task timed out. Retry to try again.")


def recover_interrupted_work(db, *, startup=False):
    """Recover persisted work after a crash/restart and during periodic sweeps."""
    active_run = select(TaskRun.id).where(TaskRun.status == "running")
    orphaned_tasks = update(Task).where(
        Task.status == "in_progress",
        or_(Task.run_id.is_(None), ~Task.run_id.in_(active_run)),
    ).values(
        status="failed", progress=0, generation_token=None,
        error="Task state was interrupted or inconsistent. Retry to try again.",
    )
    if startup:
        running = db.scalars(select(TaskRun).where(TaskRun.status == "running")).all()
        for run in running:
            fail_run(db, run.id, run.generation_token,
                    "Task execution was interrupted by a server restart. Retry to try again.")
        stale_streams = db.scalars(select(Message).where(Message.status == "generating")).all()
    else:
        expire_runs(db)
        task_messages = select(TaskRun.result_message_id).where(
            TaskRun.status == "running", TaskRun.result_message_id.is_not(None)
        )
        stale_streams = db.scalars(select(Message).where(
            Message.status == "generating",
            Message.id.not_in(task_messages),
            func.coalesce(Message.generation_started_at, Message.created_at) <= utcnow() - timedelta(seconds=STREAM_TIMEOUT_SECONDS),
        )).all()
    orphaned_count = db.execute(orphaned_tasks).rowcount
    from app.api.messages import save_attempt
    for message in stale_streams:
        if message.generation_token:
            save_attempt(db, message.id, message.generation_token, message.content, "interrupted")
        else:
            message.status, message.generation_token = "interrupted", None
    if stale_streams:
        db.commit()
    elif orphaned_count:
        db.commit()
    return (len(running) if startup else len(stale_streams)) + orphaned_count


def save_task_result(db, task_id, token, result=None, error=None):
    changed = db.execute(update(Task).where(Task.id == task_id, Task.generation_token == token,
        Task.status == "in_progress").values(status="failed" if error else "completed",
        result=result, error=error, progress=0 if error else 100, generation_token=None))
    db.commit()
    return bool(changed.rowcount)


def execute_run(db, chat_id, execute_task, task_id=None, run_id=None):
    from app.api.messages import create_turn
    expire_runs(db, chat_id)
    create_turn(db, chat_id)
    if task_id is not None:
        requested = db.scalar(select(Task).where(Task.id == task_id, Task.chat_id == chat_id))
        if requested is None:
            raise HTTPException(404, "Task not found")
        if requested.status not in {"failed", "cancelled"}:
            raise HTTPException(409, "Only failed or cancelled tasks can be retried.")
        run_id = requested.run_id
    retryable = ["pending", "failed", "cancelled"]
    query = select(Task).where(Task.chat_id == chat_id, Task.status.in_(retryable))
    if run_id is not None:
        query = query.where(Task.run_id == run_id)
    if task_id is not None:
        query = query.where(Task.id == task_id)
    candidates = db.scalars(query.order_by(Task.order, Task.id)).all()
    if not candidates:
        raise HTTPException(409, "No pending, failed, or cancelled tasks to run.")
    # Each request processes exactly one plan, never aggregates unrelated plans.
    chosen_run_id = candidates[0].run_id
    pending = [task for task in candidates if task.run_id == chosen_run_id][:8]
    if not RUN_SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Task workers are busy. Retry shortly.")
    futures = {}
    token = str(uuid4())
    run = None
    active_run_id = None
    try:
        if chosen_run_id is None:
            prompt = "\n".join(t.title for t in pending)
            user = Message(chat_id=chat_id, role="user", content=prompt, status="completed")
            db.add(user)
            db.flush()
            run = TaskRun(chat_id=chat_id, prompt=prompt, user_message_id=user.id)
            db.add(run)
            db.flush()
            for task in pending:
                task.run_id = run.id
        else:
            run = db.get(TaskRun, chosen_run_id)
        if run.status == "running":
            raise HTTPException(409, "This plan is already running.")
        assistant = db.get(Message, run.result_message_id) if run.result_message_id else None
        if assistant is None:
            assistant = Message(chat_id=chat_id, role="assistant", content="", status="generating")
            db.add(assistant)
            db.flush()
            run.result_message_id = assistant.id
        assistant.status, assistant.generation_token = "generating", token
        assistant.generation_started_at = utcnow()
        run.status, run.generation_token = "running", token
        run.deadline_at = utcnow() + timedelta(seconds=RUN_TIMEOUT_SECONDS)
        inputs = [(t.id, t.title, t.description or "") for t in pending]
        for task in pending:
            task.status, task.progress, task.error, task.generation_token = "in_progress", 10, None, token
        db.commit()
        active_run_id = run.id
        original_goal = run.prompt
        # Submit only three at a time, leaving remaining tasks cancellable.
        queue = iter(inputs)
        def submit_next():
            item = next(queue, None)
            if item:
                task_id, title, description = item
                completed = db.scalars(select(Task).where(
                    Task.chat_id == chat_id, Task.run_id == active_run_id,
                    Task.status == "completed", Task.id != task_id,
                ).order_by(Task.order, Task.id)).all()
                previous_results = "\n\n".join(
                    f"### {task.title}\n{task.result}" for task in completed if task.result
                )
                futures[EXECUTOR.submit(execute_task, title, description,
                    original_goal=original_goal, previous_results=previous_results)] = task_id
        for _ in range(3):
            submit_next()
        while futures:
            done, _ = wait(futures, timeout=.25, return_when=FIRST_COMPLETED)
            db.expire_all()
            current = db.get(TaskRun, active_run_id)
            if current is None or current.status != "running" or current.generation_token != token:
                break
            if current.deadline_at <= utcnow():
                expire_runs(db, chat_id)
                break
            for future in done:
                task_id = futures.pop(future)
                try:
                    result = future.result()
                    if not result or not result.strip():
                        raise RuntimeError("Empty task result")
                    save_task_result(db, task_id, token, result=result)
                except Exception as exc:
                    log_ai_error(exc)
                    save_task_result(db, task_id, token, error="Task generation failed. Retry to try again.")
                submit_next()
        finish_run(db, active_run_id, token)
    except Exception as exc:
        if active_run_id is None:
            raise
        db.rollback()
        log_ai_error(exc)
        fail_run(db, active_run_id, token,
                 "Task execution stopped unexpectedly. Retry to try again.")
    finally:
        for future in futures:
            future.cancel()
        RUN_SLOTS.release()
    return db.scalars(select(Task).where(Task.chat_id == chat_id).order_by(Task.order, Task.id)
                      .execution_options(populate_existing=True)).all()
