# lector

Paste a markdown document, get a narrated MP3. Self-hosted at
`lector.stephens.page` behind a password.

It exists because long strategic documents (plans, ADRs, specs) are easier to
absorb on a walk than at a desk. It also serves as a small, honest example of
how to wrap an AI automation so a person stays in command of it.

## What it does

1. Cleans the markdown for the ear - drops links and raw URLs, reads `§102` as
   "section 102", flattens tables into sentences, expands a few acronyms.
2. Splits the text into chunks under the TTS input limit.
3. Sends each chunk to a text-to-speech backend and concatenates the audio into
   one MP3. Two backends are supported, selected by `LECTOR_TTS_BACKEND`:
   - `kokoro` - a local **Kokoro-82M** (ONNX) service on this machine, so no
     audio or API key leaves the server (see `kokoro/`).
   - `openai` (default) - the hosted `gpt-4o-mini-tts`.

   The OpenAI backend bills per call, so it is gated by `LECTOR_OPENAI_ALLOWED`
   (comma-separated accounts). Listed accounts may pick OpenAI voices; everyone
   else is limited to the local Kokoro backend and can never incur API charges.
   Unset means no restriction. The limit is enforced server-side, so a forged
   request still cannot bill OpenAI for an account that is not on the list.

Jobs run in the background (a 10k-word document takes a few minutes), so the
request never blocks on a long synthesis.

Saving a result to your Library keeps the source markdown beside the audio (a
`.md` sidecar under the same basename), so every saved narration stays traceable
to exactly what was read - readable inline or downloadable from the Library page.

## The boundaries it keeps (and why they are the point)

This is a TTS toy, but it is built the way a revenue-critical AI automation
should be, so the same checklist is visible in something small:

- **Auth gate** - every account signs in with an email and a salted-hash password;
  sessions are signed, HTTPS-only cookies. Apache terminates TLS and reverse-proxies
  to the app, which enforces the login itself - no unauthenticated request reaches a
  page, except the share links you deliberately create.
- **Secret isolation** - with the hosted backend, the OpenAI key is read from a
  systemd `EnvironmentFile` (`/etc/lector/lector.env`, root-owned, outside the web
  root); it is never in the page, never in this repository, never sent to the
  browser. With the Kokoro backend there is no third-party key at all.
- **Bounded scope** - the only outbound call is to the TTS API; input is size-
  capped; there is no shell and no arbitrary network access.
- **Not delegated** - lector produces audio and stops. It never acts on its own: it
  does not email, post, or publish anything unless you deliberately create a share
  link, which you control and can revoke.
- **Traceability** - every job appends one audit line (time, user, title, outcome)
  to `lector.log`.
- **Provenance honesty** - the `/about` page states that the voice is synthetic
  and that the model vendor does not disclose training data or upstream labor,
  rather than presenting the audio as neutral.

## Run it

```
python3 -m venv .venv
.venv/bin/pip install flask waitress
echo 'OPENAI_API_KEY=sk-...' | sudo tee /etc/lector/lector.env   # mode 640
echo 'LECTOR_OPENAI_ALLOWED=you@example.com' | sudo tee -a /etc/lector/lector.env  # who may use the paid backend
.venv/bin/waitress-serve --listen 127.0.0.1:3476 app:app
```

Apache terminates TLS and reverse-proxies `lector.stephens.page` to
`127.0.0.1:3476`; authentication is the app's own session login, not anything at
the proxy. systemd (`lector.service`) keeps it running.

### Or with Docker Compose

Two containers - the app and the local Kokoro-82M TTS backend - wired together,
mirroring the systemd deployment:

```
docker compose up -d
# first start downloads the model weights (~360 MB), then:
open http://localhost:3476
```

The app binds loopback by default (`LECTOR_BIND=0.0.0.0` to expose), audio is
synthesized locally in the `kokoro` container (no third-party TTS, no API key),
and accounts/audio/state live in named volumes. Optional extras (hosted-TTS
fallback, SMTP for emailed links) come from a `.env` copied from
`.env.example` - loaded only if present.

## Swapping the API key

The key is the one line in `/etc/lector/lector.env`. Replace the value and
`sudo systemctl restart lector`. Nothing else references it.
