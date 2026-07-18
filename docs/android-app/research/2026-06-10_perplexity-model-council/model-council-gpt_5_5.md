# GPT-5.5 research: How Jacob should turn `lector` into an Android app

## Executive recommendation

Jacob should **not rewrite `lector` in Kotlin, Flutter, React Native, Tauri, or on-device Python for the first Android release**; the repository is already a server-backed, mobile-friendly Flask web application whose core value lives in server-side auth, secret isolation, background TTS jobs, library storage, and share links rather than in device-native computation ([GitHub repository](https://github.com/JacobStephens2/lector), [README](https://github.com/JacobStephens2/lector/blob/master/README.md), [app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

The best path is a **two-phase web-first mobile strategy**: first add PWA metadata/offline polish to the existing Flask app, then publish it to Android as a **Trusted Web Activity (TWA)** via Bubblewrap if a Play Store artifact is actually needed ([Chrome TWA quick start](https://developer.chrome.com/docs/android/trusted-web-activity/quick-start), [Google PWA-in-Play codelab](https://developers.google.com/codelabs/pwa-in-play)).

If Jacob later wants native Android features that PWAs/TWAs cannot deliver cleanly—richer file integration, foreground media-service behavior, custom notifications, native share-sheet flows, or eventually iOS parity—he should graduate to **Capacitor or a Kotlin/Compose client over a real JSON API**, not port the current Flask process into Android ([Capacitor Android docs](https://capacitorjs.com/docs/android), [Kotlin Multiplatform overview](https://kotlinlang.org/docs/multiplatform/kmp-overview.html)).

## 1. What `lector` actually is

`lector` is a public GitHub repository owned by `JacobStephens2`, described as a “Self-hosted markdown-to-narration TTS service” with edge/auth boundaries, secret isolation, audit trail, and provenance honesty, and GitHub classifies its primary language as Python ([GitHub repository](https://github.com/JacobStephens2/lector)).

The repository is intentionally small and server-centric: it contains `README.md`, a single large `app.py`, Python dependencies, systemd deployment units, a `kokoro/` local TTS microservice, and committed MP3 voice samples; there is no Android project, Gradle build, Flutter project, React Native project, Capacitor config, Tauri config, package.json, or separate frontend app in the inspected tree ([GitHub repository](https://github.com/JacobStephens2/lector)).

The main app is a Flask web server that accepts pasted or uploaded Markdown, cleans it for spoken output, chunks it, sends chunks to a TTS backend, writes progress to disk, serves partial and final MP3s, saves library entries with source Markdown sidecars, handles account/login/admin flows, and exposes share links through routes such as `/convert`, `/job/<job_id>`, `/library`, and `/share/<token>` ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

The README says `lector` supports two TTS backends selected by `LECTOR_TTS_BACKEND`: a local Kokoro-82M ONNX service and hosted OpenAI `gpt-4o-mini-tts`, with OpenAI gated by `LECTOR_OPENAI_ALLOWED` so unauthorized accounts cannot incur API charges ([README](https://github.com/JacobStephens2/lector/blob/master/README.md)).

The code enforces that architecture server-side: `OPENAI_API_KEY` is read only from the server environment, Kokoro requests go to `http://127.0.0.1:3477/tts`, the OpenAI voice list is separate from the Kokoro voice list, unauthorized OpenAI voice selection falls back to Kokoro, and the app uses CSRF-protected Flask forms rather than a client API token model ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

The UI is not a SPA; it is server-rendered HTML defined inside `app.py` with inline CSS, a viewport meta tag, native `<audio>` controls, a Markdown `<textarea>`, a file input, voice sample players, lightweight `fetch()` polling for job progress, and responsive-ish flexbox layout ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

The deployment model is also server-first: `lector.service` runs `waitress-serve` on `127.0.0.1:3476`, Apache terminates TLS and reverse-proxies to it, and `kokoro.service` runs a separate local service on `127.0.0.1:3477` with CPU and memory limits ([README](https://github.com/JacobStephens2/lector/blob/master/README.md), [deploy/lector.service](https://github.com/JacobStephens2/lector/blob/master/deploy/lector.service), [deploy/kokoro.service](https://github.com/JacobStephens2/lector/blob/master/deploy/kokoro.service)).

The Kokoro microservice wraps Kokoro-82M ONNX, loads model and voice files at startup, exposes `POST /tts`, `GET /voices`, and `GET /healthz`, and encodes generated speech to MP3 in-process with `lameenc` ([kokoro/server.py](https://github.com/JacobStephens2/lector/blob/master/kokoro/server.py)).

The local Kokoro README notes that the model weights are roughly 330–360 MB and that one hour of output can take roughly 40 minutes on the referenced 4-core CPU-only box, which makes bundling the whole synthesis path into a mobile app unattractive for a first release ([kokoro/README.md](https://github.com/JacobStephens2/lector/blob/master/kokoro/README.md)).

## 2. Android strategies compared against the actual codebase

| Strategy | Fit for current `lector` | Strengths | Weaknesses / gotchas | Verdict |
|---|---:|---|---|---|
| Mobile web only | Very high | Zero Android code, preserves server auth/secrets/jobs, fastest validation | No Play Store listing, no app icon unless installed as PWA | Do first regardless |
| TWA / PWA in Play | Very high | Minimal native shell; uses verified owned HTTPS origin; Bubblewrap creates Android project and Play bundle | Requires manifest, service worker/offline behavior, Digital Asset Links, Play policy work | Recommended first Play path |
| Plain native WebView wrapper | Medium | Full Kotlin control over downloads, back button, JS bridge, permissions | You own WebView security/navigation/download details; weaker than TWA for a pure website | Only if TWA cannot meet UX needs |
| Capacitor | Medium-high after modest refactor | Web-native runtime, Android Studio project, Kotlin plugins, native APIs when needed | Current app has no JS build pipeline or static frontend bundle; remote-server Capacitor shell is less compelling than TWA | Best phase-2 hybrid path |
| Tauri Mobile | Low-medium | Rust + WebView architecture fits Jacob’s Rust skills | Current app is Python/Flask, not Rust + bundled frontend; mobile Tauri adds toolchain complexity without sharing core code | Not for first Android release |
| Kotlin native / KMP | Medium long-term | Best Android UX and media/file integration; KMP can later share logic/UI with iOS | Requires extracting API and rewriting UI; no reason to port server TTS/auth logic into app | Strong long-term rewrite option, not first move |
| Flutter | Medium long-term | Good cross-platform UI, quick iteration, strong ecosystem | Complete UI rewrite and still needs server APIs; WebView-in-Flutter is worse than TWA for first release | Consider only if Jacob wants Flutter practice/iOS parity |
| React Native | Low | Native-ish UI and JS ecosystem | No existing React/TypeScript code; rewrite plus API extraction | Low fit |
| Python-on-Android | Low | Could reuse some Python text-cleaning logic | Flask-in-app is awkward; server secrets cannot ship; Kokoro model is large; Play packaging complexity | Avoid |

A TWA is specifically designed to let an Android app launch an owned web app fullscreen without browser UI, and ownership is proven through Digital Asset Links verification ([Chrome TWA quick start](https://developer.chrome.com/docs/android/trusted-web-activity/quick-start)).

Bubblewrap reads a PWA Web App Manifest, generates a TWA Android project, and can build artifacts such as `app-release-bundle.aab` for Play and `app-release-signed.apk` for device testing ([Google PWA-in-Play codelab](https://developers.google.com/codelabs/pwa-in-play)).

That maps unusually well to `lector` because the app already runs at `https://lector.stephens.page`, already has HTTPS, already handles login and server-side sessions, and already keeps sensitive OpenAI/Kokoro execution on the server ([README](https://github.com/JacobStephens2/lector/blob/master/README.md)).

A plain Android WebView wrapper is technically viable, but Android’s own WebView guidance says JavaScript is disabled by default, `INTERNET` permission must be declared, links require explicit `WebViewClient` handling if they should stay inside the app, and popup/multiple-window behavior must be controlled carefully ([Android WebView docs](https://developer.android.com/develop/ui/views/layout/webapps/webview)).

Capacitor is attractive only after Jacob wants native integrations because Capacitor’s Android runtime lets JavaScript communicate with native Java or Kotlin and supports Android API 24+ through the system WebView model ([Capacitor Android docs](https://capacitorjs.com/docs/android)).

Capacitor’s standard workflow assumes built web assets that are synced into native projects with `npx cap sync`, which is not how the current Flask/Jinja app is structured today ([Capacitor workflow docs](https://capacitorjs.com/docs/basics/workflow)).

Tauri Mobile is powerful but misaligned for this repo because Tauri opens a webview displaying a web app after Rust builds and its mobile distribution path centers on `tauri android` projects and Rust libraries loaded into the app runtime ([Tauri develop docs](https://v2.tauri.app/develop/)).

Tauri can build Android bundles for Google Play and supports Android 7.0 / SDK 24 minimum, but its first-upload and release automation story still has manual Play Console caveats ([Tauri Google Play docs](https://v2.tauri.app/distribute/google-play/)).

Kotlin Multiplatform is a good later direction if Jacob wants durable Android/iOS native clients because KMP can share business logic, networking, storage, and optionally Compose Multiplatform UI across Android, iOS, desktop, web, and server ([KMP overview](https://kotlinlang.org/docs/multiplatform/kmp-overview.html)).

Compose Multiplatform currently supports Android with minimum Android 5.0/API 21 and iOS 14, but adopting it would be a real client rewrite rather than a packaging step ([Compose Multiplatform compatibility](https://kotlinlang.org/docs/multiplatform/compose-compatibility-and-versioning.html)).

Flutter is also a credible rewrite option if the goal is learning Dart/Flutter or building a polished cross-platform client, and Flutter’s official WebView plugin uses Android WebView and supports Android SDK 24+ ([webview_flutter package](https://pub.dev/packages/webview_flutter)).

React Native is a weaker fit because the repository has no React frontend, even though React Native itself renders platform-native UI and Expo includes `react-native-webview` for native WebView use cases ([React Native docs](https://reactnative.dev/), [Expo WebView docs](https://docs.expo.dev/versions/latest/sdk/webview/)).

BeeWare, Kivy, and Chaquopy show that Python Android packaging is possible, but those paths solve a different problem and do not remove `lector`’s need to protect server credentials, run long TTS jobs, store libraries, and avoid shipping heavyweight TTS model assets to each phone ([BeeWare Android publishing](https://briefcase.beeware.org/en/stable/how-to/publishing/android/), [Kivy Android docs](https://kivy.org/doc/stable/guide/android.html), [Chaquopy](https://chaquo.com/chaquopy/)).

## 3. Recommended path: PWA hardening + TWA Play wrapper

The recommended first Android product should be **“Lector Mobile”: the existing server app, optimized as an installable PWA and packaged as a TWA for Play**.

This path preserves the repo’s strongest design choice—server-side authority over secrets, billing boundaries, account permissions, audit logs, and generated files—rather than moving sensitive or expensive work into a client binary ([README](https://github.com/JacobStephens2/lector/blob/master/README.md), [app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

It also minimizes wasted rewrite effort because the current UI already uses normal browser primitives that are mobile-compatible: HTML forms, file upload, native audio controls, simple polling, downloads, and responsive layout constraints ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

The only near-term product work needed before packaging is mobile polish: add a manifest, icons, splash/theme metadata, offline fallback, better small-screen layout around voice samples, and explicit privacy/account-deletion affordances.

For a private or semi-private tool, Jacob may not even need Play Store distribution; a home-screen-installed PWA from `lector.stephens.page` may be sufficient after the same manifest and service-worker work.

For a public Play listing, TWA is better than a handcrafted WebView because TWA uses a verified owned origin and Android browser infrastructure instead of asking Jacob to maintain a custom WebView shell and navigation/security surface ([Chrome TWA quick start](https://developer.chrome.com/docs/android/trusted-web-activity/quick-start)).

## 4. Step-by-step implementation outline

### Milestone 0 — Decide distribution scope

If the app is just for Jacob and a small trusted group, ship a polished PWA first and skip Play until there is a clear reason for a store listing.

If Play distribution is desired, choose a stable package name such as `page.stephens.lector`, a public app name, a support email, and a privacy policy URL before creating a Play Console app.

### Milestone 1 — Make the Flask app a real PWA

Add a `GET /manifest.webmanifest` route or static file with `name`, `short_name`, `start_url`, `scope`, `display: "standalone"`, `theme_color`, `background_color`, and icons including maskable 192×192 and 512×512 PNG assets.

Add `<link rel="manifest" href="/manifest.webmanifest">`, `theme-color`, and platform icon tags in the existing `PAGE` template near the current favicon link ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

Add a service worker that caches only safe shell assets such as the favicon, icons, manifest, and an offline page; do **not** cache private `/job`, `/library`, `/share`, audio, Markdown, or authenticated HTML responses because `lector` handles private user documents and generated MP3s ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

Add `Cache-Control: no-store` or equivalent headers for authenticated document/audio routes if they are not already controlled by the reverse proxy.

Improve the current inline CSS for narrow screens by shrinking voice sample cards, avoiding 12.5rem audio controls in multi-column overflow, making the nav wrap cleanly, and making the main textarea usable on phone keyboards ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

Add Web App Manifest screenshots only if using modern Play/PWA presentation assets, and generate store-quality icons from the existing SVG speaker favicon idea ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

### Milestone 2 — Add mobile-product niceties in the web layer

Use the Media Session API for title/artist/artwork metadata and basic playback action handlers where supported, because `lector`’s primary artifact is an MP3 played through browser audio controls.

Make “Save to Library,” “Download MP3,” and share-link creation easier on phones by moving those controls closer to the audio player after completion.

Consider adding an optional “send me email when ready” default per-account preference, because the current job model already continues on the server after the user leaves the page ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

Do not add push notifications in the first pass unless email becomes insufficient, because Web Push/TWA notification plumbing adds Firebase/browser-policy complexity without changing core app value.

### Milestone 3 — Generate the TWA project with Bubblewrap

Create an Android wrapper directory such as `android-twa/` at repo root, then initialize Bubblewrap against the production manifest: `bubblewrap init --manifest=https://lector.stephens.page/manifest.webmanifest` ([Chrome TWA quick start](https://developer.chrome.com/docs/android/trusted-web-activity/quick-start)).

Commit `twa-manifest.json` and either commit the generated Android project for reproducibility or document regeneration from `twa-manifest.json`; Google’s codelab specifically calls out `twa-manifest.json` as version-control-worthy configuration ([Google PWA-in-Play codelab](https://developers.google.com/codelabs/pwa-in-play)).

Build and test locally with `bubblewrap build` and `bubblewrap install`, then verify that login, Markdown upload, conversion, job polling, audio preview, library playback, downloads, and share links work on a real Android device ([Chrome TWA quick start](https://developer.chrome.com/docs/android/trusted-web-activity/quick-start)).

Handle Android back navigation expectations by verifying that the TWA/browser history stack behaves correctly from job pages, library entries, share pages, and login redirects.

### Milestone 4 — Digital Asset Links and verification

After signing is decided, generate the Digital Asset Links file and serve it from `https://lector.stephens.page/.well-known/assetlinks.json`, because TWA verification fails back to a Custom Tab if Digital Asset Links do not match ([Chrome TWA quick start](https://developer.chrome.com/docs/android/trusted-web-activity/quick-start)).

If using Play App Signing, copy the SHA-256 fingerprint from Play Console’s App Integrity section and add it with `bubblewrap fingerprint add <fingerprint>`, because the certificate used on user devices can differ from the local upload key ([Google PWA-in-Play codelab](https://developers.google.com/codelabs/pwa-in-play)).

Keep the upload keystore out of Git, store it in a password manager or CI secret store, and document key ownership because the signing key proves that Play artifacts come from Jacob ([Google PWA-in-Play codelab](https://developers.google.com/codelabs/pwa-in-play)).

### Milestone 5 — Play Store readiness

Build an Android App Bundle, because Google Play uses app bundles to generate optimized APKs for each device configuration and app bundles defer APK generation/signing to Google Play ([Android App Bundle docs](https://developer.android.com/guide/app-bundle)).

Ensure the generated Android project targets the current required API level, because Google Play requires new apps and updates submitted after August 31, 2025 to target Android 15/API 35 or higher ([Google Play target API requirements](https://developer.android.com/google/play/requirements/target-sdk)).

Complete the Play Data safety form carefully: `lector` collects email addresses for accounts, files/docs via pasted or uploaded Markdown, generated audio files, app interactions/job metadata, and possibly shares text with OpenAI when authorized accounts choose OpenAI voices ([Google Play Data safety help](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en), [README](https://github.com/JacobStephens2/lector/blob/master/README.md)).

The Data safety form should disclose webview-controlled data collection where relevant, because Google says developers must disclose data collected from a WebView opened from the app when the app controls the code or behavior delivered through that WebView ([Google Play Data safety help](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en)).

Add an easily discoverable account/data deletion mechanism such as `/account/delete` or a dedicated deletion-request email, because Play asks whether the app provides a way for users to request deletion of their data ([Google Play Data safety help](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en)).

Create an internal testing release first, because Google’s PWA-in-Play flow describes internal testing as a quick way to release to trusted testers before broader rollout ([Google PWA-in-Play codelab](https://developers.google.com/codelabs/pwa-in-play)).

## 5. Gotchas specific to `lector`

Do not expose `OPENAI_API_KEY` in any Android binary, WebView bridge, bundled JavaScript, or Capacitor/Tauri config; the current server-only `EnvironmentFile` model is exactly the right boundary ([README](https://github.com/JacobStephens2/lector/blob/master/README.md), [.env.example](https://github.com/JacobStephens2/lector/blob/master/.env.example)).

Do not cache authenticated HTML, Markdown sidecars, MP3s, or share pages in a service worker unless you build explicit per-user encrypted/offline semantics, because the current library and share-link model treats documents and audio as private server resources ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

Do not try to run Kokoro locally on-device for v1; the repo’s own Kokoro documentation describes large model weights and long CPU synthesis times on a 4-core server, and Android app size/performance/battery implications would dominate the project ([kokoro/README.md](https://github.com/JacobStephens2/lector/blob/master/kokoro/README.md)).

Do not move job execution to Android background services unless the product goal changes; the current design intentionally lets jobs run on the server while users close the page and optionally receive email when ready ([README](https://github.com/JacobStephens2/lector/blob/master/README.md), [app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

Do not assume a TWA gives all native app affordances; if foreground audio playback controls, download manager integration, or app-private offline libraries become must-haves, plan a second-phase native shell or client rewrite.

## 6. Maintenance, CI/CD, and code-sharing implications

For the recommended TWA/PWA path, the server remains the source of truth and Android maintenance is mostly metadata, signing, target SDK updates, Digital Asset Links, and Play policy compliance.

Add server CI around the existing Python app: run lint/type checks if desired, unit-test `clean_markdown`, `chunk`, auth permission helpers, library/share helpers, and route-level smoke tests with Flask’s test client ([app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

Add browser/mobile regression tests with Playwright or similar against `LECTOR_TTS_BACKEND=kokoro` using a mocked `/tts` endpoint, because the current app’s critical flows are browser flows rather than Android-native screens.

Add a TWA build job that runs Bubblewrap/Gradle on tags and stores the unsigned or signed AAB artifact, but keep the first production upload manual if the chosen tooling or Play Console flow requires signature/bundle verification ([Google PWA-in-Play codelab](https://developers.google.com/codelabs/pwa-in-play)).

Track target SDK and dependency updates at least quarterly, because Play policy already requires API 35 for new apps and updates from August 31, 2025 ([Google Play target API requirements](https://developer.android.com/google/play/requirements/target-sdk)).

If Jacob later adopts Capacitor, the most maintainable route is to first split `app.py` into `server/` plus `web/` and introduce JSON endpoints for jobs, library, shares, account, and voice metadata; Capacitor can then own native features while the backend keeps TTS secrets and job execution ([Capacitor workflow docs](https://capacitorjs.com/docs/basics/workflow), [app.py](https://github.com/JacobStephens2/lector/blob/master/app.py)).

If Jacob later adopts Kotlin/Compose or KMP, the best shared-code seam is not the existing Flask app but a small protocol layer: OpenAPI schema, typed job/library DTOs, auth/session rules, and perhaps a shared Markdown-cleaning spec with golden tests.

If Jacob later adopts Flutter, treat it as a cross-platform client rewrite over those same APIs rather than as a WebView shell, because a Flutter WebView wrapper would duplicate the TWA’s web-container role without gaining much product value ([webview_flutter package](https://pub.dev/packages/webview_flutter)).

## 7. Concrete project layout proposal

```text
lector/
  app.py                         # current Flask app, later split if needed
  requirements.txt
  kokoro/
  deploy/
  static/
    pwa/
      icon-192.png
      icon-512.png
      icon-maskable-512.png
      offline.html
      service-worker.js
  android-twa/
    twa-manifest.json
    app/                         # generated Bubblewrap Android project, optional but recommended
    README.md                    # build/signing/release instructions
  tests/
    test_markdown_cleaning.py
    test_chunking.py
    test_auth_boundaries.py
  .github/workflows/
    server-ci.yml
    android-twa-build.yml
```

This layout keeps the Android artifact visibly separate from the server while making the PWA assets part of the deployed web app.

## Final answer

Build `lector` as a **mobile-first PWA and publish it as a TWA** rather than rewriting it for Android.

Move to Capacitor or Kotlin/Compose only after the product needs native features that a verified web app cannot provide.
