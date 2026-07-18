# Release / Compliance Checklist

Unusually short because the architecture deletes most obligations: no data
collection, no accounts, no network, no third-party services. Items are marked
**[1.0]** (applies to the sideload release) or **[Play]** (activates only if a
Play listing is pursued).

## [1.0] Sideload release

- [ ] **AI-transparency disclosure** - About screen states the voice is
  synthetic, produced on-device by Kokoro-82M; names the model's Apache-2.0
  license and documented training-data provenance. (Same honesty bar as the
  sotto server's /about.)
- [ ] **License compliance** - bundle attributions: Kokoro-82M (Apache-2.0),
  sherpa-onnx (Apache-2.0), espeak-ng (GPL-3.0 - verify linkage form and
  obligations before release; this is the one third-party license that needs
  actual review), Media3, and the voice-embedding files' terms.
- [ ] **App license** decided and committed (repo-licensing conventions).
- [ ] **README claims verifiable** - the no-network claim ships with its
  verification command (`aapt dump permissions`); release notes include the
  output (31-release-cicd-plan.md).
- [ ] **Privacy policy** - one page, hosted with the repo: "this app collects
  nothing and transmits nothing; it cannot - here's the proof." Not legally
  required for sideload, but it preempts the Play item and is a marketing asset
  for this particular app.

## [Play] Only if a Play listing is pursued (post-1.0 decision)

- [ ] Developer verification completed (legal name/address; the regime gating
  publishing since March 2026 - start early, it gates the timeline).
- [ ] Data Safety form, per flavor: `local` - "no data collected, no data
  shared," accurate because of ADR-004. `sync` - declare account credentials
  (email) and user-content upload, transmitted only to the user-configured
  server; no third parties. No WebView disclosure needed (council flag applied:
  that finding was for the TWA product, not this one). If only one listing is
  published, list the `local` flavor and offer `sync` via GitHub.
- [ ] Account deletion mechanism: **N/A - no accounts exist.** (The council's
  /account/delete finding applies to the sotto web service, not here.)
- [ ] Content rating questionnaire; store listing assets (screenshots, feature
  graphic); privacy policy URL (already exists from [1.0]).
- [ ] Internal testing track: the 12-tester/14-day requirement on a personal
  account (known from Creighton) - budget calendar time for it.
- [ ] Play Asset Delivery for the model pack (ADR-005) if base-size limits bite.

## [F-Droid] If submitted

- [ ] Reproducible build configuration; no proprietary blobs question: confirm
  the int8 model files' redistribution terms are F-Droid-acceptable (Apache-2.0
  weights should be, but confirm their policy on large model assets).
