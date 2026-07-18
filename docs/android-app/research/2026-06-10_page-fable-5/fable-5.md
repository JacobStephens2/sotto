Fun one. Let me ground it in what you've already got and built before (Capacitor on MacroTracker, Compose Multiplatform on Daily Dozen, Flutter on Quadrille, the Cascade one-core-many-shells kata), then lay out the option space.

## The core question: where does synthesis run?

Everything else follows from this choice.

### Option A - Thin client to your server
The app is a native front end for lector.stephens.page: paste/share text → POST to the existing Flask API → job runs server-side on Kokoro → notification when done → stream or download from the Library.

- **Pros:** smallest build; reuses everything you just hardened (durable jobs, resume, email/notify, share links); long docs don't cook a phone; jobs keep running when the phone sleeps.
- **Cons:** needs network; multi-user means your VPS does everyone's synthesis (fine at current scale); you'd need to add token auth to the API (the session-cookie login won't fly for a native app).
- **New server work:** a small token-auth API surface (`POST /api/convert`, `GET /api/jobs`, `GET /api/library`), which is genuinely useful regardless.

### Option B - On-device Kokoro (the interesting one)
Kokoro-82M runs on phones. **sherpa-onnx** ships Android support with Kokoro specifically, and an int8-quantized model is ~80-170 MB; modern mid-range SoCs synthesize around or above realtime. The app bundles the model and narrates entirely on-device.

- **Pros:** this is the *strongest possible version of lector's whole thesis* - "no audio leaves your device, no account, no server, and you can name the model's training data." Offline on a plane. Zero marginal cost. As a portfolio artifact, "edge deployment of an openly-licensed TTS model with the same seven-boundary checklist" is a genuinely distinctive story - it extends your MH positioning from "self-hosted" to "user-sovereign."
- **Cons:** real engineering - model packaging (Play's 200 MB+ asset delivery), thermals/battery on hour-long syntheses, foreground-service plumbing; the 38k-word encyclical that took your 4-core VPS ~5h is a brutal on-phone job.
- **Mitigation:** chunk-as-you-listen - synthesize just ahead of the playhead instead of the whole file upfront. The user presses play and it stays ~2-3 min ahead. That converts the "hours of synthesis" problem into "seconds to first audio," which is also just a better product.

### Option C - Hybrid (B with A as an escape hatch)
On-device by default; "send to my server" for monster documents or low-battery situations, landing the result in the same Library. Most product, most work.

### Option D - Capacitor wrap of the existing site
You've done this with MacroTracker. A day of work, gets the share-sheet and an icon.
- Honest assessment: low portfolio value (you've already shipped this pattern), and lector's web UI is already mobile-fine. I'd skip unless you just want the share-target quickly.

## The Android-native wins (whichever architecture)

These are what make an *app* worth having over the website:

1. **Share-sheet target** - the killer feature. Select text anywhere / share a URL or .md file → "Read with lector." This alone is the reason to build it.
2. **Media session done right** - lock-screen controls, headphone buttons, resume position per oration, sleep timer, 15s skips. Listening on a walk is the whole point; the web `<audio>` tag is the weakest part of the current experience.
3. **Foreground service with progress notification** for synthesis (mirrors your job page; Android requires it for long background work anyway).
4. **Offline library** - downloaded orations + source text, synced from the server when present.
5. Later: **Android Auto** (it's an audio app; this is cheap once MediaSession is right), playback speed, per-paragraph navigation derived from the chunk boundaries you already track.

## Stack thoughts

- **Compose Multiplatform** - aligns with your Daily Dozen KMP investment, and leaves an iOS door open. sherpa-onnx has JNI bindings that work fine from Kotlin.
- **Plain Kotlin/Compose** - simplest for a B-style app; all the interesting work is in the audio/inference layer anyway.
- **Flutter** - you have Quadrille, but the ONNX/media-session story is more mature on the Kotlin side.
- A Cascade-style **Rust core** is tempting for the kata aesthetic but overkill here - the "core" is Kokoro itself.

## Boundary story on mobile (worth writing down early)

The seven boundaries translate nicely and would make a great README section: auth gate becomes *no account at all* (on-device); secret isolation becomes *no key exists*; bounded scope becomes *zero network permission* (literally omit `INTERNET` from the manifest for pure Option B - an auditable, falsifiable claim); not-delegated stays (it makes audio, never acts); traceability becomes a local job log; provenance honesty ships in the About screen. An Android app where the manifest *proves* nothing leaves the device is a lovely artifact.

## What I'd actually do

**Option B, Kotlin/Compose, share-sheet-first MVP:** share text in → chunk-ahead-of-playhead on-device Kokoro → media-session player → local library with named entries. No server dependency in v1; add optional sync with your VPS later (which is when the token API gets built). Distribute first as a GitHub-release APK like MacroTracker - that sidesteps the Play 12-tester slog from Creighton until it's worth it.

MVP scope is honestly ~2-4 weeks of evenings: sherpa-onnx integration and the streaming player are the two real lifts; the rest is plumbing you've done before.

Want me to spike the riskiest slice first - sherpa-onnx + Kokoro int8 on an actual device build, measuring realtime factor and battery - so the architecture choice rests on a measurement instead of my estimate?