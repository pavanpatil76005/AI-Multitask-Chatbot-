import unittest
from unittest.mock import patch
import test_chats

tearDownModule = test_chats.tearDownModule


class ChatControlTests(unittest.TestCase):
    setUp = test_chats.ChatTests.setUp
    tearDown = test_chats.ChatTests.tearDown
    create = test_chats.ChatTests.create

    def test_delete_failed_response_preserves_question_and_checks_ownership(self):
        path = f"/api/chats/{self.create()['id']}/messages"
        with patch("app.api.messages.generate_chat_response", side_effect=RuntimeError("Unavailable")):
            self.client.post(path, json={"content": "Keep my question"}, headers=self.headers)
        rows = self.client.get(path, headers=self.headers).json()
        self.assertEqual(rows[-1]["status"], "failed")
        target = path + f"/{rows[-1]['id']}"
        self.assertEqual(self.client.delete(target, headers=self.other_headers).status_code, 404)
        self.assertEqual(self.client.delete(target).status_code, 401)
        response = self.client.delete(target, headers=self.headers)
        self.assertEqual(response.status_code, 204, response.text)
        self.assertEqual(response.content, b"")
        self.assertEqual(self.client.get(path, headers=self.headers).json(), rows[:1])
        self.assertEqual(self.client.delete(target, headers=self.headers).status_code, 404)

    def test_delete_rejects_success_partial_active_and_task_responses(self):
        from app.models import Message, TaskRun
        chat_id = self.create()["id"]
        path = f"/api/chats/{chat_id}/messages"
        for state in ("completed", "interrupted", "generating", "failed"):
            message = Message(chat_id=chat_id, role="assistant", content="Preserve", status=state)
            self.db.add(message)
            self.db.flush()
            if state == "failed":
                self.db.add(TaskRun(chat_id=chat_id, prompt="Plan", result_message_id=message.id))
            self.db.commit()
            response = self.client.delete(path + f"/{message.id}", headers=self.headers)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIsNotNone(self.db.get(Message, message.id))
            if state == "generating":
                message.status = "interrupted"
                self.db.commit()

    def test_legacy_failure_migration_is_exact_and_retry_keeps_question(self):
        from importlib import import_module
        from app.models import Message
        migration = import_module("migrations.versions.i405_legacy_failures")
        chat_id = self.create()["id"]
        failure = "I couldn\ufffdt generate a reply right now. Please try again in a moment."
        user = Message(chat_id=chat_id, role="user", content=failure, status="completed")
        assistant = Message(chat_id=chat_id, role="assistant", content=failure, status="completed")
        quoted = Message(chat_id=chat_id, role="assistant", content="Example: " + failure, status="completed")
        self.db.add_all([user, assistant, quoted])
        self.db.commit()
        with patch.object(migration.op, "execute", side_effect=self.db.execute):
            migration.upgrade()
            migration.upgrade()  # Idempotent; no ordinary answer gets classified.
        self.db.expire_all()
        self.assertEqual(assistant.status, "failed")
        self.assertEqual(user.status, "completed")
        self.assertEqual(quoted.status, "completed")
        with patch("app.api.messages.generate_chat_response_stream", return_value=iter(["Recovered"])):
            response = self.client.post(f"/api/chats/{chat_id}/messages/{assistant.id}/retry", headers=self.headers)
        self.assertIn("event: done", response.text)
        rows = self.client.get(f"/api/chats/{chat_id}/messages", headers=self.headers).json()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1]["content"], "Recovered")

    def test_search_pin_archive_and_ownership(self):
        first = self.create({"title": "Python study"})
        second = self.create({"title": "Java study"})
        path = f"/api/chats/{first['id']}"
        self.assertEqual(self.client.get("/api/chats?q=Python", headers=self.headers).json()[0]["id"], first["id"])
        self.assertEqual(self.client.get("/api/chats?q=Python", headers=self.other_headers).json(), [])
        self.assertEqual(self.client.patch(path, json={"is_pinned": True}, headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get("/api/chats", headers=self.headers).json()[0]["id"], first["id"])
        self.client.patch(path, json={"is_archived": True}, headers=self.headers)
        self.assertEqual([r["id"] for r in self.client.get("/api/chats", headers=self.headers).json()], [second["id"]])
        self.assertEqual(self.client.get("/api/chats?archived=true", headers=self.headers).json()[0]["id"], first["id"])
        self.client.patch(path, json={"is_archived": False}, headers=self.headers)
        with patch("app.api.messages.generate_chat_response", return_value="Unique searchable words"):
            self.client.post(path + "/messages", json={"content": "Question"}, headers=self.headers)
        self.assertEqual(self.client.get("/api/chats?q=searchable", headers=self.headers).json()[0]["id"], first["id"])

    def test_archive_search_literals_and_pin_persist_without_cross_user_access(self):
        chat = self.create({"title": "100% Python_notes"})
        other = self.create({"title": "Unrelated"})
        path = f"/api/chats/{chat['id']}"
        for change in ({"is_pinned": True}, {"is_archived": True}):
            self.assertEqual(self.client.patch(path, json=change, headers=self.other_headers).status_code, 404)
            self.assertEqual(self.client.patch(path, json=change, headers=self.headers).status_code, 200)
        self.db.expire_all()
        saved = self.client.get(path, headers=self.headers).json()
        self.assertTrue(saved["is_pinned"] and saved["is_archived"])
        for query in ("%", "_", "python"):
            rows = self.client.get("/api/chats", params={"q": query, "archived": True}, headers=self.headers).json()
            self.assertEqual([r["id"] for r in rows], [chat["id"]])
            self.assertEqual(self.client.get("/api/chats", params={"q": query, "archived": True}, headers=self.other_headers).json(), [])
        self.assertEqual(self.client.get("/api/chats", headers=self.headers).json()[0]["id"], other["id"])
        self.client.patch(path, json={"is_archived": False}, headers=self.headers)
        self.assertEqual(self.client.get("/api/chats", headers=self.headers).json()[0]["id"], chat["id"])
        self.client.patch(path, json={"is_pinned": False}, headers=self.headers)
        self.assertFalse(self.client.get(path, headers=self.headers).json()["is_pinned"])

    def test_edit_regenerate_preserve_rows(self):
        path = f"/api/chats/{self.create()['id']}/messages"
        with patch("app.api.messages.generate_chat_response", return_value="Original"):
            rows = self.client.post(path, json={"content": "Question"}, headers=self.headers).json()
        user_id, assistant_id = [row["id"] for row in rows]
        self.assertEqual(self.client.patch(path + f"/{assistant_id}", json={"content": "Edited"}, headers=self.other_headers).status_code, 404)
        response = self.client.patch(path + f"/{assistant_id}", json={"content": "Edited"}, headers=self.headers)
        self.assertEqual(response.json()["content"], "Edited")
        with patch("app.api.messages.generate_chat_response_stream", return_value=iter(["Regenerated"])):
            self.assertIn("event: done", self.client.post(path + f"/{assistant_id}/regenerate", headers=self.headers).text)
        with patch("app.api.messages.generate_chat_response_stream", return_value=iter(["New answer"])):
            response = self.client.post(path + f"/{user_id}/edit", json={"content": "New question"}, headers=self.headers)
            self.assertIn("event: done", response.text)
        saved = self.client.get(path, headers=self.headers).json()
        self.assertEqual([row["id"] for row in saved], [user_id, assistant_id])
        self.assertEqual([row["content"] for row in saved], ["New question", "New answer"])
