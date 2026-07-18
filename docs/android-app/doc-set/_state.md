# _state.md - sotto-android session handoff

Phase: **planning complete; Phase 0 (SPIKE-001) not started**
Updated: 2026-06-12

## Decisions snapshot

- Plain Kotlin/Compose, Android-only (ADR-001)
- sherpa-onnx + Kokoro-82M int8, on-device, 7 server-parity voices (ADR-002)
- Streaming chunk-ahead-of-playhead in one MediaSessionService (ADR-003)
- `local` flavor = no INTERNET, flagship claim (ADR-004); `sync` flavor =
  opt-in sotto-server account/library sync (ADR-007, contract in
  12-api-contract.md)
- Model bundled in APK; arm64-v8a; minSdk 29 (ADR-005)
- GitHub-release sideload first; Play/F-Droid deferred decisions (ADR-006)

## Measurements (authoritative; update from device runs only)

| Metric | Value | Device | Date |
|---|---|---|---|
| RTF sustained | - | - | - |
| Battery %/hr (synth+play) | - | - | - |
| Thermal (30 min) | - | - | - |
| Peak RSS | - | - | - |
| APK size (local, release) | - | - | - |

Reference points from the server (not phone numbers): VPS 4-core EPYC ≈ 1.4x
RTF, 0.26 s/word; council research cites puff-dayo/Kokoro-82M-Android as
precedent for int8 on-device.

## Next actions

1. Create `sotto-android` repo; copy doc-set in; license decision
2. SPIKE-001 per tasks.md; fill the table above; record gate verdict here
3. If gate passes → Phase 1 (first item is the server-side vector generator)

## Open questions (mirror of tasks.md)

final display name · F-Droid timing · playhead sync
(Decided: sync ships at 1.0 - 2026-06-12.)

## Known constraints from the host environment

- VPS disk is tight for Android builds; prefer GitHub-hosted runners or a local
  machine (the Cascade build-output-on-volume lesson).
- Server-side sync API (Phase 5) touches /var/www/sotto.stephens.page/app.py -
  deploys must respect the no-restart-while-narrating rule (check jobs/*.json
  status first; resume exists but don't lean on it).
