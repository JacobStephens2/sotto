# Council synthesis — How should I turn https://github.com/JacobStephens2/lector into an And…

- **Profile:** council-deep
- **Date:** 2026-06-10 20:58 UTC
- **Members:** Perplexity Web Agent (grok-4.3), GLM-5.1, GPT-5.5, Gemini 3.1 Pro
- **Synthesizer:** Claude Fable 5
- **Elapsed:** 277.6s
- **Cost:** ≈$0.42 (Chair $0.00)

## Question

How should I turn https://github.com/JacobStephens2/lector into an Android app?

## Synthesis

# Recommendation: Don't port it — package it. PWA + Trusted Web Activity via Bubblewrap.

## What `lector` actually is (and why that decides the answer)

One council member couldn't see the repo and gave only generic options, but another inspected it directly: `lector` is a server-hosted Flask app (live at `lector.stephens.page`) that takes Markdown, cleans and chunks it under TTS limits, synthesizes audio via local Kokoro or OpenAI `gpt-4o-mini-tts`, concatenates MP3s, and stores library entries — with the OpenAI key kept server-side in `/etc/lector/lector.env` and paid-backend access gated by `LECTOR_OPENAI_ALLOWED` [11].

That architecture settles the question. The expensive, secret-bearing, long-running work (TTS, billing controls, audit logs) already lives where it should — on the server. The phone only needs to log in, submit Markdown, poll job status, and play/download/share MP3s. That's web-client territory. **Do not attempt an on-device Android port of the TTS pipeline** — it would break your secrets/billing/privacy model for no payoff.

Notably, both members who ranked options independently converged on the same ordering: **PWA + TWA first**, Capacitor if you later need native plugins, plain WebView only for personal sideloading, full native last.

## The plan

### 1. Make the Flask app installable as a PWA (Day 1–2)

Add and serve:

- `/manifest.webmanifest` (name, icons, `display: standalone`, `start_url`, theme color)
- `/sw.js` — a deliberately minimal service worker
- 192px, 512px, and maskable icons under `/static/icons/`

**Critical gotcha since the app is password-protected:** exempt `/manifest.webmanifest`, `/sw.js`, the icons, and `/.well-known/assetlinks.json` from your login guard. The PWA/TWA machinery must fetch them unauthenticated; app pages stay behind auth.

Keep the service worker boring at first — just `skipWaiting()` / `clients.claim()`. Don't cache `/library`, `/job/*`, `/audio/*`, or `/share/*`: generated MP3s and Markdown sidecars can be sensitive [11], and stale job-status pages are worse than no caching.

While you're in there, fix mobile UX in Android Chrome: 16px+ font in the Markdown textarea (avoids zoom-on-focus), a resilient polling job-status page, native `<audio controls>` playback, and tap-friendly library rows. This is the project's biggest unknown — if the templates are already roughly responsive, this is a 1–3 day project; if they're desktop-only, budget closer to a week.

### 2. Wrap with Bubblewrap / TWA (Day 3)

Trusted Web Activity is Android's official mechanism for opening a web app you own fullscreen, with no browser chrome, after proving ownership via Digital Asset Links [38][39]. Bubblewrap is Google Chrome Labs' CLI that generates and builds the Android project for you, producing a signed APK/AAB [40][41]:

```bash
npm install -g @bubblewrap/cli
bubblewrap init --manifest=https://lector.stephens.page/manifest.webmanifest
bubblewrap build
```

