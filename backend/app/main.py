import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.core.database import check_database_connection, get_db
from app.api.auth import router as auth_router
from app.api.chats import router as chats_router
from app.api.messages import router as messages_router
from app.api.tasks import router as tasks_router
from app.api.files import router as files_router
from app.models.task import Task  # noqa: F401
from app.core.config import get_settings

from app.services.task_lifecycle import recover_interrupted_work

logger = logging.getLogger(__name__)
RECOVERY_INTERVAL_SECONDS = 30


def recover_persisted_work(application: FastAPI, *, startup=False):
    dependency = application.dependency_overrides.get(get_db, get_db)
    db_context = dependency()
    db = next(db_context)
    try:
        return recover_interrupted_work(db, startup=startup)
    finally:
        next(db_context, None)


async def recovery_loop(application: FastAPI):
    while True:
        await asyncio.sleep(RECOVERY_INTERVAL_SECONDS)
        try:
            await asyncio.to_thread(recover_persisted_work, application)
        except Exception:
            logger.exception("Periodic generation recovery failed")


@asynccontextmanager
async def lifespan(application: FastAPI):
    # In-process workers do not survive a restart, so persisted work is stale here.
    try:
        await asyncio.to_thread(recover_persisted_work, application, startup=True)
    except SQLAlchemyError:
        logger.exception("Startup generation recovery could not reach PostgreSQL")
    recovery_task = None if application.dependency_overrides else asyncio.create_task(recovery_loop(application))
    try:
        yield
    finally:
        if recovery_task is not None:
            recovery_task.cancel()
            with suppress(asyncio.CancelledError):
                await recovery_task



app = FastAPI(
    title="AI Multitask Chatbot API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(dict.fromkeys([
        *get_settings().cors_origins,
        "http://localhost:3000",
        "https://ai-multitask-chatbot.vercel.app",
    ])),
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(chats_router)
app.include_router(messages_router)
app.include_router(tasks_router)
app.include_router(files_router)



@app.get("/")
def home():
    return {"message": "AI Multitask Chatbot Backend is running"}


@app.get("/health/database")
def database_health():
    try:
        connected = check_database_connection()
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Database unavailable") from None
    if not connected:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"status": "ok", "database": "connected"}
