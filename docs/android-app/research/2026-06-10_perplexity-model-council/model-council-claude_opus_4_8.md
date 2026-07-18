# Turning `lector` into an Android App — A Codebase-Grounded Analysis

*Prepared by Claude Opus 4.8 for the model council. Repository inspected directly via the GitHub connector (`JacobStephens2/lector`, default branch `master`, last pushed 2026-06-10).*

## Executive summary

`lector` is **not** a client-side app that needs "porting" — it is a server-side, server-rendered Python (Flask) web service whose entire reason for existing is a set of *server-enforced trust boundaries* (edge auth, secret isolation, audit trail, a paid-backend allowlist enforced server-side). Three of its five stated design boundaries are meaningless if the logic moves onto a phone. The pragmatic, high-leverage move is therefore **not** to rewrite it in Kotlin or Flutter, but to make the existing web app installable and ship it to Google Play as a **Trusted Web Activity (TWA)** via Bubblewrap/PWABuilder, keeping the server as the single source of truth. A native Kotlin shell becomes worthwhile only if Jacob wants a genuinely *different* product — an **offline, on-device narrator** that runs Kokoro-82M locally on the phone — which the codebase's own architecture (a swappable, localhost Kokoro ONNX backend) makes unusually tractable. This report grounds both paths in what the repo actually is.

---

## 1. What `lector` actually is (after inspecting the repo)

The repository is small and deliberate: GitHub reports it as **100% Python (~70 KB)**, and the file tree is essentially one application file plus a sidecar TTS microservice and systemd deploy units:

```
app.py              # the entire web app: 1,399 lines, single-file Flask monolith
requirements.txt    # Flask>=3.1 — and nothing else (OpenAI call uses stdlib urllib)
kokoro/server.py    # optional local TTS microservice (Kokoro-82M ONNX)
kokoro/requirements.txt  # kokoro-onnx, onnxruntime, misaki[en], lameenc, waitress
deploy/lector.service, deploy/kokoro.service   # systemd units, waitress WSGI
samples/*.mp3       # voice previews
.env.example        # OPENAI_API_KEY, SMTP, base URL
```

**Stack and architecture.** `app.py` is a classic Flask monolith. The README and `app.py` header describe it precisely: paste markdown, get a narrated MP3, self-hosted at `lector.stephens.page` behind a password. Concretely, from the source:

- **Web framework:** Flask 3.1, served in production by **waitress** (`waitress-serve --listen 127.0.0.1:3476 --threads 24`, per `deploy/lector.service`), behind Apache terminating TLS and reverse-proxying — the README spells out the `mod_xsendfile` / `X-Sendfile` integration and the Apache-terminated-TLS topology.
- **UI:** there is no separate frontend. Every page is rendered server-side with Flask's `render_template_string` from Python string constants (`PAGE`, `HOME`, `JOB`, etc.). The only client-side JavaScript is a few hand-written vanilla functions for audio skip controls and polling `/job/<id>/status` (no framework, no build step, no `package.json`, no `node_modules`).
- **Auth & sessions:** email + salted-hash passwords (`werkzeug.security`), signed `HTTPONLY`/`SECURE`/`SameSite=Lax` Flask session cookies, 30-day lifetime, password reset and email-verification tokens, an admin role, and SMTP (Resend by default) for transactional mail.
- **The narration engine:** `clean_markdown()` strips links/URLs, flattens tables, expands acronyms (ADR → "architecture decision record"), and normalizes symbols (`§` → "section", `$` → "dollars") for the ear; `chunk()` splits text under a per-backend input ceiling; `run_job()` runs in a **detached daemon thread**, synthesizes chunk-by-chunk, `fsync`s a partial MP3 after each chunk, mirrors job state to disk (`<id>.json`, `<id>.md.src`, `<id>.mp3`), and **resumes interrupted jobs on restart**. A 10k-word document takes minutes; the HTTP request never blocks on synthesis.
- **TTS backends (the swappable seam):** selected by `LECTOR_TTS_BACKEND`. `tts_openai()` POSTs to `https://api.openai.com/v1/audio/speech` (`gpt-4o-mini-tts`) via stdlib `urllib`; `tts_kokoro()` POSTs to a **localhost** microservice (`http://127.0.0.1:3477/tts`). Both return MP3 bytes and the caller concatenates them identically — a clean abstraction (`tts(text, voice)`) that already treats the speech engine as a pluggable component.
- **The local Kokoro service** (`kokoro/server.py`) wraps **Kokoro-82M ONNX** (`kokoro_onnx`, `onnxruntime`, `misaki[en]` G2P, `espeak-ng` fallback) and encodes MP3 in-process with `lameenc` — no ffmpeg subprocess, no outbound network. Model weights (~360 MB) are downloaded from the `thewh1teagle/kokoro-onnx` releases, not committed.

