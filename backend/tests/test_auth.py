"""PostgreSQL integration tests; all test data is rolled back."""
from datetime import datetime, timedelta, timezone
import unittest
from uuid import uuid4

import jwt
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db, get_engine
from app.core.security import verify_password
from app.main import app
from app.models import User


def tearDownModule():
    get_engine().dispose()


class AuthenticationTests(unittest.TestCase):
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
        self.email = f"auth-{uuid4().hex}@example.com"
        self.password = "TestPassword123!"

    def tearDown(self):
        self.client.close()
        app.dependency_overrides.pop(get_db, None)
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def register(self):
        response = self.client.post("/api/auth/register", json={
            "name": " Pavan ", "email": f" {self.email.upper()} ", "password": self.password,
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def login(self):
        response = self.client.post("/api/auth/login", json={
            "email": self.email, "password": self.password,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["token_type"], "bearer")
        return response.json()["access_token"]

    def test_register_login_me_and_hash(self):
        user = self.register()
        self.assertEqual(set(user), {"id", "name", "email", "is_active"})
        self.assertEqual(user["name"], "Pavan")
        self.assertEqual(user["email"], self.email)
        stored = self.db.scalar(select(User).where(User.email == self.email))
        self.assertTrue(stored.password_hash.startswith("$argon2"))
        self.assertTrue(verify_password(self.password, stored.password_hash))
        token = self.login()
        payload = jwt.decode(token, get_settings().secret_key.get_secret_value(), algorithms=["HS256"])
        self.assertEqual(payload["sub"], str(user["id"]))
        self.assertEqual(payload["exp"] - payload["iat"], get_settings().access_token_expire_minutes * 60)
        response = self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), user)

    def test_duplicate_email_is_normalized(self):
        self.register()
        response = self.client.post("/api/auth/register", json={
            "name": "Duplicate", "email": f" {self.email.upper()} ", "password": self.password,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "Email already registered"})

    def test_wrong_password_and_unknown_email(self):
        self.register()
        for email, password in [(self.email, "wrong-password"), ("missing@example.com", self.password)]:
            response = self.client.post("/api/auth/login", json={"email": email, "password": password})
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json(), {"detail": "Invalid email or password"})

    def test_invalid_tokens(self):
        user = self.register()
        key = get_settings().secret_key.get_secret_value()
        future = datetime.now(timezone.utc) + timedelta(minutes=5)
        payloads = [
            {"sub": str(user["id"]), "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
            {"sub": str(user["id"])}, {"exp": future},
            {"sub": "not-an-id", "exp": future},
            {"sub": "9" * 100, "exp": future},
            {"sub": "2147483647", "exp": future},
        ]
        tokens = ["malformed"] + [jwt.encode(p, key, algorithm="HS256") for p in payloads]
        tokens.append(jwt.encode({"sub": str(user["id"]), "exp": future}, "wrong-key-" * 8, algorithm="HS256"))
        tokens.append(jwt.encode({"sub": str(user["id"]), "exp": future}, key, algorithm="HS384"))
        headers_list = [{}, {"Authorization": "Basic invalid"}]
        headers_list += [{"Authorization": f"Bearer {token}"} for token in tokens]
        for headers in headers_list:
            with self.subTest(headers_present=bool(headers)):
                response = self.client.get("/api/auth/me", headers=headers)
                self.assertEqual(response.status_code, 401, response.text)
                self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_inactive_and_deleted_user(self):
        user = self.register()
        token = self.login()
        stored = self.db.get(User, user["id"])
        stored.is_active = False
        self.db.commit()
        response = self.client.post("/api/auth/login", json={"email": self.email, "password": self.password})
        self.assertEqual(response.status_code, 401)
        headers = {"Authorization": f"Bearer {token}"}
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)
        self.db.delete(stored)
        self.db.commit()
        self.assertEqual(self.client.get("/api/auth/me", headers=headers).status_code, 401)

    def test_input_validation_and_existing_endpoints(self):
        valid = {"name": "Pavan", "email": self.email, "password": self.password}
        for change in [{"name": "   "}, {"name": "x" * 101}, {"email": "invalid"}, {"password": "short"}]:
            response = self.client.post("/api/auth/register", json=valid | change)
            self.assertEqual(response.status_code, 422)
        self.assertEqual(self.client.get("/").status_code, 200)
        self.assertEqual(self.client.get("/health/database").status_code, 200)
        self.assertEqual(self.client.get("/docs").status_code, 200)
        schema = self.client.get("/openapi.json").json()
        for path in ("/api/auth/register", "/api/auth/login", "/api/auth/me"):
            self.assertIn(path, schema["paths"])
        self.assertTrue(schema["paths"]["/api/auth/me"]["get"]["security"])


if __name__ == "__main__":
    unittest.main()
