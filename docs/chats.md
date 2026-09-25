# Chat and message APIs

All seven endpoints require an active user's bearer token. Log in at
`POST /api/auth/login` and use Authorize in http://127.0.0.1:8000/docs.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | /api/chats | Create a chat (201); title defaults to New Chat |
| GET | /api/chats | List your chats, most recently updated first |
| GET | /api/chats/{chat_id} | Read your chat |
| PATCH | /api/chats/{chat_id} | Rename your chat using a title |
| DELETE | /api/chats/{chat_id} | Delete your chat and its messages (204, empty body) |
| GET | /api/chats/{chat_id}/messages | Read message history in chronological order |
| POST | /api/chats/{chat_id}/messages | Store a user message and temporary assistant reply (201) |

Create example: `{"title":"Python Learning"}`.
Send example: `{"content":"Explain Python inheritance"}`.
Sending returns two messages: the user's content and the assistant response
`Message received: Explain Python inheritance`. No AI provider is connected yet.
Both messages are saved in one transaction and sending updates the chat's
activity timestamp. Equal timestamps use IDs for stable ordering.

Users can only read or modify their own chats and messages. Missing chats and
another user's chats both return 404. Missing authentication returns 401.
Titles must be nonblank and at most 255 characters. Message content must be
nonblank; its whitespace formatting is preserved. Invalid inputs return 422.

## Verification

From backend, with PostgreSQL running:

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

All 11 authentication/chat tests passed. Chat tests cover CRUD, persisted
messages, default values, ownership isolation, unauthenticated access,
validation, activity/history ordering, and cascading deletion. Test data is
rolled back. All seven endpoints were also verified against the live server
in the requested order; the temporary live test chat was deleted afterward.

Existing authentication, home, database-health, and Swagger endpoints remain
available. This stage reuses the existing schema and requires no migration.
