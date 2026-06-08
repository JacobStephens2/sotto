# kokoro - local TTS backend for lector

A small Flask service that synthesizes speech with **Kokoro-82M** (ONNX) on CPU
and returns MP3. lector calls it on localhost instead of a hosted TTS API, so
there is no third-party API key and no audio leaves the server.

Why it exists: the hosted provider could not disclose what its voices were
trained on. Kokoro-82M is Apache-2.0 and trained on documented public-domain and
permissively licensed audio, so lector can finally *name* its model's provenance
instead of marking it opaque.

## Endpoints

- `POST /tts` - body `{"text": "...", "voice": "af_heart", "speed": 1.0}` -> `audio/mpeg`
- `GET /voices` - the allowed voice ids
- `GET /healthz`

## Setup

```
cd kokoro
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo apt-get install -y espeak-ng          # phonemizer backend for out-of-vocab words

# model weights (~360 MB total) - not committed
mkdir -p models
curl -L -o models/kokoro-v1.0.onnx https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -L -o models/voices-v1.0.bin  https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin

# voice previews for the lector home page (commit the results)
.venv/bin/python generate_samples.py
```

Then install the service and point lector at it:

```
sudo cp ../deploy/kokoro.service /etc/systemd/system/kokoro.service
sudo systemctl daemon-reload && sudo systemctl enable --now kokoro

# in /etc/lector/lector.env:
#   LECTOR_TTS_BACKEND=kokoro
sudo systemctl restart lector
```

To fall back to the hosted provider, set `LECTOR_TTS_BACKEND=openai` (or remove
the line) and restart lector. Nothing else changes.

## Footprint

Kokoro-82M is ~330 MB of weights. On this 4-core box it synthesizes at roughly
**1.4x realtime** (CPU only), so a short document is ready in well under a minute,
but an audiobook-length document (~1 hour of audio) takes ~40 min. lector runs
synthesis as a background job, so the request never blocks on it. The systemd unit
fences the service at `CPUQuota=300%` / `Nice=10` / `MemoryMax=2G`, leaving a core
free for the other apps on the box.
