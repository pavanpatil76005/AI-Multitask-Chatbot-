"""Run the requested real-provider smoke test; retain its chat for browser review."""
import json
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.main import app
from app.core.database import get_engine
from app.core.security import create_access_token, hash_password
from app.models import User

questions = ["What is Python?", "What is 235 × 46?", "Explain black holes simply.",
             "Write a professional leave email.", "Compare Java and Python.",
             "Give me FastAPI interview questions.", "Explain machine learning with examples."]
with Session(get_engine()) as db:
    user = User(name="Live verification", email=f"verification-{uuid4().hex}@example.com", password_hash=hash_password(uuid4().hex))
    db.add(user)
    db.commit()
    token = create_access_token(user.id)
with TestClient(app) as client:
    headers = {"Authorization": f"Bearer {token}"}
    chat = client.post("/api/chats", json={"title": "Seven prompt verification"}, headers=headers).json()
    path = f"/api/chats/{chat['id']}/messages"
    results = []
    for question in questions:
        response = client.post(path + "/stream", json={"content": question}, headers=headers)
        rows = client.get(path, headers=headers).json()
        answer = rows[-1]
        result = {"question": question, "status": answer["status"], "answer": answer["content"]}
        results.append(result)
        print(question, answer["status"], flush=True)
    persisted = client.get(path, headers=headers).json()
    assert len(persisted) == 14
    report = {"chat_id": chat["id"], "history_matches": [m["content"] for m in persisted if m["role"] == "assistant"] == [r["answer"] for r in results], "results": results}
    destination = Path(__file__).resolve().parents[1] / ".local/current-live-validation.json"
    destination.parent.mkdir(exist_ok=True)
    with destination.open("w", encoding="utf-8") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
    assert report["history_matches"]
    assert all(result["status"] == "completed" for result in results), "One or more prompts failed; inspect the report"
    assert "10810" in results[1]["answer"].replace(",", ""), "Incorrect arithmetic response"
