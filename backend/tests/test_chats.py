"""Chat/message integration tests against PostgreSQL; test data is rolled back."""
from datetime import datetime, timedelta
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.gemini_provider import GeminiProvider
from app.core.database import get_db, get_engine
from app.core.security import create_access_token, hash_password
from app.main import app
from app.models import Chat, Message, User


def tearDownModule():
    get_engine().dispose()


class ChatTests(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        get_engine().dispose()

    def setUp(self):
        self.connection = get_engine().connect()
        self.transaction = self.connection.begin()
        self.db = Session(bind=self.connection, join_transaction_mode="create_savepoint")
        def override_db():
            yield self.db
        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        hashed = hash_password("TestPassword123!")
        self.users = [User(name="Chat test", email=f"chat-{uuid4().hex}@example.com", password_hash=hashed) for _ in range(2)]
        self.db.add_all(self.users)
        self.db.flush()
        self.headers = {"Authorization": "Bearer " + create_access_token(self.users[0].id)}
        self.other_headers = {"Authorization": "Bearer " + create_access_token(self.users[1].id)}

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def create(self, payload=None):
        response = self.client.post("/api/chats", json=payload or {}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_complete_flow_and_delete_cascade(self):
        chat = self.create({"title": "Python Learning", "user_id": self.users[1].id})
        self.assertEqual(chat["user_id"], self.users[0].id)
        path = f"/api/chats/{chat['id']}"
        response = self.client.get("/api/chats", headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertIn(chat, response.json())
        self.assertEqual(self.client.get(path, headers=self.headers).json(), chat)
        renamed = self.client.patch(path, json={"title": "Inheritance"}, headers=self.headers)
        self.assertEqual(renamed.status_code, 200)
        self.assertEqual(renamed.json()["title"], "Inheritance")
        self.assertEqual(self.client.get(path + "/messages", headers=self.headers).json(), [])
        content = "Explain Python inheritance\n  preserve this formatting"
        with patch("app.api.messages.generate_chat_response", return_value="42"):
            response = self.client.post(path + "/messages", json={"content": content, "role": "system"}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        messages = response.json()
        self.assertEqual([m["role"] for m in messages], ["user", "assistant"])
        self.assertEqual([m["content"] for m in messages], [content, "42"])
        self.assertTrue(all(m["chat_id"] == chat["id"] and m["status"] == "completed" for m in messages))
        self.assertEqual(self.client.get(path + "/messages", headers=self.headers).json(), messages)
        response = self.client.delete(path, headers=self.headers)
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get(path, headers=self.headers).status_code, 404)
        self.assertEqual(self.client.get(path + "/messages", headers=self.headers).status_code, 404)
        self.assertEqual(self.db.scalars(select(Message).where(Message.chat_id == chat["id"])).all(), [])

    def test_other_user_cannot_access_chat_or_messages(self):
        chat = self.create()
        path = f"/api/chats/{chat['id']}"
        self.assertEqual(self.client.get("/api/chats", headers=self.other_headers).json(), [])
        for method, url, data in [("GET", path, None), ("PATCH", path, {"title": "stolen"}),
                                  ("DELETE", path, None), ("GET", path + "/messages", None),
                                  ("POST", path + "/messages", {"content": "unauthorized"})]:
            response = self.client.request(method, url, json=data, headers=self.other_headers)
            self.assertEqual(response.status_code, 404, response.text)
            self.assertEqual(response.json(), {"detail": "Chat not found"})
        self.assertEqual(self.client.get(path, headers=self.headers).json()["title"], "New Chat")
        self.assertEqual(self.client.get(path + "/messages", headers=self.headers).json(), [])

    def test_streaming_message_emits_chunks_and_persists_response(self):
        chat = self.create({"title": "New Chat"})
        path = f"/api/chats/{chat['id']}/messages/stream"
        with patch("app.api.messages.generate_chat_response_stream", return_value=iter(["Hello ", "there!"])):
            response = self.client.post(path, json={"content": "Test stream"}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/event-stream", response.headers.get("content-type", ""))
        self.assertIn("no-transform", response.headers.get("cache-control", ""))
        self.assertEqual(response.headers.get("x-accel-buffering"), "no")
        self.assertIn("Hello", response.text)
        self.assertIn("there!", response.text)
        persisted = self.client.get(f"/api/chats/{chat['id']}/messages", headers=self.headers)
        self.assertEqual(persisted.status_code, 200)
        self.assertEqual(persisted.json()[-1]["content"], "Hello there!")

    def test_partial_stream_failure_is_error_not_completed_reply(self):
        chat = self.create()
        def partial():
            yield "Partial reply"
            raise RuntimeError("PRIVATE_ERROR_DETAIL")
        with patch("app.api.messages.generate_chat_response_stream", return_value=partial()):
            response = self.client.post(f"/api/chats/{chat['id']}/messages/stream", json={"content": "test"}, headers=self.headers)
        self.assertIn("event: error", response.text)
        self.assertNotIn("event: done", response.text)
        self.assertNotIn("PRIVATE_ERROR_DETAIL", response.text)
        persisted = self.client.get(f"/api/chats/{chat['id']}/messages", headers=self.headers).json()
        self.assertEqual(len(persisted), 2)
        self.assertEqual(persisted[-1]["content"], "Partial reply")
        self.assertEqual(persisted[-1]["status"], "interrupted")

    def test_task_workflow_creates_lists_and_updates(self):
        chat = self.create({"title": "Project plan"})
        path = f"/api/chats/{chat['id']}/tasks"

        create_response = self.client.post(
            path,
            json={"title": "Research Python", "status": "pending", "order": 1},
            headers=self.headers,
        )
        self.assertEqual(create_response.status_code, 201, create_response.text)
        task = create_response.json()
        self.assertEqual(task["title"], "Research Python")
        self.assertEqual(task["status"], "pending")

        listed = self.client.get(path, headers=self.headers)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()[0]["id"], task["id"])

        updated = self.client.patch(
            f"{path}/{task['id']}",
            json={"status": " COMPLETED ", "progress": 100},
            headers=self.headers,
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()["status"], "completed")
        self.assertEqual(updated.json()["progress"], 100)
        self.assertEqual(self.client.patch(
            f"{path}/{task['id']}", json={"status": "in_progress"}, headers=self.headers,
        ).status_code, 409)
        cancelled = self.client.patch(
            f"{path}/{task['id']}", json={"status": "cancelled"}, headers=self.headers,
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.text)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        self.assertEqual(self.client.patch(
            f"{path}/{task['id']}", json={"status": "done"}, headers=self.headers,
        ).status_code, 422)

    def test_failed_response_retry_reuses_both_rows(self):
        chat = self.create()
        path = f"/api/chats/{chat['id']}/messages"
        with patch("app.api.messages.generate_chat_response_stream", side_effect=RuntimeError("private failure")):
            response = self.client.post(path + "/stream", json={"content": "Explain Python"}, headers=self.headers)
        self.assertIn("event: error", response.text)
        before = self.client.get(path, headers=self.headers).json()
        self.assertEqual(len(before), 2)
        self.assertEqual(before[-1]["status"], "failed")
        self.assertEqual(before[-1]["content"], "Response generation failed.")
        retry = path + f"/{before[-1]['id']}/retry"
        self.assertEqual(self.client.post(retry, headers=self.other_headers).status_code, 404)
        self.assertEqual(self.client.post(retry).status_code, 401)
        with patch("app.api.messages.generate_chat_response_stream", return_value=iter(["Python ", "is useful."])) as provider:
            response = self.client.post(retry, headers=self.headers)
            self.assertEqual([m.content for m in provider.call_args.args[0]], ["Explain Python"])
        self.assertIn("event: done", response.text)
        after = self.client.get(path, headers=self.headers).json()
        self.assertEqual([m["id"] for m in before], [m["id"] for m in after])
        self.assertEqual(after[-1]["content"], "Python is useful.")
        self.assertEqual(after[-1]["status"], "completed")
        self.assertEqual(self.client.post(retry, headers=self.headers).status_code, 409)

    def test_nonstream_failure_is_failed_and_retry_failure_keeps_partial(self):
        chat = self.create()
        path = f"/api/chats/{chat['id']}/messages"
        with patch("app.api.messages.generate_chat_response", side_effect=RuntimeError("private failure")):
            response = self.client.post(path, json={"content": "Question"}, headers=self.headers)
        self.assertEqual(response.json()[-1]["status"], "failed")
        message_id = response.json()[-1]["id"]
        message = self.db.get(Message, message_id)
        message.content, message.status = "Useful partial answer", "interrupted"
        self.db.commit()
        with patch("app.api.messages.generate_chat_response_stream", side_effect=RuntimeError("private failure")):
            self.client.post(path + f"/{message_id}/retry", headers=self.headers)
        rows = self.client.get(path, headers=self.headers).json()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["content"], "Useful partial answer")
        self.assertEqual(rows[-1]["status"], "interrupted")

    def test_stop_invalidates_old_generation_and_allows_retry(self):
        from app.api.messages import save_attempt
        chat = self.create()
        user = Message(chat_id=chat["id"], role="user", content="Question", status="completed")
        self.db.add(user)
        self.db.flush()
        assistant = Message(chat_id=chat["id"], role="assistant", content="Partial", status="generating", generation_token="old")
        self.db.add(assistant)
        self.db.commit()
        message_id = assistant.id
        path = f"/api/chats/{chat['id']}/messages/{message_id}"
        self.assertEqual(self.client.post(path + "/retry", headers=self.headers).status_code, 409)
        self.assertEqual(self.client.post(path + "/stop", headers=self.other_headers).status_code, 404)
        response = self.client.post(path + "/stop", headers=self.headers)
        self.assertEqual(response.json()["status"], "interrupted")
        self.assertEqual(response.json()["content"], "Partial")
        self.assertFalse(save_attempt(self.db, message_id, "old", "stale output", "completed"))
        with patch("app.api.messages.generate_chat_response_stream", return_value=iter(["Recovered"])):
            self.assertIn("event: done", self.client.post(path + "/retry", headers=self.headers).text)
        self.assertFalse(save_attempt(self.db, message_id, "old", "stale output", "completed"))
        self.assertEqual(self.db.get(Message, message_id).content, "Recovered")

    def test_repeated_failure_remains_failed(self):
        path = f"/api/chats/{self.create()['id']}/messages"
        with patch("app.api.messages.generate_chat_response_stream", side_effect=RuntimeError("failure")):
            self.client.post(path + "/stream", json={"content": "Question"}, headers=self.headers)
            message = self.client.get(path, headers=self.headers).json()[-1]
            self.client.post(path + f"/{message['id']}/retry", headers=self.headers)
        rows = self.client.get(path, headers=self.headers).json()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["status"], "failed")

    def test_retry_of_old_message_gets_fresh_generation_deadline(self):
        from app.services.task_lifecycle import recover_interrupted_work, utcnow
        chat = self.create()
        self.db.add(Message(chat_id=chat["id"], role="user", content="Question", status="completed"))
        self.db.flush()
        assistant = Message(chat_id=chat["id"], role="assistant", content="", status="failed",
                            created_at=utcnow() - timedelta(days=3))
        self.db.add(assistant)
        self.db.commit()
        message_id = assistant.id
        def provider(_messages):
            recover_interrupted_work(self.db)
            self.assertEqual(self.db.get(Message, message_id).status, "generating")
            return iter(["Recovered"])
        with patch("app.api.messages.generate_chat_response_stream", side_effect=provider):
            response = self.client.post(f"/api/chats/{chat['id']}/messages/{message_id}/retry", headers=self.headers)
        self.assertIn("event: done", response.text)
        self.assertEqual(self.db.get(Message, message_id).status, "completed")

    def test_disconnect_preserves_partial_and_closes_provider(self):
        import asyncio
        from app.api.messages import new_messages, stream_attempt
        chat_id = self.create()["id"]
        user, assistant = new_messages(self.db, chat_id, "Question")
        message_id = assistant.id
        closed = []
        class Request:
            async def is_disconnected(self):
                return False
        def source(_messages):
            try:
                yield "Useful partial answer"
                yield " never requested"
            finally:
                closed.append(True)
        async def read_then_abort():
            response = stream_attempt(Request(), self.db, chat_id, assistant, user)
            iterator = response.body_iterator
            self.assertIn("event: started", await anext(iterator))
            self.assertIn("Useful partial answer", await anext(iterator))
            await iterator.aclose()
        with patch("app.api.messages.generate_chat_response_stream", side_effect=source):
            asyncio.run(read_then_abort())
        saved = self.db.get(Message, message_id)
        self.assertEqual(saved.status, "interrupted")
        self.assertEqual(saved.content, "Useful partial answer")
        self.assertEqual(closed, [True])

    def test_all_routes_require_authentication(self):
        chat = self.create()
        path = f"/api/chats/{chat['id']}"
        for method, url, data in [("POST", "/api/chats", {}), ("GET", "/api/chats", None),
                                  ("GET", path, None), ("PATCH", path, {"title": "x"}),
                                  ("DELETE", path, None), ("GET", path + "/messages", None),
                                  ("POST", path + "/messages", {"content": "hello"})]:
            self.assertEqual(self.client.request(method, url, json=data).status_code, 401)

    def test_validation_and_missing_chat(self):
        chat = self.create()
        path = f"/api/chats/{chat['id']}"
        for title in ("", "   ", "x" * 256):
            self.assertEqual(self.client.post("/api/chats", json={"title": title}, headers=self.headers).status_code, 422)
            self.assertEqual(self.client.patch(path, json={"title": title}, headers=self.headers).status_code, 422)
        for content in ("", "  ", None):
            self.assertEqual(self.client.post(path + "/messages", json={"content": content}, headers=self.headers).status_code, 422)
        for bad_id in (0, -1, 2147483648, "abc"):
            self.assertEqual(self.client.get(f"/api/chats/{bad_id}", headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get("/api/chats/2147483647", headers=self.headers).status_code, 404)
        self.assertEqual(self.client.post("/api/chats/2147483647/messages", json={"content": "hello"}, headers=self.headers).status_code, 404)

    def test_activity_order_and_message_tie_order(self):
        first, second = self.create(), self.create()
        stored = self.db.get(Chat, first["id"])
        stored.updated_at = datetime.utcnow() - timedelta(days=1)
        self.db.commit()
        response = self.client.get("/api/chats", headers=self.headers)
        self.assertEqual(response.json()[0]["id"], second["id"])
        path = f"/api/chats/{first['id']}/messages"
        with patch("app.api.messages.generate_chat_response", return_value="Activity reply"):
            response = self.client.post(path, json={"content": "new activity"}, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.client.get("/api/chats", headers=self.headers).json()[0]["id"], first["id"])
        messages = self.db.scalars(select(Message).where(Message.chat_id == first["id"])).all()
        same_time = datetime.utcnow()
        for message in messages:
            message.created_at = same_time
        self.db.commit()
        response = self.client.get(path, headers=self.headers)
        self.assertEqual([m["role"] for m in response.json()], ["user", "assistant"])


if __name__ == "__main__":
    unittest.main()
