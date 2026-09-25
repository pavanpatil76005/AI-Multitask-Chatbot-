# Cloud deployment: Neon, Render, and Vercel

The repository contains all manifests required for the requested topology:

- `render.yaml` for the FastAPI Docker service
- `backend/Dockerfile` and `backend/docker-entrypoint.sh`
- `frontend/vercel.json`
- `.github/workflows/ci.yml`

Provider credentials are intentionally not stored in Git. The current machine
has no authenticated Neon, Render, or Vercel session, so the final account-side
provisioning steps must be completed by an authenticated owner.

## 1. Neon PostgreSQL

1. Create a Neon project.
2. Use the default PostgreSQL database or create `ai_chatbot`.
3. Copy its **pooled** connection string. It resembles:
   `postgresql://USER:PASSWORD@HOST/neon_db?sslmode=require`
4. Save it as Render's `DATABASE_URL`. `backend/app/core/config.py` normalizes
   `postgres://` and `postgresql://` to `postgresql+psycopg://` and preserves TLS
   query parameters.
5. The container runs `alembic upgrade head` on startup. To migrate manually:

```powershell
cd backend
$env:DATABASE_URL = "postgresql://..."
.\.venv\Scripts\python.exe -m alembic upgrade head
```

Never commit the Neon URL because it contains the database password.

## 2. Render FastAPI service

1. In Render, choose **New > Blueprint** and connect
   `pavanpatil76005/AI-Multitask-Chatbot-`.
2. Render reads `render.yaml` and builds `backend/Dockerfile`.
3. Set these environment variables:

| Variable | Source |
| --- | --- |
| `DATABASE_URL` | Neon pooled connection string (`sync: false`) |
| `SECRET_KEY` | Blueprint generates a 32+ character value |
| `GEMINI_API_KEY` | Google AI Studio secret (`sync: false`) |
| `GEMINI_MODEL` | Primary model name |
| `GEMINI_FALLBACK_MODEL` | First fallback |
| `GEMINI_SECOND_FALLBACK_MODEL` | Second fallback |
| `CORS_ORIGINS` | Comma-separated localhost and Vercel origins |

4. Deploy and record the backend URL, for example
   `https://ai-multitask-api.onrender.com`.
5. Verify `https://YOUR-BACKEND/health/database` and
   `https://YOUR-BACKEND/docs`.

The container listens on `$PORT` (Render-provided) or 8000. Its entrypoint applies
migrations before starting Uvicorn.

## 3. Vercel frontend

1. In Vercel, import the same GitHub repository.
2. Set **Root Directory** to `frontend`. `frontend/vercel.json` selects Next.js.
3. Add `NEXT_PUBLIC_API_URL=https://YOUR-BACKEND.onrender.com`.
4. Deploy and record the frontend URL, for example
   `https://ai-multitask-xyz.vercel.app`.
5. Add that exact origin to Render's `CORS_ORIGINS` and redeploy the backend:

```text
http://localhost:3000,https://ai-multitask-xyz.vercel.app
```

Do not add a trailing slash to stored CORS origins; settings normalization removes it.

## 4. Final production smoke test

Run in this order:

1. Open the Vercel URL and register.
2. Log out, then log in.
3. Create a chat and request a Gemini answer.
4. Refresh and confirm history is restored.
5. Use Stop on a streaming answer, then Retry.
6. Create a multitask plan and confirm every task reaches completion and one
   combined answer appears.
7. Upload a PDF and CSV, verify analysis and metadata ownership.
8. Search, rename, pin, archive, and delete a conversation.
9. Confirm the deployed backend health endpoint and frontend API URL.

## Rollback and maintenance

- Neon retains branch/database backups according to its plan.
- Render keeps the previous deploy image; promote a known-good deploy to roll back.
- Review pending Alembic revisions before the next production migration.
- Rotate `SECRET_KEY` or `GEMINI_API_KEY` directly in Render; never commit values.
- Keep `CORS_ORIGINS` explicit. Do not use `*` with credentialed requests.

## Verification status

The configuration is prepared; no Neon database or Render/Vercel deployment was
created in this pass. Docker CLI/Desktop and authenticated provider access are
unavailable in the current environment. Actual production URLs, production CORS,
and the complete hosted smoke test remain pending. The CI workflow now includes
an image build plus a disposable PostgreSQL/container health test on its next run;
adding that job does not mean it has run successfully.

Configuration references: [Render Blueprint specification](https://render.com/docs/blueprint-spec),
[Vercel monorepos](https://vercel.com/docs/monorepos), and
[Vercel environment variables](https://vercel.com/docs/environment-variables).
