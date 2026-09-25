# Ordered completion report — 2026-09-25

## 1. Multitask aggregation

Ran the exact request through the running API in a fresh chat:

> Compare Java and Python, give 5 advantages of each, create a 7-day study plan, and suggest 3 beginner projects.

The latest planner produced five specific tasks: compare languages, Java advantages,
Python advantages, seven-day study plan, and three beginner projects. All five
completed. The database contained one user request and one completed assistant
message containing all five results. Separate HTTP requests returned identical
messages and task records, including saved results. Aggregation assembles the saved AI
outputs into one Markdown answer; it does not make an extra model call to rewrite
or silently omit results.

Reproduce with `python verify_task_cycle.py` from `backend`. This uses real Gemini
quota and removes only its temporary verification account/data. Report:
`.local/ordered-task-validation.json`.

Every executor call now explicitly receives the saved original plan request,
task instructions, and any completed results from that same plan. Queued tasks
receive results available when submitted; parallel siblings do not wait for each
other. Tests cover retries, queued work, and exclusion of unrelated plan results.

The reported legacy Plan #52 was inspected and repaired in place. Its generic
research title had incorrectly become its original request, and only one of its
three tasks belonged to the plan. Using the user's explicitly stated machine-learning
goal, all three tasks were regrouped and regenerated successfully. The existing
assistant message was updated with one combined answer. Original records were
backed up locally before repair; other conversation topics were left intact.
The sidebar now labels its overall counter as "All tasks in this chat" separately
from each plan's count.

## 2. Task failures and retry

Individual tasks now use `pending`, `in_progress`, `completed`, `failed`, and
`cancelled`. Internal task-run records retain their separate `running` state.
Migration `g203_task_in_progress` preserves existing rows while normalizing the
task state. Three-minute run deadlines, periodic recovery, cancellation, restart
recovery, and guarded writes prevent stale workers from replacing new attempts.
Retries preserve completed tasks and update the same final assistant response.

## 3. Markdown

The installed `react-markdown` / `remark-gfm` renderer is used for assistant
messages and task results. Headings, bold, lists, separators, tables, and code
blocks have styles. Rendering tests also check unsafe HTML/links and remote-image
tracking protection. The rebuilt frontend serves this renderer.

## 4. Files

Real HTTP uploads and Gemini analyses passed for PDF, CSV, TXT, and Markdown.
The checks verify extracted document content in the actual saved user message,
completed answers, ownership-scoped metadata, and stored history. The PDF returned
a summary and five important points. For CSV values 10, 50, and 90, Python Decimal
calculations produced maximum 90 and average 50; Gemini explained those values.
TXT and Markdown tests included questions grounded in the supplied content.

Reproduce with `python verify_uploads.py`. Report:
`.local/ordered-upload-validation.json`. Scanned PDFs without extractable text are
rejected; OCR is not implemented. Maximum size is 5 MB and extracted text is
limited to 40,000 characters.

## Remaining local controls and verification

Search checks titles and message content. Pin/archive state is persisted. Copy,
Regenerate, Edit prompt, Edit answer, and Retry are present. Thinking and Stop
remain available. Disconnect tests verify that partial output is saved and the
provider generator is closed. A new attempt timestamp fixes premature recovery
of old messages during retry/regeneration. Non-streaming transport failures now
try the configured fallback provider, consistent with streaming failures.

- 51 backend tests passed with no unclosed psycopg connection warnings, including
  two-user isolation, invalid/expired tokens, duplicate registration, wrong
  passwords, empty messages, deletion/history, failures/retries, cancellation,
  timeout/restart recovery, legacy failure repair, invalid uploads, uploads over
  5 MB, and attachment access from another user's own chat.
- 10 frontend tests passed; production build and ESLint passed.
- Backend compilation passed and Alembic reported no schema drift.
- Latest migration: `i405_legacy_failures` (head).

No browser connection was available. Browser clicks, screenshots, responsive
visual review, and a literal browser-refresh check remain unverified. The live
checks used the same HTTP endpoints and fresh history requests, and Markdown was
render-tested through React. Deployment work remains deferred as requested; no
public deployment or Streamlit conversion was performed in this pass.
