# Platform Strategy + Capability Matrix

## Platforms

Android only, phones first (ADR-001). No iOS, tablet, Wear, or Auto in v1. The
"second platform" in this product's life is not iOS - it is the **sotto web
service**, which already exists. The strategy question is parity *with the web
app*, not across mobile OSes.

## What is shared vs native

- **Shared with the server, by contract not code:** the text pipeline.
  `clean_markdown()` and `chunk()` are ported to Kotlin and held equivalent by a
  shared test-vector file generated from the Python implementation
  (30-testing-plan.md). The 7 voices, the 1,000-char chunk limit, the 400 KB
  input cap, and the title-derivation rule are the same constants.
- **Native, deliberately:** everything else. UI is Compose/Material 3 and does
  not imitate the website's look (41-design-system.md); storage is Room +
  app-private files; playback is Media3.

## Capability matrix - sotto-android v1 vs sotto web

| Capability | Android `local` | Android `sync` | Web (sotto.stephens.page) |
|---|---|---|---|
| Works offline | Yes - entirely | Yes (sync needs network, narration doesn't) | No |
| Account required | No | Optional (opt-in connect) | Yes |
| Anything leaves device | No (no INTERNET permission) | Only library entries you upload, to your own server | Text to server; optionally to OpenAI for allowed accounts |
| Library on desktop browser | No | Yes - synced with the server account | Yes |
| Voice backends | Kokoro only | Kokoro only (sync never adds hosted TTS) | Kokoro + gated OpenAI |
| Share-sheet input | Yes - primary entry | Yes | No |
| Lock-screen / headphone controls | Yes (Media3) | Yes | Limited (browser) |
| Long-doc latency | Seconds to first audio (streaming) | Same | Minutes-to-hours batch, preview while running |
| Share links to other people | No (non-goal) | No (create them from the web UI) | Yes, revocable capability links |
| Email-when-done | No (no email, no network) | No | Yes |
| Library | Local, single user | Local + mirrored with server account | Server, per-account |
| Synthesis cost | User's battery | User's battery | Server CPU |
| Update mechanism | New APK (GitHub/F-Droid) | Same | Instant (server deploy) |

## Parity rules

- **Required parity:** text pipeline behavior (vector-tested); voice identity
  (a document narrated by `af_heart` should sound the same from either product);
  naming semantics; honest provenance/About language.
- **Acceptable divergence:** everything UI; stopped-narration semantics (app
  keeps partials, server deletes them - documented in the PRD); features that
  require a server (sharing, email) simply don't exist here.
- **Forbidden convergence:** the `local` flavor must never grow login/network
  features "for parity" - that direction is one-way (ADR-004); only the `sync`
  flavor crosses it, and even there synthesis never moves off-device (ADR-007).
