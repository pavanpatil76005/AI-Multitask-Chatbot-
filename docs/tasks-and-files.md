# Tasks and files

Create/select a chat. Enter a request in Task Activity and choose **Plan tasks**.
Inspect the generated tasks, then choose **Run pending / retry failed tasks**.
Alternatively, add a single task directly. Each run processes up to eight pending,
failed, or cancelled tasks, with at most three Gemini calls executing
simultaneously. Completed tasks are not rerun. Results and safe errors are stored
separately in PostgreSQL.

Individual task states are `pending`, `in_progress`, `completed`, `failed`, and
`cancelled`. Internal task-run records use their separate `pending`, `running`,
`completed`, `failed`, and `cancelled` states. API validation and PostgreSQL check
constraints enforce both sets. The UI displays task `in_progress` as
**IN_PROGRESS**. Failed and cancelled tasks expose a
**Retry** action. When every task in a plan is complete, the backend assembles one
assistant message containing the ordered task sections and saves it to PostgreSQL.
That aggregation is deterministic, so a temporary failure while displaying the
combined result cannot lose completed task outputs.

Runs have a persisted 180-second deadline. A periodic sweep expires overdue runs,
startup recovery marks work left by a terminated API process as failed/interrupted,
and late provider results are rejected with generation-token guards. Regular
answer streams left unfinished for 15 minutes are also made retryable. Orphaned or
inconsistent `in_progress` task rows are failed instead of being left in limbo.
Progress updates poll the API, including after reopening a chat with active tasks.

The planner produces independent, self-contained text tasks. It does not execute
generated code, browse the web, send email, or perform external actions. Tasks that
depend on each other's outputs need a future dependency-aware executor.

The runner executes inside one API process. Closing the page does not cancel the
request's worker, but terminating the process interrupts it; startup/periodic
recovery makes that work retryable. This is not a durable distributed job queue.
Run only one API process for this deployment unless external worker ownership and
queueing are added.

## Attachments

Use the attachment input below the conversation. Supported files:

- UTF-8 TXT, Markdown, and CSV.
- Unencrypted text PDFs, up to 50 pages. Scanned PDFs require OCR and are rejected
  if they contain no extractable text.

Limits: 5 MB per file, 40,000 extracted characters, one attachment per request.
The extracted text is included in the next message, task plan, or manually added
task. It is sent to the configured Gemini provider. Original file bytes are not
stored. Message text and generated task descriptions/results are persisted.
An attachment can be removed before sending, and user/chat ownership is checked
before an attachment can be used.

CSV extraction computes per-column count, highest, average, and total for fully
numeric columns before sending the data to Gemini.

## API

All endpoints require the existing Bearer token and enforce chat ownership.

| Endpoint | Purpose |
| --- | --- |
| `POST /api/chats/{id}/tasks/plan` | Validate and persist an AI plan from `{ "prompt": "..." }` |
| `POST /api/chats/{id}/tasks/run` | Execute one pending/failed/cancelled plan; return saved results |
| `POST /api/chats/{id}/tasks/{task}/retry` | Retry one failed or cancelled task |
| `POST /api/chats/{id}/tasks/cancel` | Cancel active work in the chat |
| `GET /api/chats/{id}/tasks` | Poll persisted statuses, results, and safe error messages |
| `POST /api/files/extract` | Multipart `file`; return filename and bounded extracted text |

For a fresh database, run `alembic upgrade head`. The migration chain ends at
`i405_legacy_failures`: `f1c2a4b6d8e0` installs the state constraints,
`g203_task_in_progress` exposes the public task state, `h304_generation_start`
tracks attempt start times for safe recovery, and `i405_legacy_failures` classifies
exact legacy provider-failure placeholders. Do not blindly stamp migrations on
another database; inspect its migration history and schema first.