Then host the generated `assetlinks.json` (containing your package name, e.g. `page.stephens.lector`, and your signing cert's SHA-256 fingerprint) at `https://lector.stephens.page/.well-known/assetlinks.json` — publicly, returning HTTP 200 JSON, not a redirect to login [39].

Bonus of this route: updates ship instantly when you update the website — no APK re-uploads.

### 3. Distribute cautiously

- **First:** `adb install` on your own phone; test the full login → generate → play → share → revoke loop.
- **Then:** Play Console **internal testing** with a small tester list [42].
- **Public listing only if needed** — a login-gated app will need a privacy policy, data-safety disclosures, and likely a demo account for Google's reviewers.

## What was rejected, and why

| Option | Verdict |
|---|---|
| **Plain Kotlin WebView wrapper** | Tempting (<100 lines [45]), but you inherit file-upload handling, cookie/login persistence, back-navigation, download, and audio edge cases yourself. Fine for a personal sideload; TWA is cleaner and more "official" for content you own. |
| **Capacitor** | Hold in reserve. Adopt it only when you hit a concrete limitation — e.g. "Share to Lector" intents, a native `.md` file picker, or push notifications on job completion. |
| **Cordova** | Skip entirely — legacy tooling with a shrinking plugin ecosystem; Capacitor is its successor. |
| **Native Kotlin/Compose client + Flask API** | The best *eventual* product if usage grows (Retrofit + WorkManager polling + Media3 playback against `/api/jobs`, `/api/library` endpoints), but a 2–6 week effort and a poor first move. |
| **Full on-device port** | Don't. It moves the OpenAI key and billing gates onto devices and discards your audit-log centralization [11]. |

## Security boundaries to preserve

- Never ship `OPENAI_API_KEY` or let the client decide `LECTOR_OPENAI_ALLOWED` — the client can *display* backend options, but the server must enforce them [11].
- Keep share links explicit and revocable in the mobile UI (create / copy / revoke buttons); don't auto-expose audio through Android share intents.
- Defer offline caching of library content until you've designed explicit user controls for it.

## Bottom line

Spend ~3–5 days: make the Flask UI mobile-friendly, add a manifest + minimal service worker + auth-exempt asset routes, run Bubblewrap, host `assetlinks.json`, and install the resulting TWA on your phone [38][39][40]. You get a real Android app icon, fullscreen experience, and instant updates — while every security property of your current design stays intact. Graduate to Capacitor or a native Kotlin client only when daily use surfaces a specific need the web app can't meet.

## Sources

1. [Lector (software) - Wikipedia](https://en.wikipedia.org/wiki/Lector_(software)) · pplx agent · 2026-05-17
2. [Jacob Coty Stephens, Ph.D.](https://www.depts.ttu.edu/ece/faculty/jacob_stephens/Stephens_CV_2022.pdf) · pplx agent · 2024-11-27
3. [Lector - Chrome Web Store](https://chromewebstore.google.com/detail/lector/lbddammbeglkoplpimmjcldgebpclodc) · pplx agent · 2026-03-17
4. [Lector — Write it. Hear it back.](https://uselector.app) · pplx agent · 2026-04-20
5. [Jacob Stephens](https://www.imdb.com/name/nm2803384/) · pplx agent · 2026-05-19
6. [Lector | self-hosted language learning reader](https://lector.dev) · pplx agent · 2026-06-10
7. [Why We Worship at St. Stephen's | sstephens](https://www.sstephens.org/my-s-stephen-s-ministry) · pplx agent · 2024-08-28
8. [Turn Your Website into an Android App in 7 Minutes](https://www.youtube.com/watch?v=yobXmk-eD0c) · pplx agent · 2026-05-28
9. [Lector - Apps on Google Play](https://play.google.com/store/apps/details?hl=en_US&id=gr.lector) · pplx agent · 2024-01-21
10. [Dr. Jacob Stephens, MD – Cincinnati, OH | Urology on Doximity](https://www.doximity.com/pub/jacob-stephens-md) · pplx agent · 2025-03-01
11. [https://github.com/JacobStephens2/lector](https://github.com/JacobStephens2/lector) · fetched
12. `tourbot/guides/css/mobile-pwa.css` · local file
13. `tourbot/customerweb/app/group-leader-account/proposals/dark-mode-mobile.css` · local file
14. `tourbot/guides/app/login.php` · local file
15. `tourbot/customerweb/app/group-leader-account/proposals/proposal.php` · local file
16. `status-dashboard/app.py` · local file
17. `tourbot/scripts/apply-migration.sh` · local file
18. `tourbot/mtourbot/vendorportal/approve_price.php` · local file
19. `tourbot/mtourbot/vendorportal/library/approve_price.php` · local file
20. `tourbot/mtourbot/vendorportal/library/approve_allotment.php` · local file
21. `tourbot/mtourbot/tools/migrations/apply.php` · local file
22. `tourbot/mtourbot/tools/check_reappearing_emails.php` · local file
23. `tourbot/scripts/apply_performance_indexes_2026-04-25.php` · local file
24. `tasks/browser-agent-gh-pat-jacobstephens2.md` · local file
25. `tourbot/.github/workflow-drafts/PROMOTE-production-auto-deploy.md` · local file
26. `tourbot/modern/resources/js/app.js` · local file
27. `tourbot/modern/config/app.php` · local file
28. `tourbot/modern/bootstrap/app.php` · local file
29. `tourbot/maintenance/api/toggle_app.php` · local file
30. `tourbot/modern/app/Providers/AppServiceProvider.php` · local file
31. `tourbot/modern/resources/views/app.blade.php` · local file
32. [GitHub - JacobStephens2/java_17_masterclass_udemy: This repository tracks my progress through the course on Udemy, Java 17 Masterclass: Start Coding in 2024. I aim to get Java certification from Oracle.](https://github.com/JacobStephens2/java_17_masterclass_udemy) · web result (pplx)
33. [Lector/README.md at master · msuozzo/Lector](https://github.com/msuozzo/Lector/blob/master/README.md) · web result (pplx)
34. [JacobStephens2/wedding-platform: A custom-built ...](https://github.com/JacobStephens2/wedding-platform) · web result (pplx)
35. [Releases · anaralabs/lector](https://github.com/anaralabs/lector/releases) · web result (pplx)
36. [GitHub - davazp/lector: A library for contextual computations in Javascript](https://github.com/davazp/lector) · web result (pplx)
37. [lector/README.md at main · anaralabs/lector](https://github.com/anaralabs/lector/blob/main/README.md) · web result (pplx)
38. [Overview of Trusted Web Activities | Views](https://developer.android.com/develop/ui/views/layout/webapps/trusted-web-activities) · web result (pplx)
39. [Setting up your asset link file](https://developer.android.com/develop/ui/views/layout/webapps/guide-trusted-web-activities-version2) · web result (pplx)
40. [GoogleChromeLabs/bubblewrap - GitHub](https://github.com/GoogleChromeLabs/bubblewrap) · web result (pplx)
41. [What's new for Web In Play | Web on Android - Chrome for Developers](https://developer.chrome.com/docs/android/trusted-web-activity/whats-new) · web result (pplx)
42. [Submitting a PWA to Google Play Store using Bubblewrap](https://vaadin.com/blog/submitting-a-pwa-to-google-play-store-using-bubblewrap) · web result (pplx)
43. [คู่มือเริ่มใช้งานฉบับย่อสําหรับกิจกรรมในเว็บซึ่งเชื่อถือได้ | Views | Android Developers](https://developer.android.com/develop/ui/views/layout/webapps/guide-trusted-web-activities-version2?hl=th) · web result (pplx)
44. [Android WebView Handling input type "File" (File Explorer and ...](https://stackoverflow.com/questions/76285895/android-webview-handling-input-type-file-file-explorer-and-camera-separate) · web result (pplx)
45. [Build web apps in WebView - Android Developers](https://developer.android.com/develop/ui/views/layout/webapps/webview) · web result (pplx)
46. [Android WebView <input type="file"> does not show 'Choose an ...](https://github.com/NativeScript/NativeScript/issues/5313) · web result (pplx)
47. [Upload file in Android 2.2.1 webview using html form](https://stackoverflow.com/questions/8469597/upload-file-in-android-2-2-1-webview-using-html-form) · web result (pplx)
48. [How to implement file upload in Android - TalkJS](https://talkjs.com/resources/chat-file-upload-android/) · web result (pplx)
49. [android Webview支持input type=file](https://blog.csdn.net/qq_29034779/article/details/58584655) · web result (pplx)
