# Chat loading: rejected session recovery

The reported failure was confirmed in backend logs as `GET /api/chats 401`,
with successful CORS preflights. The backend and database health checks passed,
the frontend URL already pointed to port 8001, and Alembic was at
`c831_task_results` with no schema drift. A rejected stored token was being
displayed as the generic `Unable to load chats` error.

Protected frontend API calls now clear the rejected token and navigate to login.
Streaming uses the same authenticated request helper. A late 401 cannot erase a
newer login's token. Incorrect credentials on the login form continue to show the
login error. Network failures and chat-loading HTTP errors now have distinct,
actionable messages.

Refresh the frontend and sign in again with your existing account. No manual
local-storage editing is needed. This does not extend token lifetime or weaken
backend authorization.

Verification: seven frontend regression tests, production build, and ESLint passed.
The running API returned 200 for `/api/chats` after a fresh login, 401 for an
invalid token, and 200 for the localhost CORS preflight. Run the helper tests with
`npm test` in `frontend`.
