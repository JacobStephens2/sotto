# Roadmap - sotto for Android

Living document; reorder freely, but no phase starts before its gate passes.
Estimates assume evenings/weekends pace.

## Phase 0 - SPIKE-001: on-device Kokoro feasibility (gate for everything)

Bare Kotlin app, no UI polish: sherpa-onnx + Kokoro-82M int8, synthesize a fixed
2,000-word text on a real device. Measure and record in `_state.md`:

- Realtime factor (target: ≥ 1.3x on a Pixel-6-class arm64 device)
- Battery %/hour during sustained synthesis+playback
- Thermal behavior over 30+ minutes
- Peak memory; APK size with bundled int8 model

**Gate:** RTF ≥ 1.0x sustained without thermal shutdown. Below 1.0x, streaming
playback cannot keep up and the product premise fails → stop and reconsider
(options: smaller model, pre-synthesis batch mode, or shelve).
**Estimate:** 2-4 evenings. The research already de-risks this
(puff-dayo/Kokoro-82M-Android runs int8 Kokoro on Android), but our numbers on
our floor device are the gate.

## Phase 1 - Core engine, no UI

- Port `clean_markdown()` and `chunk()` from app.py to Kotlin with the Python
  test vectors (the highest-value pure-logic code in the project).
- `NarrationEngine`: text → chunks → sherpa-onnx → growing audio file, with
  per-chunk persistence and resume (the server's run_job/resume design,
  device-local).
- Room schema from 11-data-model.md; job log.
- Unit + instrumented tests green in CI.
**Gate:** engine narrates the encyclical test file end-to-end on-device,
resuming across a forced process kill.
**Estimate:** 1-1.5 weeks.

## Phase 2 - Vertical slice (21-vertical-slice-plan.md)

Share text → confirm screen → streaming narration in a foreground service →
Media3 playback with lock-screen controls → entry visible in a minimal library.
One workflow, production quality, CI-built signed APK.
**Gate:** I use it for a real walk-listen of a real document, daily, for a week.
**Estimate:** 1-2 weeks.

## Phase 3 - Full v1 surface

- Library: detail screen, rename, delete, source text, progress on incomplete.
- Player: speed control, sleep timer, position memory polish.
- Voice previews; calibrated time estimate; About screen with provenance text
  and the no-network claim.
- Queueing; storage-full and thermal edge cases from the PRD.
**Gate:** PRD acceptance criteria all pass on the device matrix
(30-testing-plan.md).
**Estimate:** 2-3 weeks.

## Phase 4 - Release 1.0 (sideload)

- GitHub repo public, license per repo conventions, README with the
  boundary story and `aapt dump permissions` verification instructions.
- Signed release APK via GitHub Actions, published as a GitHub release
  (MacroTracker pattern). F-Droid submission considered (the no-network,
  FOSS-model app is a natural fit).
**Estimate:** 2-3 evenings.

## Phase 5 - account sync (`sync` flavor; ADR-007, 12-api-contract.md)

Server side first (in the sotto server repo): token auth + the /api/v1 library
endpoints, honoring the existing sidecar scheme. Then the app's `sync` source
set: Connect-account screen, server-library section, download/upload, rename
LWW. May run in parallel with Phase 3 once the contract is frozen. **Decided
2026-06-12: sync ships at 1.0**, so this phase completes before Phase 4's
release and both artifacts publish together.
**Gate:** narrate on the phone → upload → play in a desktop browser; narrate on
the web → download → play offline on the phone. Both round-trips on the real
server.
**Estimate:** 1 week server + 1-1.5 weeks app.

## Post-1.0 (each gets its own decision before work starts)

- **Play Store** - developer verification, listing assets, data-safety form
  (`local`: nothing collected; `sync`: account email + user-directed upload to
  the user's own server). Decide whether the 12-tester internal-testing slog
  (known from Creighton) is worth it for this app.
- **Extraction inputs** - share a URL/EPUB/PDF and extract text. URL fetch
  conflicts with no-network; would live in the sync flavor only.
- **Playhead-position sync** across devices (API extension; tasks.md).
- **Android Auto / Wear; per-paragraph navigation** from chunk boundaries.
