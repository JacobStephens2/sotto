# Concept Brief - Sotto for Android

**Name:** Sotto (decided 2026-06-12; from *sotto voce* - quietly, privately -
the narrator that speaks only to you). Display name "Sotto", repo
`sotto-android`, package `page.stephens.sotto`. The whole product family is
renamed Sotto: the web service lives at sotto.stephens.page.

**One sentence:** Share any text to your phone and listen to it as a private,
locally synthesized narration - no account, no server, no network.

## Problem

Long documents (plans, specs, articles, encyclicals) are easier to absorb on a
walk than at a desk. The sotto web service solves this on a server you trust;
it still requires an account, a connection, and trusting that server. On a phone
the text you want read is usually already *on the phone* - sending it anywhere is
unnecessary work and an unnecessary disclosure.

## Target user

1. Me (Jacob) - daily long-document listening, replacing the web flow for
   on-phone text.
2. Privacy-conscious readers who want text-to-speech without a cloud dependency -
   the audience the sotto README's "boundaries" section already speaks to.

## Value proposition

The strongest version of sotto's thesis. The web service says "the key never
leaves the server." This app's `local` flavor says **"nothing leaves the
device"** - and the AndroidManifest proves it, because that build does not hold
the INTERNET permission (ADR-004). The claim is falsifiable by anyone with
`aapt dump permissions`. The `sync` flavor (ADR-007) trades that one property,
explicitly and only on connection, for the second value proposition: **one
library on both your phone and your desktop browser**, synced with your own
sotto server - narration still happens entirely on-device.

## Design pillars

1. **Share-sheet first.** The primary entry is Android's share sheet: select text
   anywhere, share a `.md`/`.txt` file, get a narration. The in-app paste box is
   secondary.
2. **Listen now, not later.** Synthesis streams just ahead of the playhead
   (ADR-003). First audio in seconds, even for a 40,000-word document.
3. **Boundaries you can verify.** No account, no key, no network permission, a
   local job log, synthetic-voice disclosure in About. The seven-boundary
   checklist from the sotto README, translated to a device (constitution.md).
4. **A real audio app.** Lock-screen and headphone controls, position memory,
   15-second skips, sleep timer. Listening on a walk is the whole point.

## Primary use cases

- Share selected text from a browser/reader app → it starts narrating.
- Share or open a `.md`/`.txt` file → named oration lands in the local library.
- Paste markdown into the app → same.
- Reopen the app days later → library list, resume where you stopped.

## Primary use cases (continued)

- Connect a sotto server account (`sync` flavor): download server orations for
  offline listening; upload phone-made orations to work with them in a desktop
  browser.

## Non-goals (v1)

- No network code in the `local` flavor - ever (ADR-004). Sync exists only as
  the separate `sync` artifact (ADR-007).
- No hosted synthesis from the app: even the `sync` flavor narrates on-device
  only; it moves finished orations, it never sends text away to be voiced.
- No OpenAI or any hosted voice backend.
- No iOS, no tablet-optimized layout, no Wear.
- No in-app document editing beyond the paste box.
- No EPUB/PDF extraction (share plain text or markdown; extraction can come later).
- Not a replacement for the web service - the server remains the right tool for
  shared libraries, share links, and email-me-when-done workflows.

## Why this product, in one paragraph

Three independent model councils (docs/android-app/research, 2026-06-10) agreed
the sotto web service should stay server-side and be packaged as a PWA/TWA - and
agreed that an on-device narrator is "a genuinely different product," made
tractable by quantized Kokoro-82M weights (~80-170 MB int8) and the
puff-dayo/Kokoro-82M-Android precedent. This is that different product, built as
a plain Kotlin/Compose app (ADR-001) - the one mobile stack not yet represented
in my portfolio - with on-device inference as the distinguishing engineering
story.
