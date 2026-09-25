# Authentication

Implemented JSON endpoints:

- `POST /api/auth/register`: name, email, password; returns public user fields (201).
- `POST /api/auth/login`: email, password; returns a bearer access token (200).
- `GET /api/auth/me`: requires `Authorization: Bearer <token>`; returns the current active user.

Open http://127.0.0.1:8000/docs to try the endpoints. Register or log in, copy
`access_token`, click Authorize, and paste the token itself. Then execute `/me`.

Passwords are hashed with Argon2. Emails are trimmed and lowercased before
lookup and storage. Registration requires a nonblank name up to 100 characters,
a valid email up to 255 characters, and a password between 8 and 1024 characters.
Duplicate emails return 400. Incorrect credentials, invalid or expired tokens,
missing credentials, and inactive or deleted accounts return 401.
User responses never contain passwords or password hashes.

The generated `SECRET_KEY` stays in ignored `backend/.env`.
`ACCESS_TOKEN_EXPIRE_MINUTES` defaults to 60. JWT verification requires `sub`
and `exp` and only accepts HS256. Changing the secret invalidates existing tokens.
The example environment file contains placeholders only.

## Verification

From `backend`, with PostgreSQL running:

```powershell
& ./.venv/Scripts/python.exe -m unittest discover -s tests -v
```

Six PostgreSQL integration tests cover the successful flow, hashing, email
normalization and duplicates, incorrect passwords, unknown users, malformed,
expired and incorrectly signed tokens, missing claims, inactive/deleted users,
input validation, and existing endpoints. Test records are rolled back.

The supplied Pavan example (`pavan@example.com`) was also registered and tested
against the live server using the example password from the task instructions.
This demo account remains available. No JWT or signing key was printed.

No authentication migration is needed: the existing users table already has
all required fields. Chat and message APIs are implemented; see [chat API usage](chats.md).

References: [FastAPI JWT and password hashing](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/)
and [PyJWT claim validation](https://pyjwt.readthedocs.io/en/latest/usage.html).
