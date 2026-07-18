# ADRs - sotto for Android

One file per architecturally significant decision. Format, per the unified
writing style guide (decision first, then mechanism):

```
# ADR-NNN: <decision as a sentence>
Status: accepted | superseded by ADR-MMM | proposed
Date: YYYY-MM-DD

## Decision
## Context
## Consequences (incl. what this rules out)
```

Index:

- ADR-001: Plain Kotlin + Jetpack Compose, single platform, no KMP/Flutter/RN
- ADR-002: On-device synthesis with sherpa-onnx running Kokoro-82M int8
- ADR-003: Streaming chunk-ahead-of-playhead synthesis in one foreground media service
- ADR-004: No INTERNET permission in v1; the manifest is the privacy claim
- ADR-005: Model bundled in the APK; arm64-v8a only; minSdk 29
- ADR-006: Sideload-first distribution via GitHub releases; Play deferred
