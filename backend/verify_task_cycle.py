"""Real HTTP/provider check of planning, progress, aggregation and history."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import time
from uuid import uuid4

import httpx
from sqlalchemy.orm import Session
from app.core.database import get_engine
from app.models import User


def main():
    email, password = f"cycle-{uuid4().hex}@example.com", uuid4().hex
    user_id = None
    base = "http://127.0.0.1:8001"
    with httpx.Client(base_url=base, timeout=240) as client:
        try:
            response = client.post("/api/auth/register", json={"name": "Pipeline verification", "email": email, "password": password})
            response.raise_for_status()
            user_id = response.json()["id"]
            response = client.post("/api/auth/login", json={"email": email, "password": password})
            response.raise_for_status()
            headers = {"Authorization": "Bearer " + response.json()["access_token"]}
            chat = client.post("/api/chats", json={"title": "Ordered pipeline verification"}, headers=headers)
            chat.raise_for_status()
            path = f"/api/chats/{chat.json()['id']}"
            prompt = "Compare Python and Java, give me 5 advantages and disadvantages of each, create a 7-day learning plan, and suggest 3 beginner projects."
            plan = client.post(path + "/tasks/plan", json={"prompt": prompt}, headers=headers)
            plan.raise_for_status()
            print("Plan:", [task["status"] for task in plan.json()], flush=True)
            states = []
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(httpx.post, base + path + "/tasks/run", headers=headers, timeout=240)
                while not future.done():
                    tasks = client.get(path + "/tasks", headers=headers)
                    tasks.raise_for_status()
                    current = [t["status"] for t in tasks.json()]
                    if not states or states[-1] != current:
                        states.append(current)
                        print("Progress:", current, flush=True)
                    time.sleep(.5)
                result = future.result()
            result.raise_for_status()
            history = client.get(path + "/messages", headers=headers).json()
            # A separate connection simulates a fresh history request after reload.
            refreshed = httpx.get(base + path + "/messages", headers=headers).json()
            refreshed_tasks = httpx.get(base + path + "/tasks", headers=headers).json()
            report = {"prompt": prompt, "transitions": states, "tasks": result.json(),
                      "history": history, "history_matches": refreshed == history,
                      "tasks_match": refreshed_tasks == result.json()}
            target = Path(__file__).resolve().parents[1] / ".local/ordered-task-validation.json"
            target.write_text(json.dumps(report, indent=2), encoding="utf-8")
            assert all(t["status"] == "completed" for t in result.json())
            assert refreshed_tasks == result.json()
            assert len(history) == 2 and history[-1]["status"] == "completed"
            assert all(t["result"] in history[-1]["content"] for t in result.json())
            assert refreshed == history
            print(f"PASS: {len(result.json())} tasks completed; one combined answer saved; fresh history matches.", flush=True)
        finally:
            if user_id:
                with Session(get_engine()) as db:
                    user = db.get(User, user_id)
                    if user and user.email == email:
                        db.delete(user)
                        db.commit()


if __name__ == "__main__":
    main()
