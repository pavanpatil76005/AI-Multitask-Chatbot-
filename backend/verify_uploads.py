"""Real HTTP extraction/analysis checks; only temporary test data is removed."""
import io
import json
from pathlib import Path
from uuid import uuid4
import httpx
from sqlalchemy.orm import Session
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from app.core.database import get_engine
from app.models import User


def sample_pdf():
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=600)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 550 Td (Project Solar. Budget: 5000. Duration: 7 days.) Tj 0 -20 Td (Team: 3 people. Goal: reduce electricity use. Review on Friday.) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    target = io.BytesIO()
    writer.write(target)
    return target.getvalue()


def main():
    email, password = f"uploads-{uuid4().hex}@example.com", uuid4().hex
    user_id = None
    report = []
    with httpx.Client(base_url="http://127.0.0.1:8001", timeout=600) as client:
        try:
            registered = client.post("/api/auth/register", json={"name": "Upload verification", "email": email, "password": password})
            registered.raise_for_status()
            user_id = registered.json()["id"]
            login = client.post("/api/auth/login", json={"email": email, "password": password})
            login.raise_for_status()
            headers = {"Authorization": "Bearer " + login.json()["access_token"]}
            samples = [
                ("brief.pdf", sample_pdf(), "Summarize this PDF, give me the 5 most important points, and create 5 questions from it.", "Project Solar"),
                ("values.csv", b"item,value\nA,10\nB,50\nC,90", "Analyze this CSV, calculate the average, find the highest and lowest values, identify patterns, and summarize the results.", "A,10"),
                ("brief.txt", b"The library opens at 9 AM and closes at 6 PM. Members may borrow five books for two weeks. Online renewals are available.", "Summarize this file, extract the important information, and answer: how many books may a member borrow?", "five books"),
                ("notes.md", b"# Launch\n- Test the app on Monday\n- Fix bugs on Tuesday\n- Deploy on Friday", "Summarize this file, extract important information, and answer: what day is deployment?", "Deploy on Friday"),
            ]
            for filename, content, prompt, marker in samples:
                created = client.post("/api/chats", json={"title": filename}, headers=headers)
                created.raise_for_status()
                chat_id = created.json()["id"]
                path = f"/api/chats/{chat_id}"
                uploaded = client.post("/api/files/extract", data={"chat_id": chat_id}, files={"file": (filename, content)}, headers=headers)
                uploaded.raise_for_status()
                assert marker in uploaded.json()["text"]
                response = client.post(path + "/messages/stream", json={"content": prompt, "attachment_ids": [uploaded.json()["id"]]}, headers=headers)
                response.raise_for_status()
                rows = client.get(path + "/messages", headers=headers).json()
                metadata = client.get(f"/api/files?chat_id={chat_id}", headers=headers).json()
                report.append({"filename": filename, "metadata": metadata, "statistics": uploaded.json()["statistics"], "messages": rows})
                target = Path(__file__).resolve().parents[1] / ".local/ordered-upload-validation.json"
                target.write_text(json.dumps(report, indent=2), encoding="utf-8")
                assert marker in rows[0]["content"]
                assert rows[-1]["status"] == "completed", f"{filename} generation failed"
                fresh = httpx.get("http://127.0.0.1:8001" + path + "/messages", headers=headers).json()
                assert fresh == rows
                assert len(metadata) == 1 and metadata[0]["size_bytes"] == len(content)
                if filename.endswith(".csv"):
                    assert uploaded.json()["statistics"]["2: value"]["highest"] == "90"
                    assert uploaded.json()["statistics"]["2: value"]["lowest"] == "10"
                    assert uploaded.json()["statistics"]["2: value"]["average"] == "50"
                    assert "90" in rows[-1]["content"] and "50" in rows[-1]["content"]
                    assert "10" in rows[-1]["content"]
                elif filename.endswith(".pdf"):
                    assert "solar" in rows[-1]["content"].lower()
                    assert "5,000" in rows[-1]["content"] or "5000" in rows[-1]["content"]
                    assert rows[-1]["content"].count("?") >= 5
                elif filename.endswith(".txt"):
                    assert "five" in rows[-1]["content"].lower() or "5" in rows[-1]["content"]
                else:
                    assert "friday" in rows[-1]["content"].lower()
                print(filename, "PASS: content extracted, AI answer completed, metadata/history saved", flush=True)
        finally:
            if user_id:
                with Session(get_engine()) as db:
                    user = db.get(User, user_id)
                    if user and user.email == email:
                        db.delete(user)
                        db.commit()


if __name__ == "__main__":
    main()
