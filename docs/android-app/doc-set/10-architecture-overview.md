# Architecture Overview - sotto for Android

Single-module-first plain Kotlin/Compose app (ADR-001) with one hard internal
boundary: the **engine** (pure logic + inference + persistence) must not depend
on the **shell** (Compose UI, Android services). The engine is where the value
is; the shell is replaceable.

## System diagram

```
share sheet / file open / paste
        │
        ▼
┌──────────────────────────── app (shell) ───────────────────────────┐
│  Compose UI: Confirm · Player · Library · About                    │
│  NarrationService (foreground, mediaPlayback type)                 │
│    ├── NarrationEngine (engine)                                    │
│    │     clean_markdown port → chunk port → SynthesisQueue         │
│    │     └── KokoroSynthesizer (sherpa-onnx JNI, Kokoro-82M int8)  │
│    │           └── writes chunk PCM → encoder → oration audio file │
│    └── Media3 ExoPlayer ← plays the growing file                   │
│  Room DB: orations · chunks-progress · joblog · settings           │
│  Files (app-private): orations/<id>/audio + source.md              │
└─────────────────────────────────────────────────────────────────────┘
        ▲
        └── `local` flavor: NO network - no INTERNET permission exists (ADR-004).
            `sync` flavor adds, in src/sync only (ADR-007):
            SyncEngine ──▶ sotto server /api/v1 (12-api-contract.md)
            (library mirror: download server entries, upload local ones;
             narration never touches it)
```

## Components

### Engine (package `engine/`, no Android UI imports)

- **TextPipeline** - Kotlin ports of app.py's `clean_markdown()` and `chunk()`
  (1,000-char sentence-boundary chunks). Deterministic, validated against test
  vectors generated from the Python originals. These two functions are the
  shared-DNA between the server and this app; the test vectors are the contract.
- **KokoroSynthesizer** - wraps sherpa-onnx's Kotlin/JNI API; loads the bundled
  int8 model once per service lifetime; `synthesize(text, voiceId): FloatArray`.
  Phonemization is sherpa-onnx's bundled espeak-ng - no Python, no misaki.
- **NarrationEngine** - drives an oration: for each remaining chunk, synthesize,
  encode, append to the oration's audio file, persist progress (chunk index +
  byte offset) in Room, emit progress. Resume = truncate to last persisted byte
  offset and continue, exactly the server's run_job resume design.
- **Estimator** - median seconds-per-word from completed orations on this
  device; fallback constant until 2+ samples exist (server's `calibrated_rates`
  logic).

### Shell

- **NarrationService** - a `MediaSessionService` (Media3) holding both the
  ExoPlayer and the NarrationEngine coroutine. One service, one notification:
  synthesis progress and playback controls together. Foreground type
  `mediaPlayback` while playing; synthesis-only (queued, screen off, not
  listening) runs as expedited WorkManager work that checkpoints per chunk and
  tolerates being deferred - it never needs to outrun Doze because resume is
  free (ADR-003 records this split).
- **Playhead governor** - pauses playback at the synthesis frontier ("catching
  up") when synthesis falls behind; resumes when buffer ≥ ~20 s ahead.
- **UI** - four screens (Confirm, Player, Library, About), Material 3, single
  activity, Navigation-Compose. Share intents land on Confirm.

### Sync (flavor `sync` only, package `src/sync/`)

- **SyncEngine** - implements the client side of 12-api-contract.md: token
  auth (stored in Keystore-backed settings), library list/download/upload,
  rename LWW. Peripheral by construction: it mutates the same Room rows and
  files the engine owns, through the same DAOs, and nothing in `engine/` or
  `shell/` references it. The `local` flavor compiles without this source set
  existing.

## Audio format decision (resolved by SPIKE-001)

Kokoro emits 24 kHz mono PCM. Options: (a) encode chunks to MP3 with LAME
(server parity, larger CPU cost), (b) AAC via Android's MediaCodec (hardware
encoder, free, native), (c) store WAV and encode on export. Leaning (b) -
hardware AAC in an `.m4a` container costs near-zero CPU during synthesis -
with (a) only if seamless append across sessions proves unreliable in M4A.
The spike measures both. Export always produces a single file either way.

## Data design

See 11-data-model.md. Summary: Room is the source of truth for metadata and
progress; the filesystem holds the two big artifacts (audio, source text) under
`filesDir/orations/<orationId>/`, mirroring the server's sidecar convention.

## Concurrency model

One synthesis worker, ever (mirrors the server's per-job thread but stricter:
phones don't profit from parallel ONNX sessions and thermals punish trying).
Queue is FIFO by request time. Playback of an already-complete oration is
independent of the worker.

## Assumptions

- sherpa-onnx Kokoro RTF ≥ 1.3x on the floor device (SPIKE-001 verifies).
- arm64-v8a covers all target devices (ADR-005).
- A growing local file can be played by ExoPlayer with periodic
  re-resolution of duration - proven pattern; the web app already does the
  equivalent with its "Load latest" preview.