**The boundaries are the product.** The README is emphatic that this is a "small, honest example of how to wrap an AI automation so a person stays in command of it." Five boundaries: **auth gate**, **secret isolation** (the OpenAI key lives only in a root-owned systemd `EnvironmentFile`, never in the page/repo/browser), **bounded scope** (one outbound call, size-capped input, no shell), **not delegated** (produces audio and stops; only shares when you explicitly create a revocable share link), and **traceability** (every job appends one audit line to `lector.log`). The paid OpenAI backend is gated server-side by `LECTOR_OPENAI_ALLOWED` so "a forged request still cannot bill OpenAI for an account that is not on the list."

**Current platforms:** one — a responsive web app reachable from any browser, including a mobile browser, today. There is **zero** existing mobile code, no Capacitor/Cordova/Tauri config, no `manifest.json`, no service worker.

This characterization matters enormously, because **most of `lector`'s value lives on the server and cannot be moved to a phone without abandoning the very boundaries that justify the project.** "Make it an Android app" is really two different questions, addressed next.

---

## 2. Realistic Android strategies and their trade-offs

I group the options by *where the logic ends up*, because that — not the framework brand — is the decision that actually matters for this codebase.

### Group A — Wrap the existing web app (server stays authoritative)

These keep `app.py` exactly as-is and put an Android entry point in front of it. Code sharing is total because there is nothing to duplicate.

| Approach | What it is | Fit for `lector` | Cost |
|---|---|---|---|
| **PWA only** | Add `manifest.json` + service worker; users "Add to Home Screen" | Trivial; no store presence | Lowest |
| **TWA (Bubblewrap/PWABuilder)** | A thin Android wrapper that opens *your verified site* full-screen in the user's Chrome engine, no browser chrome | **Best fit.** Renders the real site; auto-updates server-side; ~free | Low |
| **WebView wrapper (Median/Capacitor `WebView`)** | A native `Activity` hosting a `WebView` pointed at the URL | Works, but you own a stale browser engine and risk Play's "repackaged website" scrutiny | Low–medium |
| **Capacitor (web assets bundled)** | Bundle a web build into the APK, call native plugins | Designed for *client-rendered SPAs*; `lector` is server-rendered, so you'd either bundle nothing useful or point Capacitor's WebView at the remote URL (≈ WebView wrapper) | Medium |

