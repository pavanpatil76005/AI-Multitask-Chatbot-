"""Opt-in real Gemini task smoke test. All database test rows are rolled back."""
import json
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.core.database import get_db, get_engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models import User


with get_engine().connect() as connection:
    transaction = connection.begin()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        def override_db():
            yield db
        app.dependency_overrides[get_db] = override_db
        try:
            user = User(name="Task verification", email=f"tasks-{uuid4().hex}@example.com",
                        password_hash=hash_password(uuid4().hex))
            db.add(user)
            db.flush()
            headers = {"Authorization": "Bearer " + create_access_token(user.id)}
            with TestClient(app) as client:
                response = client.post("/api/chats", json={"title": "Task verification"}, headers=headers)
                response.raise_for_status()
                path = f"/api/chats/{response.json()['id']}/tasks"
                document = client.post("/api/files/extract", files={"file": ("sales.csv", b"month,sales\nJan,10\nFeb,20")}, headers=headers)
                document.raise_for_status()
                planned = client.post(path + "/plan", json={"prompt": "Create exactly two independent tasks: calculate total sales, and draft a one-sentence sales summary. Data:\n" + document.json()["text"]}, headers=headers)
                planned.raise_for_status()
                print(f"Planned {len(planned.json())} tasks", flush=True)
                run = client.post(path + "/run", headers=headers)
                run.raise_for_status()
                persisted = client.get(path, headers=headers).json()
                report = {"history_matches": persisted == run.json(), "tasks": persisted}
                destination = Path(__file__).resolve().parents[1] / ".local/task-live-validation.json"
                destination.parent.mkdir(exist_ok=True)
                destination.write_text(json.dumps(report, indent=2), encoding="utf-8")
                print([(task["title"], task["status"]) for task in persisted], flush=True)
                assert report["history_matches"]
                assert all(task["status"] == "completed" and task["result"] for task in persisted)
        finally:
            app.dependency_overrides.pop(get_db, None)
    transaction.rollback()
