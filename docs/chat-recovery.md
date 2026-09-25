# Chat recovery

Implemented before the multitask planner:

- Persist the user once and reserve one assistant row as `generating` before contacting Gemini.
- Use existing bounded automatic retries and three-model fallback.
- Save empty failures as `failed`, with a clean message and Retry in the UI.
- Keep useful partial text as `interrupted`, with Retry.
- Retry the same assistant ID using only its preceding conversation, without inserting a user message.
- Show Thinking until text arrives; replace Send with Stop during generation.
- Stop uses AbortController and an authenticated stop endpoint. Partial text is saved.
- A private generation token prevents late chunks/completions from overwriting a new attempt.
- Provider iteration runs outside the event loop so Stop and other API requests remain responsive.

Endpoints:

```text
POST /api/chats/{chat_id}/messages/{message_id}/retry
POST /api/chats/{chat_id}/messages/{message_id}/stop
```

Retry returns SSE `started`, `chunk`, and `done` or `error` events. Started includes
canonical message IDs; terminal events include saved content and status. A retry
of a completed or currently generating response returns 409. Ownership failures
return 404. A chat permits one generating response at a time. Failures and
interrupted text are excluded from future prompts unless the row is successfully
regenerated. The original useful text is retained if a retry fails before output.

Stop immediately stops delivery and invalidates the attempt. An already-running
provider HTTP call may take until its timeout to exit; its late output is discarded.
A process crash can leave a `generating` row; the stop endpoint can mark it interrupted.

## Migration

The additive message generation-token migration is `b72f100c1020`, on the
`chat_recovery` branch. Run `alembic upgrade chat_recovery@head` from backend.
The pre-existing tasks migration is a separate pending branch because its table
was previously created outside Alembic. It was not stamped as applied. Reconcile
that branch before using a blanket `upgrade heads` or developing planner migrations.
No task planner was added. Existing manual task endpoints/panel remain, and automatic
placeholder task creation/progress on ordinary sends was removed.

## Checks

```powershell
# backend
./.venv/Scripts/python.exe -m compileall -q app tests
./.venv/Scripts/python.exe -m unittest discover -s tests -p "test_*.py"
# frontend
npm run build
```

29 backend tests pass, including failures before the first chunk, repeat failures,
retry row identity, ownership, concurrent/redundant retry rejection, preserved
partial answers, Stop and stale-attempt protection. Browser automation could not
start because the local browser runtime was unavailable; visual interaction checks
are not claimed. Live API checks are recorded in `.local/recovery-validation.json`.

Live verification passed: Stop before the first chunk, Retry with the same assistant ID and one user row, and all seven requested prompts. A new history request returned all 14 saved messages. Validation chat 222 is retained as "Recovery validation - September 25" for inspection. Frontend lint and the Next.js production build passed.
