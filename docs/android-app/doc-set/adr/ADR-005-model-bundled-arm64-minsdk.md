# ADR-005: Model bundled in the APK; arm64-v8a only; minSdk 29

Status: accepted
Date: 2026-06-12

## Decision

The int8 Kokoro model and voice embeddings ship inside the APK as assets. The
APK builds for `arm64-v8a` only. `minSdk = 29` (Android 10), `targetSdk` =
latest stable.

## Context

**Bundling is forced, then embraced.** ADR-004 (no network) eliminates
first-run model download. Sideload distribution (ADR-006) has no Play asset
delivery either. So the model rides in the APK: expect roughly 150-250 MB total
(SPIKE-001 records the real number). GitHub releases serve files this size
without complaint, and a single self-contained artifact suits the product's
"everything is local" story. If/when a Play listing happens, Play Asset Delivery
(install-time pack) carries the model past Play's base-APK limits without
changing the no-network property.

**arm64-v8a only:** every plausible target device since ~2017 is arm64; x86_64
is emulators (a debug-only x86_64 build variant exists for development);
armeabi-v7a devices are below the performance floor SPIKE-001 gates on anyway.
Shipping one ABI halves artifact size versus universal.

**minSdk 29:** scoped storage from day one (no legacy storage code paths),
modern foreground-service and notification APIs, and 29 covers ~95%+ of active
devices in 2026. Nothing in the PRD needs anything older.

## Consequences

- APK is large by app-store norms; the README owns this ("the entire voice is
  inside").
- Model version upgrades mean APK releases - acceptable, releases are cheap on
  GitHub.
- Emulator testing of synthesis uses the x86_64 debug variant; release
  performance claims come only from arm64 hardware.
