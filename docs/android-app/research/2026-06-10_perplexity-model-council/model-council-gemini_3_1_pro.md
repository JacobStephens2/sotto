# Turning Lector into an Android App: A 2026 Strategy Guide

## 1. What Lector Actually Is (Stack & Architecture)
After inspecting the `JacobStephens2/lector` repository via the GitHub CLI, it's clear that Lector is not a typical modern web app (like a React or Vue SPA). It is a self-hosted, server-side Python application. 

Here's the technical reality of the stack:
*   **Backend:** Python 3 with the **Flask** web framework.
*   **Routing/Templates:** It uses `render_template_string` from Flask, meaning the HTML UI is generated server-side.
*   **TTS Engines:** It supports an external API (`gpt-4o-mini-tts`) or a strictly local microservice (`kokoro` running an 82M parameter ONNX model on the host CPU).
*   **State & Storage:** It uses the local filesystem extensively (`/jobs`, `/samples`, `/library`, `/state` directories) for storing MP3s, Markdown sidecars, and user databases (hashed passwords in JSON/files).
*   **Security Model:** It relies on a reverse proxy (Apache) for TLS, server-side HTTPS-only cookies for sessions, and host-level environment variables for secrets. 

Crucially, **Lector expects to run as a persistent daemon on a server (via Waitress and systemd)**, handling background TTS generation that can take up to 40 minutes for large documents.

## 2. Realistic Android Porting Strategies for 2026

Given that Lector is a server-rendered Flask app heavy on local filesystem I/O and CPU-bound background processing, standard front-end web app wrappers are immediately problematic. Here is an analysis of potential approaches in 2026:

*   **Capacitor / Tauri Mobile (Web Wrappers):** 
    *   *How it works:* These wrap HTML/JS/CSS in a native WebView and provide bridges to native device features.
    *   *The Problem:* They expect a client-side SPA (React, Vue, Next.js). They do *not* run a Python Flask server. To use Capacitor, you would need to completely decouple Lector's frontend into a separate JS app that talks via API to a Lector server. 
*   **Trusted Web Activity (TWA) / Progressive Web App (PWA):**
    *   *How it works:* A TWA wraps a PWA in a Chrome Custom Tab for Play Store distribution. It requires the app to be served over HTTPS from a verified domain.
    *   *The Problem:* This doesn't actually port the *code* to the phone. It just creates a native Android icon that loads your self-hosted instance (e.g., `lector.stephens.page`). This is great for distribution, but it requires the user to maintain their own server infrastructure.
*   **Kivy / Python-for-Android (Python Native):**
    *   *How it works:* Tools like Kivy can package a Python runtime into an APK. There are community efforts to run Flask inside Android WebViews using local HTTP servers.
    *   *The Problem:* Running a background ONNX model (Kokoro) on an Android device via a bundled Python interpreter will face massive memory constraints, OS background execution limits (Doze mode), and horrific battery drain. Android will kill the 40-minute TTS background job aggressively.
*   **Kotlin Multiplatform (KMP) / Flutter Rewrite:**
    *   *How it works:* A complete rewrite of the application logic and UI in Kotlin or Dart.
    *   *The Problem:* High effort. You have to recreate the UI, the state management, and the audio processing logic. 
*   **React Native:**
    *   *The Problem:* Similar to KMP/Flutter, it requires a total rewrite of the UI.

## 3. The Recommended Path: The "Thin Client + TWA/PWA" Strategy

For Jacob Stephens—a senior platform engineer comfortable with Kotlin, Swift, and advanced tooling, who explicitly values *secret isolation* and *provenance honesty*—**the best approach is not to shove a server daemon onto a mobile phone, but to embrace the server-client model securely.**

**Recommendation: Do not port the Flask app to Android natively. Instead, convert the existing Lector instance into a Progressive Web App (PWA), and use a Trusted Web Activity (TWA) via Bubblewrap to publish a highly-performant thin client to the Play Store.**

