# Tasks - sotto-android (living)

Status: planning complete, awaiting SPIKE-001. Updated 2026-06-12.

## Now (Phase 0 - SPIKE-001)

- [ ] Create `sotto-android` repo (private until 1.0 or until decided);
      license decision per repo conventions
- [ ] Copy this doc-set into the repo; move ownership there (README note in
      sotto server repo pointing across)
- [ ] Bare spike app: sherpa-onnx dependency, bundled Kokoro int8 + voices,
      synthesize fixed 2,000-word text to PCM on-device
- [ ] Measure on the floor device: RTF, battery %/hr, thermals 30 min, peak
      RSS, APK size; record all in `_state.md`
- [ ] Decide audio container (M4A/AAC vs MP3) from spike data
      (10-architecture-overview.md "Audio format decision")
- [ ] Gate decision recorded in `_state.md`: proceed / reconsider

## Phase 1 - engine

- [ ] **Server repo:** write `tools/generate_pipeline_vectors.py` producing
      pipeline-vectors.json from clean_markdown/chunk over the agreed corpus;
      publish hash
- [ ] Port cleanMarkdown + chunk with vectors green
- [ ] Room schema per 11-data-model.md; migrations baseline
- [ ] NarrationEngine with per-chunk durability + resume; kill-test
      byte-identity
- [ ] Job log writer + coverage assertions

## Phase 2 - vertical slice (21-vertical-slice-plan.md)

- [ ] Share-intent → Confirm → narrate-while-listening → library row
- [ ] NarrationService + MediaSession + single notification
- [ ] Playhead governor ("catching up")
- [ ] CI: ci.yml (lint, tests, manifest guards, debug APK) + release.yml dry run
- [ ] One week of daily real use - exit gate

## Phase 3 - v1 surface

- [ ] Library detail / rename / delete / source view
- [ ] Speed, sleep timer, position memory polish
- [ ] Voice picker with previews; estimator calibration
- [ ] About: provenance text, no-network claim + verification command, job log
- [ ] PRD edge cases: storage-full, thermal catch-up, queueing, encoding

## Phase 4 - release 1.0

- [ ] Keystore (strong password), CI secrets, signed release pipeline
- [ ] README with boundary story + aapt verification; privacy page
- [ ] License attributions incl. espeak-ng GPL linkage review
      (32-compliance-checklist.md)
- [ ] Publish `local` + `sync` artifacts together - GitHub release (decided:
      sync is in 1.0, so Phase 5 completes first)

## Phase 5 - sync (ADR-007, 12-api-contract.md)

- [ ] **Server repo:** /api/v1 token auth (hashed tokens in
      state/api_tokens.json, account-page management, rate limit, audit lines)
- [ ] **Server repo:** library list/download/upload/rename/delete endpoints
      honoring existing sidecars
- [ ] App `sync` source set: API client, Connect-account screen, token in
      Keystore-backed storage
- [ ] Pull (SERVER_ONLY rows, download on demand), push (upload local-only),
      rename LWW; per 12-api-contract.md semantics
- [ ] Sync-flavor CI guard (INTERNET only; dependency allowlist)
- [ ] End-to-end: narrate on phone → upload → play in desktop browser; narrate
      on web → download → play offline on phone

## Open questions

- [x] ~~Ship `sync` flavor at 1.0 or as 1.1?~~ **Decided 2026-06-12: sync ships
      at 1.0.** Phase 5 server work therefore precedes the 1.0 release; both
      artifacts (`local`, `sync`) publish together.
- [ ] Final display name (Concept Brief candidates)
- [ ] F-Droid: pursue at 1.0 or later? Model-asset policy question
      (32-compliance-checklist.md)
- [ ] Playhead-position sync (v1.1 candidate, needs API extension)
