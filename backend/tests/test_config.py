import unittest

from pydantic import ValidationError

from app.core.config import Settings


class ProductionSettingsTests(unittest.TestCase):
    def test_neon_database_url_and_deployed_cors_origins(self):
        settings = Settings(
            _env_file=None,
            DATABASE_URL="postgresql://user:<password>@db.example/neon?sslmode=require",
            **{"SECRET_KEY": "x" * 32},
            CORS_ORIGINS="https://app.vercel.app, http://localhost:3000/",
        )
        self.assertEqual(settings.database_url.drivername, "postgresql+psycopg")
        self.assertEqual(settings.database_url.host, "db.example")
        self.assertEqual(dict(settings.database_url.query), {"sslmode": "require"})
        self.assertEqual(
            settings.cors_origins,
            ["https://app.vercel.app", "http://localhost:3000"],
        )

    def test_database_credentials_are_required_without_dotenv(self):
        with self.assertRaises(ValidationError):
            Settings(_env_file=None, SECRET_KEY="x" * 32)

    def test_non_postgresql_database_url_is_rejected(self):
        settings = Settings(
            _env_file=None,
            DATABASE_URL="mysql://user:<password>@db.example/app",
            **{"SECRET_KEY": "x" * 32},
        )
        with self.assertRaises(ValueError):
            _ = settings.database_url


if __name__ == "__main__":
    unittest.main()
