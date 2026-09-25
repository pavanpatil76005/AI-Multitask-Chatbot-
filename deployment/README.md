# Deployment package

This package is prepared for a Linux host with Docker Compose, a public domain
pointing to that host, and inbound ports 80/443. No remote deployment has been
performed. The hosting destination and domain are still needed. Docker is not
available in the current workspace, so container builds have not been verified.

1. Copy `deployment.env.example` to `deployment.env` and fill in fresh secrets,
   your Gemini configuration, and `APP_DOMAIN` (hostname only).
2. Run `docker compose --env-file deployment.env config --quiet`.
3. Run `docker compose --env-file deployment.env up --build -d`.
4. Open `https://YOUR_DOMAIN/health/database`, then sign in through the frontend.
5. Verify a streamed answer, Stop/Retry, file analysis, and a complete task run.

Caddy provides HTTPS and forwards same-origin API calls without buffering the
stream. PostgreSQL and FastAPI have no public host ports. The migration container
must succeed before the API starts. Docker build contexts exclude local secrets
and dependency directories. Use the named PostgreSQL volume for persistence and
schedule backups before accepting important data. Do not use `down -v` on a
database you need to preserve.

The task runner has six provider worker threads and accepts two active runs per
API process. Each plan runs up to three tasks simultaneously and has a 180-second
deadline. Startup recovery marks interrupted work retryable, a 30-second periodic
sweep expires overdue runs, and generation tokens reject late results. Regular
streams have a 15-minute stale-work ceiling. This is not a distributed queue: run
one API process unless external worker ownership and durable queueing are added.
Tasks never execute generated code or external actions.

Caddy compression is applied only to frontend responses, not API/SSE responses.
FastAPI also emits `Cache-Control: no-cache, no-transform` and
`X-Accel-Buffering: no` for streamed answers.

To inspect startup: `docker compose --env-file deployment.env logs --tail=100`.
For updates, back up PostgreSQL, review migrations, then rerun the build/up command.
