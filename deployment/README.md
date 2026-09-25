# Deployment

Two deployment paths are prepared.

## Managed cloud: Neon + Render + Vercel

- Neon supplies `DATABASE_URL`.
- Render builds `backend/Dockerfile` from `render.yaml` and runs migrations on
  container startup.
- Vercel builds the Next.js app from the `frontend` root directory using
  `frontend/vercel.json`.
- Render `CORS_ORIGINS` must include the exact Vercel production origin.

Follow [cloud deployment](../docs/cloud-deployment.md) for account setup,
environment variables, deployment order, smoke testing, and rollback.

## Docker Compose

1. Copy `deployment.env.example` to `deployment.env` and fill every placeholder.
2. Validate and start:

```powershell
docker compose --env-file deployment.env config --quiet
docker compose --env-file deployment.env up --build -d
```

The stack contains PostgreSQL, a migration job, FastAPI on internal port 8000,
Next.js, and Caddy. PostgreSQL and FastAPI have no public host ports. Caddy
provides same-origin HTTPS on 80/443 and disables compression for API/SSE
responses so streaming is not buffered.

The named PostgreSQL volume is persistent. Do not run `docker compose down -v`
for a database you need to keep. Review and back up before future migrations.

The task runner is in-process and limited to two active runs per API process.
Use one API process unless external worker ownership and a durable queue are
added. Startup and 30-second recovery sweeps make interrupted work retryable,
and generation tokens reject late provider results.

Inspect logs with:

```powershell
docker compose --env-file deployment.env logs --tail=100
```

Docker is not installed on the current workstation, so the container build must be
verified on a Docker/Render builder.
