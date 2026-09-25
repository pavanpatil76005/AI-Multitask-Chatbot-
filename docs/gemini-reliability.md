# Gemini reliability

The configured model order is:
1. gemini-3.6-flash
2. gemini-3.5-flash
3. gemini-3.5-flash-lite

Configuration defaults, `.env`, and `.env.example` agree. API keys remain private.
The SDK makes at most three attempts per model, with exponential backoff
(initial delay 1 second, maximum 8 seconds, base 2) and a 60-second request timeout.
HTTP 408, 429, 500, 502, 503, and 504 can trigger fallback; permanent API errors
fail immediately. Duplicate or disabled model entries are skipped.

The AI Multitask prompt covers programming, mathematics, science, writing,
summarization, brainstorming, interviews, data analysis, and general questions.
It includes recent conversation context and asks for clarification when needed.

## Stream recovery

When streaming is interrupted by a transient API error or transport disconnect,
the next model receives the original prompt and the exact accumulated answer,
with instructions to continue from its ending without repeating text. Existing
output remains visible; new chunks are appended without stripping whitespace.
Continuation is generated text and cannot guarantee perfect semantic continuity.

If all remaining models fail, partial output is saved with status `incomplete`
and returned with a clean error event. The frontend preserves it rather than
replacing it with an error message. It also retains visible text on a network
failure and buffers incomplete SSE frames across network reads. Browser network
failures cannot guarantee database persistence. Successful responses are saved
normally. Backend logs contain exception type/status, not private provider payloads.

## Verification

The backend suite currently has 25 passing tests and one unrelated task-workflow
failure because `/api/chats/{id}/tasks` is not implemented. Recovery tests cover
third-model generation/streaming, partial continuation, exhausted fallbacks,
transport disconnects, safe logging, and saved incomplete messages.
TypeScript checking passes. Frontend lint reports an existing `loadChats`
declaration-order error and an unused `loading` warning outside the streaming changes.

Run from backend:

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
& ./.venv/Scripts/fastapi.exe dev app/main.py --port 8001
```

Frontend remains available at http://localhost:3000.

References: [Google model catalog](https://ai.google.dev/gemini-api/docs/models)
and [thinking levels](https://ai.google.dev/gemini-api/docs/generate-content/thinking).

All seven requested prompts passed live streaming checks in one fresh chat; 14 history messages were verified. Arithmetic returned 35,505. The comparison request was slow. Only the verified test chat was removed afterward. Cleanup exposed an unrelated missing tasks table in the current task-model work: ORM chat deletion may fail until that work is completed.
