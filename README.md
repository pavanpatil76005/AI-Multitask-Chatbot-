# AI Multitask Chatbot

Next.js frontend, FastAPI backend, PostgreSQL persistence, and Gemini responses.

Chat supports streamed answers, Thinking, Stop, failed/interrupted states, and retry
without duplicating the question. AI messages render GitHub-flavored Markdown.
Task Activity supports validated AI plans, parallel text generation, saved results,
cancelled/failed-task retry, timeout and restart recovery, and one combined answer.
Search, pin/archive, answer edit/regenerate, and PDF/CSV/TXT/Markdown analysis are
included.

## Start locally (PowerShell)

The bundled PostgreSQL database must be running. From the project root:

```powershell
& ./.local/pgsql/bin/pg_ctl.exe -D ./.local/pgdata -l ./.local/postgresql.log -w start
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\fastapi.exe dev app/main.py --port 8001
```

Database credentials, JWT secret, and Gemini settings belong in `backend/.env`.
Never include that file in source archives. See [database setup](docs/database.md).

In another terminal:

```powershell
cd frontend
npm ci
npm run dev
```

Open http://localhost:3000 and register or sign in.
API docs: http://127.0.0.1:8001/docs.
Database health: http://127.0.0.1:8001/health/database.

## Verify

```powershell
cd backend
.\.venv\Scripts\python.exe -m compileall app
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"
.\.venv\Scripts\python.exe -m alembic check
cd ../frontend
npm test
npm run build
npm run lint
npx tsc --noEmit --incremental false
```

Backend tests use the configured PostgreSQL database and roll back test rows.
To explicitly test the real provider (consumes Gemini quota), run
`python verify_live.py`, `python verify_tasks_live.py`, or the complete
`python verify_advanced_live.py` workflow from the activated backend environment.
The advanced workflow checks the three-task Java/Python request plus PDF, CSV, TXT,
and Markdown analysis; it rolls back all of its database rows. Reports are written
to `.local/`.

See [task and file usage](docs/tasks-and-files.md) and
[verification report](docs/implementation-verification.md).
