# CLAUDE.md - sotto-android

(To be placed at the app repo root. Governs agent-assisted work in this repo.)

## What this project is

A plain Kotlin/Compose Android app that narrates documents on-device with
Kokoro-82M (sherpa-onnx). Two flavors: `local` (no INTERNET permission - the
flagship claim) and `sync` (opt-in sotto-server account sync). Full context:
`docs/` - read `docs/README.md` first; `docs/constitution.md` is binding.

## Hard rules (see constitution.md for the full list and enforcement)

- Never add INTERNET/ACCESS_NETWORK_STATE to the `local` flavor's merged
  manifest; never add any other permission to `sync`. CI enforces; don't fight
  the guard, fix the dependency.
- `engine/` never imports Compose, Android services, network, or `shell/`.
- Network code only under `src/sync/`.
- `cleanMarkdown`/`chunk` changes require regenerated vectors from the sotto
  server repo first - the server is the reference implementation.
- Wording: "narrating/oration" in UI text; "synthesized/Kokoro-82M" only in
  About/provenance. No em-dashes in any prose - use a spaced hyphen ( - ).
- No Co-Authored-By trailers on commits.
- Performance claims only from measured numbers recorded in docs/_state.md.

## Build & verify

- `./gradlew ktlintCheck lintLocalDebug testLocalDebugUnitTest` - fast loop
- `./gradlew connectedLocalDebugAndroidTest` - emulator (x86_64, stub model)
- `./gradlew assembleLocalRelease assembleSyncRelease` - artifacts
- Manifest guard runs in CI; locally:
  `aapt dump permissions app/build/outputs/apk/local/release/*.apk`
- Real-model performance work happens on arm64 hardware only - never conclude
  performance from the emulator.

## Working style

- Update `docs/_state.md` at the end of any session that changes phase,
  measurements, or decisions; keep `docs/tasks.md` checkboxes current.
- Behavior changes update the governing doc in the same commit
  (constitution rule 14).
- ADR before merge for any forever-decision (template: docs/adr/README.md).
