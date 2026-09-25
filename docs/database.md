# Local PostgreSQL database

PostgreSQL 17.11 is installed from the existing Windows binary archive under
`.local/pgsql`. Database files are in `.local/pgdata`. The server listens only
on `127.0.0.1:5432`, uses SCRAM password authentication, and owns a database
named `ai_chatbot` with owner `postgres`. Alembic migration `63abf2568aaf` creates `users`, `chats`, and `messages`;
`alembic_version` tracks the applied revision.

Credentials are in `backend/.env`, which is ignored by Git. Do not commit it.
`backend/.env.example` lists the required settings without real credentials.

## Start after restarting Windows

Run from the project root in PowerShell:

```powershell
& ./.local/pgsql/bin/pg_ctl.exe -D ./.local/pgdata -l ./.local/postgresql.log -w start
```

This is a project-local server, not an automatically starting Windows service.

## Check the connection

```powershell
cd backend
& ./.venv/Scripts/python.exe -m app.core.database
```

With FastAPI running, open http://127.0.0.1:8000/health/database.
A successful response is HTTP 200 with `{"status":"ok","database":"connected"}`.
Connection failures return HTTP 503 without exposing credentials.
The existing home endpoint and Swagger `/docs` remain available.

## Stop PostgreSQL

From the project root:

```powershell
& ./.local/pgsql/bin/pg_ctl.exe -D ./.local/pgdata -m fast -w stop
```

## Optional pgAdmin connection

If pgAdmin is installed later, register a server using host `127.0.0.1`, port
`5432`, maintenance database `postgres`, username `postgres`, and the password
stored in `backend/.env`. Expand Databases to see `ai_chatbot`.

## Next stage

The User, Chat, and Message models and their relationships are implemented.
Authentication is implemented; see [authentication](authentication.md).
Chat and message APIs are implemented; see [chat API usage](chats.md).

## Migrations

From `backend`, use the project virtual environment:

```powershell
& ./.venv/Scripts/python.exe -m alembic upgrade head
& ./.venv/Scripts/python.exe -m alembic current
& ./.venv/Scripts/python.exe -m alembic check
```

Alembic reads the existing settings and `.env`; no credentials are stored in
`alembic.ini`. The application does not automatically create or migrate tables.
After changing models, generate and review a migration before applying it:

```powershell
& ./.venv/Scripts/python.exe -m alembic revision --autogenerate -m "describe schema change"
```

Verified against PostgreSQL: defaults, user/chat/message relationships, unique
email, foreign keys, orphan deletion, and ORM/database delete cascades. All
verification rows were rolled back. Schema comparison reported no differences.
See [Alembic autogeneration](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)
and [SQLAlchemy cascades](https://docs.sqlalchemy.org/en/20/orm/cascades.html).

References: [PostgreSQL Windows binaries](https://www.postgresql.org/download/windows/)
and [SQLAlchemy engines](https://docs.sqlalchemy.org/en/20/tutorial/engine.html).
