# ADR-001: Plain Kotlin + Jetpack Compose, single platform, no KMP/Flutter/RN

Status: accepted
Date: 2026-06-12

## Decision

sotto-android is a single-platform Android app in plain Kotlin with Jetpack
Compose. No Kotlin Multiplatform scaffolding, no Flutter, no React Native, no
Capacitor, no Rust core.

## Context

Every interesting subsystem in this app is native-Android-shaped: sherpa-onnx
ships first-class Kotlin/JNI bindings (and no React Native binding - an RN build
would mean writing the same native module *plus* a bridge); Media3/ExoPlayer,
foreground media services, and share-sheet intents are all Kotlin-first APIs.
The 2026-06-10 council research and the fable-5 brainstorm both land here for an
on-device build.

Portfolio context tips the same way: the existing repo set already demonstrates
Flutter (quadrille), Compose Multiplatform (daily-dozen-kmp), Capacitor
(MacroTracker), and a Rust-core shell (cascade). Plain native Android is the one
missing competency, and it is the legible one for platform-engineering roles.

KMP specifically: there is no second platform in scope (Concept Brief non-goals
exclude iOS), so KMP buys abstraction cost now for an option that, if ever
exercised, can still be adopted later by extracting the `engine/` package - which
this codebase keeps UI-free precisely to preserve that move.

## Consequences

- Fastest path to the hard parts; no bridge layers over JNI.
- iOS would be a rewrite or a later KMP extraction of `engine/`; accepted.
- Rules out sharing UI code with any other sotto client; the shared DNA with
  the server is the ported `clean_markdown`/`chunk` logic and its test vectors,
  not code.
