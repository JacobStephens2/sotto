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
3. Sends each chunk to OpenAI text-to-speech (`gpt-4o-mini-tts`) and
   concatenates the audio into one MP3.

Jobs run in the background (a 10k-word document takes a few minutes), so the
request never blocks on a long synthesis.

Saving a result to your Library keeps the source markdown beside the audio (a
`.md` sidecar under the same basename), so every saved narration stays traceable
to exactly what was read - readable inline or downloadable from the Library page.

## The boundaries it keeps (and why they are the point)

This is a TTS toy, but it is built the way a revenue-critical AI automation
should be, so the same checklist is visible in something small:

- **Auth gate** - the whole site is behind HTTP Basic auth at the Apache edge,
  over TLS.
- **Secret isolation** - the OpenAI key is read from a systemd `EnvironmentFile`
  (`/etc/lector/lector.env`, root-owned, outside the web root). It is never in
  the page, never in this repository, never sent to the browser.
- **Bounded scope** - the only outbound call is to the TTS API; input is size-
  capped; there is no shell and no arbitrary network access.
- **Not delegated** - lector produces audio and stops. It never sends, publishes,
  posts, or acts on anyone's behalf.
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
.venv/bin/waitress-serve --listen 127.0.0.1:3475 app:app
```

Apache reverse-proxies `lector.stephens.page` to `127.0.0.1:3475` and adds the
Basic-auth gate and the `X-Remote-User` header. systemd (`lector.service`) keeps
it running.

## Swapping the API key

The key is the one line in `/etc/lector/lector.env`. Replace the value and
`sudo systemctl restart lector`. Nothing else references it.
