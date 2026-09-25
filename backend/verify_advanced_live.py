"""Opt-in real Gemini workflow checks; all verification DB rows roll back."""
import io
import json
from pathlib import Path
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from app.main import app
from app.core.database import get_db, get_engine
from app.core.security import create_access_token, hash_password
from app.models import User


def sample_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=600)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 550 Td (Project Solar. Budget: 5000. Duration: 7 days.) Tj 0 -20 Td (Team: 3 people. Goal: reduce electricity use. Review on Friday.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


report = {"files": []}
with get_engine().connect() as connection:
    transaction = connection.begin()
    with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
        def override_db():
            yield db
        app.dependency_overrides[get_db] = override_db
        try:
            user = User(name="Advanced verification", email=f"advanced-{uuid4().hex}@example.com", password_hash=hash_password(uuid4().hex))
            db.add(user)
            db.flush()
            headers = {"Authorization": "Bearer " + create_access_token(user.id)}
            with TestClient(app) as client:
                chat = client.post("/api/chats", json={"title": "Advanced task verification"}, headers=headers).json()
                path = f"/api/chats/{chat['id']}"
                prompt = "Compare Java and Python, give 5 advantages of each, make a 7-day study plan, and suggest 3 beginner projects."
                plan = client.post(path + "/tasks/plan", json={"prompt": prompt}, headers=headers)
                plan.raise_for_status()
                print(f"Planned {len(plan.json())} independent tasks", flush=True)
                run = client.post(path + "/tasks/run", headers=headers)
                run.raise_for_status()
                history = client.get(path + "/messages", headers=headers).json()
                report["tasks"] = run.json()
                report["combined_answer"] = history[-1]
                report["single_answer"] = len(history) == 2 and history[0]["content"] == prompt
                print("Task statuses:", [t["status"] for t in run.json()], "Final:", history[-1]["status"], flush=True)
                samples = [
                    ("brief.pdf", sample_pdf(), "Summarize this document and give me 5 important points."),
                    ("values.csv", b"item,value\nA,10\nB,50\nC,90", "Find the highest value, calculate the average and summarize the data."),
                    ("brief.txt", b"The library opens at 9 AM and closes at 6 PM. Members can borrow five books for two weeks. Renewals are available online.", "Summarize this file."),
                    ("notes.md", b"# Launch\n- Test the app\n- Fix bugs\n- Deploy on Friday", "Summarize this file."),
                ]
                for filename, content, question in samples:
                    file_chat = client.post("/api/chats", json={"title": filename}, headers=headers).json()
                    file_path = f"/api/chats/{file_chat['id']}"
                    upload = client.post("/api/files/extract", data={"chat_id": file_chat["id"]}, files={"file": (filename, content)}, headers=headers)
                    upload.raise_for_status()
                    response = client.post(file_path + "/messages/stream", json={"content": question, "attachment_ids": [upload.json()["id"]]}, headers=headers)
                    response.raise_for_status()
                    saved = client.get(file_path + "/messages", headers=headers).json()
                    metadata = client.get(f"/api/files?chat_id={file_chat['id']}", headers=headers).json()
                    report["files"].append({"filename": filename, "metadata_saved": len(metadata) == 1,
                                            "answer": saved[-1], "statistics": upload.json()["statistics"]})
                    print(filename, saved[-1]["status"], flush=True)
                target = Path(__file__).resolve().parents[1] / ".local/advanced-live-validation.json"
                target.write_text(json.dumps(report, indent=2), encoding="utf-8")
                assert report["single_answer"]
                assert all(t["status"] == "completed" for t in report["tasks"])
                assert report["combined_answer"]["status"] == "completed"
                assert all(item["answer"]["status"] == "completed" and item["metadata_saved"] for item in report["files"])
                csv_answer = report["files"][1]["answer"]["content"]
                assert "90" in csv_answer and "50" in csv_answer
        finally:
            app.dependency_overrides.pop(get_db, None)
    transaction.rollback()
print("Advanced workflow verification passed; test rows rolled back.", flush=True)
