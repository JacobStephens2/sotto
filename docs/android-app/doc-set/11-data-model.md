# Data Model - sotto for Android

Room is authoritative for metadata and progress; the filesystem holds the large
artifacts. Layout mirrors the server's library sidecar convention (`.mp3` +
`.md` + `.title` + `.meta`) so the two products stay conceptually aligned.

## Entities

### Oration

| Column | Type | Notes |
|---|---|---|
| id | UUID string, PK | Directory name under `filesDir/orations/` |
| title | String(120) | Verbatim user name, else heading-derived (server `convert()` rule) |
| status | enum | see state machine |
| voiceId | String | one of the 7 `KOKORO_VOICES` |
| words | Int | word count of cleaned text |
| chunksTotal | Int | set when chunking completes |
| chunksDone | Int | progress; resume point |
| audioBytes | Long | last durable byte offset; truncate-to here on resume |
| audioDurationMs | Long | derived, updated per chunk |
| narratedMs | Long | accumulated wall-clock synthesis time across resumes (fixes the server's known undercount) |
| createdAt / updatedAt | Long | epoch ms |
| playheadMs | Long | last listening position (S2 position memory) |
| errorMessage | String? | terminal error detail |
| serverName | String? | sync key: filename in the server library (`sync` flavor; null = never synced) |
| serverMtime | Long? | server-side mtime at last sync, for rename LWW (12-api-contract.md) |
| downloaded | Bool | false for SERVER_ONLY rows (metadata known, audio not yet fetched) |

Files: `orations/<id>/audio.m4a` (or `.mp3`, per the spike), `orations/<id>/source.md`.

### JobLogEntry

Append-only traceability (boundary 5): `id, at, orationId?, title, event, detail`.
Events: created, started, resumed, chunk-done (sampled, not every chunk),
stopped, completed, error, deleted, exported, renamed. Viewable in About →
Activity log. Never leaves the device.

### Settings (single row / DataStore)

`lastVoiceId` (S1 preselect), `playbackSpeed`, `sleepTimerDefault`,
`estimatorRates` (per-voice median s/word once ≥ 2 samples).

## State machine (Oration.status)

```
            ┌────────────┐
 created ──▶│  QUEUED    │──── worker picks up ───▶ NARRATING
            └────────────┘                            │  │  │
   user stop ──────────────────────────────◀──────────┘  │  │
        ▼                                                 │  │
    STOPPED  (partial kept, playable)         all chunks ─┘  └─ failure
                                                  ▼              ▼
                                               COMPLETE        ERROR
                                                                 │
                                  retry (re-queue from chunksDone) ──▶ QUEUED
```

- QUEUED → NARRATING only via the single worker; FIFO.
- Process death in NARRATING → on next start, any NARRATING row reverts to
  QUEUED with its chunksDone/audioBytes intact (the resume_jobs design).
- STOPPED and COMPLETE are both playable; STOPPED shows "stopped at n of N".
- Deleting an oration removes the Room row and the directory atomically (row
  first, directory cleanup idempotent on next start).

## Invariants

1. `audioBytes` is only advanced after an fsync of the audio file (chunk
   boundary durability - lost work on crash is at most one chunk).
2. `chunksDone` and `audioBytes` move together in one Room transaction.
3. `title` is never derived twice: derived at creation, then only user renames
   touch it.
4. An oration directory without a Room row (or vice versa) is garbage; a
   startup sweep deletes orphans and logs the event.
5. In the `local` flavor the sync columns are always null/false and no entity
   stores account ids or URLs - nothing to sync, nothing to leak. In the `sync`
   flavor, the only stored identifiers are the user's chosen server URL and
   token (Keystore-backed settings, never in Room) and `serverName` per entry
   (constitution.md boundary 2).
6. SERVER_ONLY rows (`downloaded = false`) are metadata mirrors: no files on
   disk, not playable, excluded from the estimator and the job log until
   downloaded.

## Validation rules

- title: trimmed, 1-120 chars after fallback derivation.
- input text: non-empty after `clean_markdown`, ≤ 400 KB raw (server parity).
- voiceId: must be in the bundled voice list; unknown → default voice
  (server's coerce rule).
