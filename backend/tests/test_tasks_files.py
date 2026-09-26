import io
import unittest
from threading import Barrier
from unittest.mock import patch

import test_chats
from app.schemas.task import TaskPlan
from app.services.task_service import plan_tasks

tearDownModule = test_chats.tearDownModule


class TaskFileTests(unittest.TestCase):
    setUp = test_chats.ChatTests.setUp
    tearDown = test_chats.ChatTests.tearDown
    create = test_chats.ChatTests.create

    def test_queued_tasks_receive_same_plan_results_and_original_request(self):
        from app.models import Task, TaskRun
        chat_id = self.create()["id"]
        path = f"/api/chats/{chat_id}/tasks"
        unrelated = TaskRun(chat_id=chat_id, prompt="Unrelated private topic", status="completed")
        self.db.add(unrelated)
        self.db.flush()
        self.db.add(Task(chat_id=chat_id, run_id=unrelated.id, title="Other plan",
                         status="completed", result="UNRELATED_RESULT"))
        self.db.commit()
        goal = "Explain machine learning in detail with examples"
        plan = TaskPlan(tasks=[{"title": title, "description": "Collect useful facts"}
                               for title in ["Understand", "Research", "Examples", "Present"]])
        with patch("app.api.tasks.plan_tasks", return_value=plan):
            response = self.client.post(path + "/plan", json={"prompt": goal}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        run_id = response.json()[0]["run_id"]
        contexts = {}
        barrier = Barrier(3, timeout=5)
        def execute(title, description, **context):
            contexts[title] = context
            if title != "Present":
                barrier.wait()
            return f"Machine learning {title} result"
        with patch("app.api.tasks.execute_task", side_effect=execute):
            response = self.client.post(path + f"/run?run_id={run_id}", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(all(t["status"] == "completed" for t in response.json()))
        self.assertEqual(len(contexts), 4)
        for context in contexts.values():
            self.assertEqual(context["original_goal"], goal)
            self.assertNotIn("UNRELATED_RESULT", context["previous_results"])
        self.assertIn("Machine learning", contexts["Present"]["previous_results"])

    def test_parallel_execution_partial_failure_retry_and_ownership(self):
        path = f"/api/chats/{self.create()['id']}/tasks"
        plan = TaskPlan(tasks=[{"title": title, "description": title} for title in ["A", "B", "C"]])
        with patch("app.api.tasks.plan_tasks", return_value=plan):
            response = self.client.post(path + "/plan", json={"prompt": "Plan"}, headers=self.headers)
        self.assertEqual(response.status_code, 201, response.text)
        ids = [t["id"] for t in response.json()]
        self.assertEqual(self.client.post(path + "/run", headers=self.other_headers).status_code, 404)
        barrier = Barrier(3, timeout=5)
        def execute(title, description, **context):
            self.assertEqual(context["original_goal"], "Plan")
            barrier.wait()  # Fails unless three provider calls run concurrently.
            if title == "B":
                raise RuntimeError("private provider detail")
            return f"Result {title}"
        with patch("app.api.tasks.execute_task", side_effect=execute):
            response = self.client.post(path + "/run", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        rows = response.json()
        self.assertEqual([t["status"] for t in rows], ["completed", "failed", "completed"])
        self.assertNotIn("private provider detail", response.text)
        with patch("app.api.tasks.execute_task", return_value="Recovered") as execute:
            response = self.client.post(path + "/run", headers=self.headers)
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.kwargs["original_goal"], "Plan")
            self.assertIn("Result A", execute.call_args.kwargs["previous_results"])
            self.assertIn("Result C", execute.call_args.kwargs["previous_results"])
        self.assertEqual([t["id"] for t in response.json()], ids)
        self.assertEqual(response.json()[1]["result"], "Recovered")
        self.assertEqual(self.client.get(path, headers=self.headers).json(), response.json())
        self.assertEqual(self.client.post(path + "/run", headers=self.headers).status_code, 409)
        history = self.client.get(path.replace("/tasks", "/messages"), headers=self.headers).json()
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]["status"], "completed")
        self.assertIn("3 / 3 complete", history[-1]["content"])
        self.assertIn("Recovered", history[-1]["content"])
        self.assertIsNotNone(history[-1]["task_run_id"])

    def test_timeout_and_late_result_cannot_overwrite_retry(self):
        from threading import Event
        from app.services.task_lifecycle import save_task_result
        from app.models import Task
        path = f"/api/chats/{self.create()['id']}/tasks"
        task = self.client.post(path, json={"title": "Slow task"}, headers=self.headers).json()
        finished = Event()
        def slow(*args, **kwargs):
            finished.wait(2)
            return "Late response"
        try:
            with patch("app.services.task_lifecycle.RUN_TIMEOUT_SECONDS", .01), patch("app.api.tasks.execute_task", side_effect=slow):
                response = self.client.post(path + "/run", headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()[0]["status"], "failed")
            self.assertIn("timed out", response.json()[0]["error"])
            with patch("app.api.tasks.execute_task", return_value="Recovered"):
                retried = self.client.post(path + f"/{task['id']}/retry", headers=self.headers)
            self.assertEqual(retried.json()[0]["status"], "completed")
            self.assertFalse(save_task_result(self.db, task["id"], "old-token", result="Late"))
            self.assertEqual(self.db.get(Task, task["id"]).result, "Recovered")
        finally:
            finished.set()

    def test_cancel_and_restart_recovery(self):
        from datetime import datetime, timedelta
        from app.models import Message, Task, TaskRun
        chat = self.create()
        message = Message(chat_id=chat["id"], role="assistant", content="", status="generating", generation_token="attempt")
        self.db.add(message)
        self.db.flush()
        from app.core.database import utcnow
        run = TaskRun(chat_id=chat["id"], prompt="Work", status="running", generation_token="attempt",
                      deadline_at=utcnow() + timedelta(minutes=1), result_message_id=message.id)
        self.db.add(run)
        self.db.flush()
        task = Task(chat_id=chat["id"], run_id=run.id, title="Work", status="in_progress", generation_token="attempt")
        self.db.add(task)
        self.db.commit()
        path = f"/api/chats/{chat['id']}/tasks"
        self.assertEqual(self.client.post(path + "/cancel", headers=self.other_headers).status_code, 404)
        self.assertEqual(self.client.post(path + "/cancel", headers=self.headers).json()[0]["status"], "cancelled")
        self.assertEqual(self.db.get(TaskRun, run.id).status, "cancelled")
        task.status, task.generation_token = "in_progress", "restart"
        run.status, run.generation_token = "running", "restart"
        run.deadline_at = utcnow() - timedelta(seconds=1)
        message.status, message.generation_token = "generating", "restart"
        self.db.commit()
        self.assertEqual(self.client.get(path, headers=self.headers).json()[0]["status"], "failed")
        self.assertNotEqual(self.db.get(Message, message.id).status, "generating")

    def test_startup_and_periodic_recovery_interrupt_stale_work(self):
        from datetime import timedelta
        from app.models import Message, Task, TaskRun
        from app.services.task_lifecycle import recover_interrupted_work, utcnow
        chat_id = self.create()["id"]
        stale = Message(chat_id=chat_id, role="assistant", content="Partial",
                        status="generating", generation_token="stream-token",
                        created_at=utcnow() - timedelta(hours=1))
        fresh = Message(chat_id=chat_id, role="assistant", content="Active",
                        status="generating", generation_token="fresh-token")
        result = Message(chat_id=chat_id, role="assistant", content="",
                         status="generating", generation_token="run-token")
        self.db.add_all([stale, fresh, result])
        self.db.flush()
        task = Task(chat_id=chat_id, title="Interrupted", description="Work",
                    status="in_progress", progress=10, generation_token="run-token")
        orphan = Task(chat_id=chat_id, title="Orphan", description="Legacy work",
                      status="in_progress", progress=10, generation_token="orphan-token")
        self.db.add_all([task, orphan])
        self.db.flush()
        run = TaskRun(chat_id=chat_id, prompt="Work", status="running",
                      generation_token="run-token", deadline_at=utcnow() + timedelta(minutes=3),
                      result_message_id=result.id)
        self.db.add(run)
        self.db.flush()
        task.run_id = run.id
        self.db.commit()

        recover_interrupted_work(self.db)
        self.assertEqual(self.db.get(Message, stale.id).status, "interrupted")
        self.assertEqual(self.db.get(Message, fresh.id).status, "generating")
        self.assertEqual(self.db.get(Task, task.id).status, "in_progress")
        self.assertEqual(self.db.get(Task, orphan.id).status, "failed")
        self.assertIn("inconsistent", self.db.get(Task, orphan.id).error)

        recover_interrupted_work(self.db, startup=True)
        self.assertEqual(self.db.get(Message, fresh.id).status, "interrupted")
        self.assertEqual(self.db.get(Task, task.id).status, "failed")
        self.assertIn("server restart", self.db.get(Task, task.id).error)
        self.assertEqual(self.db.get(TaskRun, run.id).status, "failed")
        self.assertEqual(self.db.get(Message, result.id).status, "failed")

    def test_unexpected_executor_submission_failure_is_finalized(self):
        path = f"/api/chats/{self.create()['id']}/tasks"
        self.client.post(path, json={"title": "Executor failure"}, headers=self.headers)
        with patch("app.services.task_lifecycle.EXECUTOR.submit",
                   side_effect=RuntimeError("private executor detail")):
            response = self.client.post(path + "/run", headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()[0]["status"], "failed")
        self.assertIn("stopped unexpectedly", response.json()[0]["error"])
        self.assertNotIn("private executor detail", response.text)
        history = self.client.get(path.replace("/tasks", "/messages"), headers=self.headers).json()
        self.assertEqual(history[-1]["status"], "failed")

    def test_attachment_ownership_metadata_and_csv_analysis(self):
        from app.models import Attachment
        chat, other_chat = self.create(), self.create()
        uploaded = self.client.post("/api/files/extract", data={"chat_id": chat["id"]},
            files={"file": ("values.csv", b"name,value\nA,10\nB,20\nC,30")}, headers=self.headers)
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        attachment = uploaded.json()
        self.assertEqual(attachment["statistics"]["2: value"]["highest"], "30")
        self.assertEqual(attachment["statistics"]["2: value"]["lowest"], "10")
        self.assertEqual(attachment["statistics"]["2: value"]["average"], "20")
        stored = self.db.get(Attachment, attachment["id"])
        self.assertEqual(stored.user_id, self.users[0].id)
        self.assertEqual(len(stored.sha256), 64)
        self.assertEqual(self.client.get(f"/api/files?chat_id={chat['id']}", headers=self.other_headers).status_code, 404)
        self.assertEqual(len(self.client.get(f"/api/files?chat_id={chat['id']}", headers=self.headers).json()), 1)
        payload = {"content": "Analyze", "attachment_ids": [attachment["id"]]}
        self.assertEqual(self.client.post(f"/api/chats/{other_chat['id']}/messages", json=payload, headers=self.headers).status_code, 404)
        foreign_chat = self.client.post("/api/chats", json={"title": "Other user"}, headers=self.other_headers).json()
        self.assertEqual(self.client.post(f"/api/chats/{foreign_chat['id']}/messages", json=payload, headers=self.other_headers).status_code, 404)
        with patch("app.api.messages.generate_chat_response", return_value="Highest 30; average 20") as provider:
            response = self.client.post(f"/api/chats/{chat['id']}/messages", json=payload, headers=self.headers)
        self.assertEqual(response.status_code, 201)
        self.assertIn('"average": "20"', provider.call_args.args[0][-1].content)

    def test_invalid_plan_does_not_save_tasks(self):
        path = f"/api/chats/{self.create()['id']}/tasks"
        with patch("app.services.task_service.GeminiProvider") as provider:
            provider.return_value.generate.return_value = '{"tasks": []}'
            response = self.client.post(path + "/plan", json={"prompt": "Plan"}, headers=self.headers)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(self.client.get(path, headers=self.headers).json(), [])

    def test_file_formats_limits_and_auth(self):
        path = "/api/files/extract"
        self.assertEqual(self.client.post(path, files={"file": ("data.csv", b"x,y\n1,2")}).status_code, 401)
        for name, content in [("data.csv", b"x,y\n1,2"), ("note.txt", b"Hello"), ("note.md", b"# Hello")]:
            response = self.client.post(path, files={"file": (name, content)}, headers=self.headers)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["text"], content.decode())
        for name, content, code in [("bad.exe", b"data", 415), ("empty.txt", b" ", 422),
                                    ("bad.pdf", b"invalid", 422), ("long.txt", b"x" * 40001, 413),
                                    ("huge.txt", b"x" * (50 * 1024 * 1024 + 1), 413)]:
            self.assertEqual(self.client.post(path, files={"file": (name, content)}, headers=self.headers).status_code, code)
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
        writer = PdfWriter()
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        stream = DecodedStreamObject()
        stream.set_data(b"BT /F1 12 Tf 20 200 Td (Hello PDF) Tj ET")
        page[NameObject("/Contents")] = writer._add_object(stream)
        output = io.BytesIO()
        writer.write(output)
        response = self.client.post(path, files={"file": ("sample.pdf", output.getvalue())}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("Hello PDF", response.json()["text"])

    def test_chunked_upload_with_50mb_limit(self):
        """Test that files up to 50MB are accepted and chunked reading works."""
        path = "/api/files/extract"
        # Create a 20MB file to test chunking
        large_content = b"x" * (20 * 1024 * 1024)
        response = self.client.post(path, files={"file": ("large.txt", large_content)}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual(data["size_bytes"], 20 * 1024 * 1024)
        self.assertEqual(len(data["sha256"]), 64)  # SHA256 hex digest

    def test_upload_exceeds_50mb_limit(self):
        """Test that files over 50MB are rejected."""
        path = "/api/files/extract"
        oversized = b"x" * (50 * 1024 * 1024 + 1)
        response = self.client.post(path, files={"file": ("oversized.txt", oversized)}, headers=self.headers)
        self.assertEqual(response.status_code, 413)
        self.assertIn("50 MB", response.json()["detail"])

    def test_attachment_upload_status_fields(self):
        """Test that new attachment fields are populated correctly."""
        from app.models import Attachment
        path = "/api/files/extract"
        response = self.client.post(path, files={"file": ("test.txt", b"Hello World")}, headers=self.headers)
        self.assertEqual(response.status_code, 200, response.text)
        
        attachment = self.db.get(Attachment, response.json()["id"])
        self.assertEqual(attachment.upload_status, "completed")
        self.assertEqual(attachment.processing_status, "completed")
        self.assertIsNone(attachment.storage_key)  # Not set until object storage

    def test_presign_endpoint_placeholder(self):
        """Test that presign endpoint exists and returns placeholder."""
        path = "/api/uploads/presign"
        response = self.client.post(
            path,
            data={"chat_id": self.create()["id"], "filename": "test.pdf", "file_size": 1024},
            headers=self.headers
        )
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertIn("upload_url", data)
        self.assertIn("storage_key", data)
        self.assertIn("expiry", data)

    def test_complete_endpoint_not_implemented(self):
        """Test that complete endpoint returns 501 Not Implemented."""
        path = "/api/uploads/complete"
        response = self.client.post(
            path,
            data={
                "chat_id": self.create()["id"],
                "filename": "test.pdf",
                "file_size": 1024,
                "storage_key": "uploads/test.pdf"
            },
            headers=self.headers
        )
        self.assertEqual(response.status_code, 501)

    def test_file_list_includes_attachment_metadata(self):
        """Test that file listing returns upload/processing status."""
        path = "/api/files/extract"
        chat = self.create()
        response = self.client.post(
            path,
            data={"chat_id": chat["id"]},
            files={"file": ("metadata.csv", b"a,b\n1,2")},
            headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        
        list_response = self.client.get(f"/api/files?chat_id={chat['id']}", headers=self.headers)
        self.assertEqual(list_response.status_code, 200)
        files = list_response.json()
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["filename"], "metadata.csv")


class PlannerTests(unittest.TestCase):
    def test_csv_statistics_include_negative_values_and_ignore_blanks(self):
        from app.services.attachments import csv_statistics
        stats = csv_statistics("name,value\nA,-2.5\nB,\nC,7.5")
        self.assertEqual(stats, {"2: value": {"count": 2, "highest": "7.5",
                         "lowest": "-2.5", "average": "2.5", "total": "5.0"}})

    def test_executor_prompt_keeps_original_goal_and_completed_results(self):
        from app.services.task_service import execute_task
        with patch("app.services.task_service.GeminiProvider") as provider:
            provider.return_value.generate.return_value = "Machine learning research"
            result = execute_task("Research the best answer", "Collect facts",
                original_goal="Explain machine learning in detail with examples",
                previous_results="Understand: cover supervised and unsupervised learning")
            prompt = provider.return_value.generate.call_args.args[0]
            self.assertIn("Explain machine learning in detail with examples", prompt)
            self.assertIn("Research the best answer", prompt)
            self.assertIn("Collect facts", prompt)
            self.assertIn("Understand: cover supervised and unsupervised learning", prompt)
            self.assertIn("Do not ask the user to provide the topic again", prompt)
            self.assertEqual(result, "Machine learning research")

    def test_fenced_json_and_task_limit(self):
        with patch("app.services.task_service.GeminiProvider") as provider:
            provider.return_value.generate.return_value = '```json\n{"tasks":[{"title":"A","description":"Do A"}]}\n```'
            self.assertEqual(plan_tasks("request").tasks[0].title, "A")
            provider.return_value.generate.return_value = "not json"
            with self.assertRaises(ValueError):
                plan_tasks("request")
