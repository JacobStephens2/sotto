# Code Style Guide - sotto-android

## Baseline

Kotlin official code style, enforced by ktlint in CI; Android lint warnings are
errors. No checked-in code that a formatter would change.

## Module / package boundaries (the rules that matter)

```
app/src/main/kotlin/page/stephens/sotto/
  engine/      pure logic + inference + persistence. NEVER imports
               androidx.compose.*, android.app.*, or anything from shell/.
               JVM-unit-testable except the JNI synthesizer seam.
    text/      TextPipeline (clean_markdown + chunk ports) - pure functions
    synth/     KokoroSynthesizer interface + sherpa-onnx impl
    narrate/   NarrationEngine, queue, estimator
    store/     Room entities/DAOs, file layout, job log
  shell/       Compose UI, NarrationService, MediaSession, notifications
  app/         Application, DI wiring, navigation
src/sync/      sync flavor only: API client, account screens, sync engine
               (12-api-contract.md). Nothing outside src/sync may reference
               network classes - enforced by the local flavor failing to
               compile such references, plus the manifest guard.
```

- Dependency direction: `shell → engine`, `sync → engine + shell`. Never the
  reverse. `engine` knows nothing about flavors.
- The synthesizer is an interface; tests use a stub, production uses
  sherpa-onnx. No other seam needs DI ceremony - keep wiring manual and boring
  (no Hilt unless the graph actually hurts; revisit at Phase 3).

## Conventions

- Coroutines: engine exposes `suspend` functions and `Flow`s; the service owns
  the narration scope; UI collects with lifecycle awareness. No GlobalScope, no
  runBlocking outside tests.
- One worker invariant (10-architecture-overview.md) is encoded in the engine,
  not assumed by callers.
- Naming mirrors the domain doc: Oration, chunk, narrate - not "track,"
  "segment," "synthesize" in user-facing or domain code. ("Synthesis" is
  correct inside `synth/`, mirroring the server's wording rule: technical word
  at the technical layer.)
- Errors: engine functions return sealed results for expected failures
  (storage full, model load failure); exceptions are reserved for bugs.
- Comments: explain *why*, in the style of app.py's section comments - one
  plain sentence above the non-obvious block. No doc-comment boilerplate on
  self-evident functions.
- Ported functions (`cleanMarkdown`, `chunk`) keep the Python implementations'
  structure and comment landmarks so the two stay diffable by eye, and cite the
  server file/commit they were ported from.

## Tests

Mirror packages under `test/` (JVM) and `androidTest/` (instrumented). Test
names are sentences: `resume produces byte-identical output after process kill`.
The shared vector file lives at `engine/text/vectors/pipeline-vectors.json` -
regenerated only from the server repo (30-testing-plan.md).
