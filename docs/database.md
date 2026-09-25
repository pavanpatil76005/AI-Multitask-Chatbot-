# Database

The application uses PostgreSQL through SQLAlchemy and Alembic. For production,
set a single `DATABASE_URL` (Neon or another managed PostgreSQL service). Local
development can continue to use the project-local server under `.local/`.

## Tables

| Table | Purpose | Important relationships/fields |
| --- | --- | --- |
| `users` | Authentication accounts | Unique `email`, Argon2 `password_hash` |
| `chats` | Conversation metadata | Belongs to user; pin/archive/search state |
| `messages` | User/assistant turns and task results | Belongs to chat; role, status, generation token |
| `tasks` | Individual work items | Belongs to chat/run; status, progress, result, error |
| `task_runs` | One multitask plan/execution lifecycle | Prompt, deadline, token, request/result messages |
| `attachments` | Extracted file metadata and text | Belongs to user and optional chat; SHA-256, size |
| `alembic_version` | Applied migration head | Managed by Alembic |

Foreign keys use cascading deletes for user/chat-owned data. Task and run states
are protected by database check constraints as well as Pydantic validation.

## Production connection

```text
DATABASE_URL=<copy the Neon pooled connection string here>
```

`backend/app/core/config.py` accepts either `DATABASE_URL` or the discrete
`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, and `DB_PASSWORD` settings.
`DATABASE_URL` takes precedence and is required in managed deployments.

Apply and verify migrations:

```powershell
cd backend
& ./.venv/Scripts/python.exe -m alembic upgrade head
& ./.venv/Scripts/python.exe -m alembic current
& ./.venv/Scripts/python.exe -m alembic check
```

The current head is `i405_legacy_failures`. The chain normalizes task state,
tracks generation start time for safe recovery, and classifies exact legacy
provider-failure placeholders.

## Local database

The local PostgreSQL data directory is `.local/pgdata`, which is ignored by Git.
Credentials belong only in `backend/.env`. Never commit that file.