**Justification:**
1.  **Preserves the Architecture:** Lector's core value is doing heavy, unmetered AI compute locally on a host machine via Kokoro to avoid data exfiltration. Android phones are not designed to run 40-minute CPU-bound ONNX inference jobs in the background without user interaction. The host server is the correct place for this compute.
2.  **Zero Rewrite:** Converting Flask templates to an SPA just to use Capacitor is wasted effort for a solo dev. A PWA just requires adding a Manifest and a Service Worker to the existing Flask app.
3.  **Modern 2026 UX:** TWAs in 2026 (running via Chrome Custom Tabs) offer a full-screen, address-bar-free experience indistinguishable from native apps, sharing the user's main Chrome session state (useful for auth).
4.  **No App Store Rejections for Background Compute:** Apple and Google actively reject apps that mine crypto or run heavy background CPU tasks that drain battery. Keeping the Kokoro engine on the server circumvents this policy trap.

If a true "offline" mobile app is required later, the *only* viable path is a **Kotlin Multiplatform (KMP)** rewrite that relies strictly on Android's native TTS APIs or a highly optimized ONNX Runtime for Android (C++ backend via JNI), completely abandoning the Flask/Waitress architecture.

## 4. Step-by-Step Implementation Outline (TWA Approach)

This path gets Lector onto an Android phone in a weekend, rather than a month of rewriting.

### Milestone 1: PWA Enablement in Flask (The Foundation)
1.  **Add `manifest.json`:** Create a Web App Manifest defining the `name`, `short_name`, `icons` (512x512 maskable), `start_url` (`/`), and `display` (`standalone`). Serve this statically from Flask.
2.  **Add a Service Worker:** Create a basic `sw.js` to cache the static assets (CSS, logos). The core Lector experience requires connectivity (to hit the Kokoro backend), so an offline fallback page ("No Connection to Lector Server") is sufficient.
3.  **HTTPS Verification:** Ensure the target server (`lector.stephens.page`) has a valid Let's Encrypt certificate (already implied by the Apache reverse proxy setup in the README).

### Milestone 2: TWA Generation (The Android Wrapper)
1.  **Install Bubblewrap CLI:** Google's official 2026 tool for generating TWAs (`npm i -g @GoogleChromeLabs/bubblewrap`).
2.  **Initialize Project:** Run `bubblewrap init --manifest=https://lector.stephens.page/manifest.json`. The CLI will automatically scaffold a lightweight Android Studio project in Java/Kotlin.
3.  **Digital Asset Links:** This is the critical step to hide the Chrome address bar. Bubblewrap will generate an `assetlinks.json` file containing the Android app's SHA256 fingerprint.
4.  **Serve Asset Links:** Modify the Flask `app.py` to route `/.well-known/assetlinks.json` and serve the generated file.

### Milestone 3: Play Store Submission & Gotchas
1.  **Build Release APK/AAB:** Run `bubblewrap build` to generate the signed App Bundle.
2.  **Play Store Policies:** Because Lector requires a server, the Play Store reviewer *must* be provided with a test account (username/password) to the public-facing `lector.stephens.page` instance.
3.  **Gotcha - Localhost limitation:** This TWA app will be hardcoded to `lector.stephens.page`. If the goal is a generic app anyone can download and point to *their own* local server (e.g., `192.168.1.50`), a TWA cannot be used. You would instead need a simple native Android Kotlin app with a single `WebView` that prompts the user for their server IP on first launch.

## 5. Maintenance, CI/CD, and Code-Sharing Implications

*   **Zero Mobile Maintenance:** The beauty of the TWA approach is that any UI updates made to the Flask templates immediately reflect in the Android app. You do not need to push updates to the Google Play Store when modifying the web UI.
*   **Play Store Updates:** You only need to push a new Android App Bundle (AAB) to the Play Store if you change the app icon, name, or update the underlying Bubblewrap SDK for newer Android OS compliance.
*   **CI/CD:** You can use GitHub Actions to automatically run `bubblewrap build` and push to the Play Store internal testing track using the `google-github-actions/upload-google-play` action, triggered only when the `manifest.json` or PWA icons change.
*   **Scaling to iOS:** Because the core is a PWA, iOS users can simply utilize Safari's "Add to Home Screen" feature (which in 2026 fully supports Web Push and standalone UI), avoiding the Apple Developer Program $99 fee entirely for what is essentially a personal/niche tool.