The **TWA** is the standout. Per Google's own documentation, a TWA "lets your Android App launch a full screen Browser Tab without any browser UI," renders content with the user's actual Chrome engine (not a bundled WebView), verifies you own the domain via **Digital Asset Links**, and updates independently of the app — so site changes ship without an app update ([Android Developers — TWA Quick Start](https://developer.android.com/develop/ui/views/layout/webapps/guide-trusted-web-activities-version2), [Chrome for Developers — Trusted Web Activity](https://developer.chrome.com/docs/android/trusted-web-activity)). **Bubblewrap** is Google's official CLI that turns a PWA manifest into a signed Android App Bundle (`bubblewrap init --manifest=...`), and **PWABuilder** provides a GUI over the same machinery ([Google Codelab — PWA in Play](https://developers.google.com/codelabs/pwa-in-play), [GoogleChromeLabs/bubblewrap](https://github.com/googlechromelabs/bubblewrap)). Crucially, Google Play *officially accepts* PWAs via TWA — unlike Apple, which rejects repackaged-website PWAs under Guideline 4.2 ([MobiLoud — Publishing a PWA to the stores, 2026](https://www.mobiloud.com/blog/publishing-pwa-app-store)).

The trade-off: a TWA is still a web app, so it inherits the server dependency (no offline narration) and Play's TWA quality bar — installability criteria (manifest, HTTPS, service worker with a fetch handler), a **Lighthouse score ≥ 80**, and verified Digital Asset Links. Since Chrome 86, three runtime conditions are treated as *app crashes* in Android Vitals: failed Digital Asset Links verification at launch, failure to return HTTP 200 for an offline resource, and any 404/5xx in the app ([MobiLoud](https://www.mobiloud.com/blog/publishing-pwa-app-store)).

### Group B — Rewrite the client, keep (or shrink) the server

These rebuild the UI natively and talk to `lector`'s endpoints as an API.

- **Kotlin / Jetpack Compose native app.** Jacob writes Kotlin, so a native client is squarely in his wheelhouse. But `lector` exposes **HTML pages, not a JSON API** — `/convert` returns a redirect, `/job/<id>/status` returns JSON but the rest is server-rendered forms. A native client would require Jacob to *first carve a JSON/REST API out of `app.py`*, then rebuild login, the editor, voice picker, job polling, the Library, and share management in Compose. That is a real product rewrite for a single-file hobby service, and it duplicates logic that already works.
- **Kotlin Multiplatform (KMP).** Jacob is interested in KMP. KMP shines when you have substantial *business logic* to share across Android/iOS/desktop. `lector`'s business logic (markdown cleaning, chunking, TTS orchestration, auth) lives in Python on a server; there is almost nothing to "share" with a KMP module unless he re-implements `clean_markdown`/`chunk` in Kotlin. KMP would be the right choice for the **offline on-device** product (Group C), not for wrapping the current service. In the cross-platform comparisons, KMP is favored when teams want native UI per platform with shared Kotlin logic, while Flutter wins on single-codebase UI velocity ([Shorebird — Flutter vs Kotlin Multiplatform, 2026](https://shorebird.dev/blog/flutter-vs-kotlin-multiplatform), [KMPShip — KMP vs Flutter vs RN, 2025](https://www.kmpship.app/blog/kmp-vs-flutter-vs-react-native-2025)).
- **Flutter / React Native rewrite.** Same objection as native Kotlin, plus a new language/runtime (Dart) and no reuse of the existing Python. Flutter is excellent for greenfield cross-platform UI, but here it means throwing away a working server-rendered UI to rebuild it, then maintaining two stacks. Justified only if iOS + Android + a single shared UI is a hard requirement — which the brief does not state.

### Group C — Move the engine onto the device (a *different* product)

This is the most interesting option intellectually, and the one the codebase quietly enables. Because `lector` already abstracts TTS behind a swappable backend and *already ships a Kokoro-82M ONNX path*, an Android app could embed that model and synthesize **entirely offline, on-device** — no server, no API key, no per-call billing, and (notably) the "secret isolation" and "paid-backend allowlist" boundaries simply evaporate because there is no secret and no paid call.

This is demonstrably feasible: **ONNX Runtime Mobile** runs ONNX models on Android with the same API as the cloud, in Kotlin/Java, via the `com.microsoft.onnxruntime:onnxruntime-mobile` Maven artifact (models converted to ORT format to shrink the binary) ([ONNX Runtime — Inference](https://onnxruntime.ai/inference), [Maven Central — onnxruntime-mobile](https://central.sonatype.com/artifact/com.microsoft.onnxruntime/onnxruntime-mobile)). And someone has already proven Kokoro specifically: **`puff-dayo/Kokoro-82M-Android`** is a working Kotlin demo running Kokoro-82M in **int8 quantization** on-device ([puff-dayo/Kokoro-82M-Android](https://github.com/puff-dayo/Kokoro-82M-Android)), built on the same `thewh1teagle/kokoro-onnx` int8 model `lector` already downloads, and Kokoro is distributed with first-class ONNX/quantized variants (`q8`, `q4`, fp16) by the community ([onnx-community/Kokoro-82M-v1.0-ONNX](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX)). The catch is the G2P front-end: `lector`'s server uses `misaki[en]` + `espeak-ng`, which you'd need to reproduce on-device (bundle a phonemizer or pre-process server-side).

A *much* cheaper variant of Group C exists: skip Kokoro and use Android's built-in **`TextToSpeech` engine** (`android.speech.tts`) for synthesis ([Android Developers — TextToSpeech.Engine](https://developer.android.com/reference/android/speech/tts/TextToSpeech.Engine)). You'd reuse `lector`'s real intellectual property — the markdown-for-the-ear cleaning rules — ported to Kotlin, and let the OS voice speak it. It loses Kokoro's voice quality and provenance story (which is half the point of the project), so it's a downgrade on `lector`'s own values.

---

## 3. Recommended path

**Primary recommendation: ship the existing web app to Google Play as a TWA built with Bubblewrap, after a small PWA-enablement pass.** This is the only option that respects what `lector` *is*.

The justification is structural, straight from the source:

1. **The boundaries demand a server.** Secret isolation (OpenAI key in a root-owned `EnvironmentFile`), the server-side `LECTOR_OPENAI_ALLOWED` allowlist that prevents forged billing, the centralized `lector.log` audit trail, and signed-session auth are all *server-enforced by design*. Any native rewrite that moves logic to the phone weakens or discards exactly the properties the README says are "the point." A TWA keeps every line of `app.py` authoritative and untouched.
2. **The UI is already mobile-friendly and server-rendered.** The `PAGE` CSS uses a `max-width:46rem` responsive layout with `viewport` meta and system fonts; it already works on a phone browser. There is no SPA to bundle and no client logic to reimplement — making a Capacitor/native rewrite pure cost with no reuse.
3. **Effort/reward is overwhelmingly favorable.** Bubblewrap turns the site into a signed `.aab` in a couple of commands ([Google Codelab](https://developers.google.com/codelabs/pwa-in-play)); the app auto-updates whenever Jacob deploys the server, so there is no perpetual app-release treadmill ([Android Developers — TWA](https://developer.android.com/develop/ui/views/layout/webapps/guide-trusted-web-activities-version2)).
4. **It fits the project's spirit.** `lector` is a deliberately small "honest example." A TWA is the proportionate amount of new surface area; a Flutter/KMP rewrite is not.

**Secondary recommendation (the ambitious fork):** if Jacob's actual goal is "narrate documents on a walk *without* a server or connectivity," then build a **separate native Android app** — Jetpack Compose UI + ONNX Runtime Mobile running Kokoro-82M int8 on-device, porting `clean_markdown`/`chunk` to Kotlin and bundling/downloading the quantized model. This is a genuinely new product (offline, private-by-construction) and is well-supported by precedent ([puff-dayo/Kokoro-82M-Android](https://github.com/puff-dayo/Kokoro-82M-Android), [ONNX Runtime Mobile](https://onnxruntime.ai/inference)). If he ever wants iOS too, *this* is where **KMP** earns its place: a shared Kotlin module for cleaning + ONNX orchestration with platform-native UI. Treat it as v2, not a replacement for the TWA.

---

## 4. Implementation outline — the recommended TWA path

**Phase 0 — PWA-enable the site (small `app.py` additions).**
- Add a `GET /manifest.json` route returning name, `short_name`, `start_url:"/"`, `display:"standalone"`, theme/background colors (reuse the brand navy `#002A4F` already in the favicon), and maskable icons (192px + 512px PNGs derived from the existing SVG speaker mark).
- Add a minimal **service worker** (`/sw.js`) with a `fetch` handler — Play's TWA quality check requires one, and it must return HTTP 200 for an offline resource to avoid the Android Vitals "crash" condition ([MobiLoud, 2026](https://www.mobiloud.com/blog/publishing-pwa-app-store)). A bare network-first SW with an offline fallback page is sufficient; do **not** try to cache narration audio.
- Add `<link rel="manifest">` and a `theme-color` meta to the `PAGE` template head.
- Run **Lighthouse** and clear ≥ 80; fix any installability gaps it flags ([MobiLoud](https://www.mobiloud.com/blog/publishing-pwa-app-store)).

**Phase 1 — Generate the Android package.**
- Install Bubblewrap (`npm i -g @bubblewrap/cli`) and run `bubblewrap init --manifest=https://lector.stephens.page/manifest.json` ([Google Codelab](https://developers.google.com/codelabs/pwa-in-play), [bubblewrap repo](https://github.com/googlechromelabs/bubblewrap)). PWABuilder is the GUI alternative if preferred.
- Choose **Play App Signing** (recommended): let Google hold the app signing key; Jacob keeps the upload key. `bubblewrap build` produces `app-release-bundle.aab`.

**Phase 2 — Digital Asset Links (the #1 cause of failure).**
- Verification uses the SHA-256 fingerprint of the key that *signs the package the user receives*. With Play App Signing, get it from **Play Console → Releases → Setup → App Integrity** (it differs from the upload key) ([Google Codelab](https://developers.google.com/codelabs/pwa-in-play)).
- Serve `/.well-known/assetlinks.json` from `lector.stephens.page` with that fingerprint and the package name. Add a Flask route for it. If verification fails, Chrome silently falls back to a Custom Tab *with* browser chrome — the tell-tale sign of a broken asset-links setup ([Android Developers — TWA](https://developer.android.com/develop/ui/views/layout/webapps/guide-trusted-web-activities-version2)).

**Phase 3 — Play Console submission.**
- Create a **Play Console developer account** ($25 one-time). Note the **2026 developer-verification regime**: verification opened to all developers in **March 2026**, requiring legal name, address, email, phone (and government ID may be requested); personal accounts verify a developer email, organizations need a D-U-N-S number ([Android Developers — Developer verification](https://developer.android.com/developer-verification), [Play Console — required developer info](https://support.google.com/googleplay/android-developer/answer/13628312)). Jacob should complete identity verification *early* — it gates publishing.
- Ensure the `.aab` meets the **target API level** rule: as of the 2025 cycle, apps had to target **Android 14 (API 34)+**, and the bar ratchets up annually, so target the current required level Bubblewrap defaults to ([Play target-API requirements](https://support.google.com/googleplay/android-developer/answer/11926878), [Android Developers — target SDK](https://developer.android.com/google/play/requirements/target-sdk)).
- Upload via **internal testing** first (add yourself as a tester), install from the testing link, confirm the app opens full-screen with **no browser toolbar** (proves asset-links verified), then promote to production.

**Gotchas, specific to `lector`:**
- **`MAX_CONTENT_LENGTH` 413s.** `app.py` caps input at 400 KB and returns a plain `413`. In a TWA that 413 would otherwise look like an app error; ensure the upload UX surfaces it gracefully (it already returns a readable message — keep it a 200-rendered page, not a raw error, where feasible, to avoid Android Vitals penalizing 4xx/5xx).
- **Long jobs + standalone display.** Synthesis runs server-side in a daemon thread and the job page polls `/job/<id>/status`; this works unchanged in a TWA, but verify the polling JS tolerates the app being backgrounded on mobile (Chrome may throttle timers).
- **Audio playback & downloads.** The `<audio>` element and `/job/<id>/audio` `send_file` work in the TWA's Chrome engine; the `X-Sendfile` path is server-side and unaffected.
- **Share links** remain server-controlled and revocable exactly as today — the "not delegated" boundary is preserved.
- **No offline.** Be honest in the listing: it needs connectivity (the SW should show a clean offline page, not a spinner).

---

## 5. Maintenance, CI/CD, and code-sharing implications

**With the TWA path, the maintenance story is almost a non-event — which is the point.**

- **Code sharing is 100%.** There is no second codebase. The Android artifact is a thin signed wrapper; all features, fixes, and copy changes ship by deploying `app.py` to the server. The app re-renders the live site, so you do **not** rebuild or re-upload the `.aab` for content/feature changes — only for wrapper-level changes (package name, icons, min-SDK, manifest URL) ([Android Developers — TWA, independent updates](https://developer.android.com/develop/ui/views/layout/webapps/guide-trusted-web-activities-version2)).
- **CI/CD.** Keep the existing systemd/waitress deploy for the server. Add a *lightweight* GitHub Actions job that runs Bubblewrap to rebuild and (optionally) upload a fresh `.aab` to a Play internal track only when wrapper config changes — gated behind a manual workflow dispatch, since it should rarely fire. Store the upload key as an encrypted secret; rely on Play App Signing for the distribution key so a lost upload key is recoverable.
- **Ongoing obligations.** Two recurring chores: (1) bump the **target API level** roughly annually to stay distributable to new devices ([Play target-API requirements](https://support.google.com/googleplay/android-developer/answer/11926878)); (2) keep **Digital Asset Links** valid if the signing key ever changes, and keep the site's Lighthouse/installability green so it doesn't trip Android Vitals "crash" conditions ([MobiLoud, 2026](https://www.mobiloud.com/blog/publishing-pwa-app-store)). Both are minutes of work per year.
- **Add a JSON API later, cheaply.** If a future native/KMP client (Group C) materializes, the clean move is to expose the handful of actions (`/convert`, status, library) as JSON endpoints alongside the existing HTML routes — `app.py` is small enough that this is a focused change, not a rewrite. That keeps the door open to KMP code-sharing for the offline product without committing to it now.

**If Jacob instead pursues the native offline fork (Group C):** code sharing becomes the central design question. Port `clean_markdown`/`chunk` once into a **KMP shared module** (pure Kotlin, no platform deps), drive ONNX Runtime Mobile from it, and you get reuse across Android (and later iOS) with native UIs — the textbook KMP sweet spot ([Shorebird, 2026](https://shorebird.dev/blog/flutter-vs-kotlin-multiplatform)). CI/CD then grows real teeth (Gradle builds, model-asset management, signing, per-platform test matrices), and the two products — server `lector` and offline `lector-go` — would deliberately *not* share code, only the narration rules. That divergence is acceptable precisely because they serve different trust models: the server app's value is its boundaries; the offline app's value is that it needs none.

---

### Bottom line

`lector` is a server-rendered Flask service whose worth is its server-side boundaries; the right "Android app" is a **Trusted Web Activity wrapper via Bubblewrap**, which ships to Play in days, preserves every boundary, and auto-updates from the server with near-zero ongoing code. Reserve a native **Kotlin + ONNX Runtime Mobile (Kokoro-82M on-device)** build — optionally KMP-shared for later iOS — for the genuinely different, *offline* product, not as a replacement for the service that already works.
