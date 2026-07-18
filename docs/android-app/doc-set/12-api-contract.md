# API Contract - sotto server sync API v1

The HTTP contract between sotto-android's `sync` flavor and the sotto server
(app.py). This document is normative for both sides; the server work it implies
is tracked in tasks.md and does not exist yet. Versioned under `/api/v1/`.

## Design constraints

- Additive to app.py - no change to existing session-cookie web auth.
- Token auth, because the app is not a browser: no cookies, no CSRF.
- The server's library remains filename-keyed (slug + sidecars); the API
  exposes that model rather than inventing a new one.
- Server remains the synthesis authority for nothing here: the app narrates
  on-device; this API only moves finished orations and metadata.

## Authentication

`POST /api/v1/token`
Body: `{"email": "...", "password": "..."}`
→ `201 {"token": "<opaque>", "created": "..."}`

- Verifies against users.json exactly like web login; rate-limited (5/min/IP);
  every issue/revoke writes an audit line (server boundary 5).
- Token: `secrets.token_urlsafe(32)`, stored **hashed** server-side in
  `state/api_tokens.json` with `{email, created, last_used, label}`.
- Tokens are listed and revocable on the web account page.
- All other endpoints: `Authorization: Bearer <token>` → 401 if absent/invalid.

`GET /api/v1/me` → `200 {"email": "..."}` - connection test for the app's
"Connect account" screen.

## Library

`GET /api/v1/library`
→ `200 {"entries": [{"name": "r3-plan.mp3", "title": "R3 Plan", "words": 5979,
"secs": 1575, "voice": "am_michael", "size": 20231040, "duration_secs": 2528,
"mtime": 1781300000, "has_text": true}]}`
Fields come from the existing sidecars (`.title`, `.meta`, mp3_duration).

`GET /api/v1/library/<name>/audio` → `200 audio/mpeg` (existing X-Sendfile path)
`GET /api/v1/library/<name>/text` → `200 text/markdown` or 404 if no sidecar

`PUT /api/v1/library/<name>`
Multipart: `audio` (required, audio/mpeg or m4a), `text` (optional), and a
`meta` JSON part `{"title", "words", "secs", "voice"}`.
→ `201` created | `200` replaced. Server writes the file plus `.md`, `.title`,
`.meta` sidecars - an uploaded oration is indistinguishable from a saved web
one. `name` must match `[a-z0-9-]{1,60}\.(mp3|m4a)`; size capped (413 over).

`PATCH /api/v1/library/<name>` Body `{"title": "..."}` → `200`. Rename =
rewrite `.title` (same semantics as the web rename; file name never changes).

`DELETE /api/v1/library/<name>` → `204`. Deletes entry + sidecars and revokes
any share link for it. (App UI confirms loudly; there is no tombstone sync -
see Sync semantics.)

## Errors

JSON body `{"error": "<machine-key>", "detail": "<human>"}` with conventional
status codes: 400 validation, 401 auth, 404 unknown entry, 409 name conflict on
PUT with `If-None-Match: *`, 413 too large, 429 rate-limited.

## Sync semantics (client-side rules, here because both sides must agree)

- Identity: `serverName` (the filename) is the sync key; the app stores it on
  its Oration row. Audio content is immutable per name - re-upload replaces.
- **Pull**: list → entries unknown locally appear as SERVER_ONLY (metadata
  only); user downloads on demand or "download all."
- **Push**: local COMPLETE/STOPPED orations without `serverName` can be
  uploaded; slug collision → app appends `-<6 chars of id>` (server's own
  collision rule).
- Renames: last-write-wins by `mtime`; titles are the only mutable field.
- Deletes do **not** propagate automatically in v1 - deleting locally keeps the
  server copy and vice versa. Explicit "delete on server too" affordance
  instead. Simplest honest semantics; revisit only with real pain.
- Playhead position does not sync in v1 (candidate for v1.1 via a
  `PATCH .../meta` extension).

## Versioning

Breaking changes bump the path (`/api/v2/`). The app sends
`User-Agent: sotto-android/<version> (<flavor>)`; the server may log it,
never branches on it.
