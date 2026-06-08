#!/usr/bin/env python3
"""kokoro - a local text-to-speech microservice for lector.

It wraps Kokoro-82M (ONNX) so lector's only TTS call is to this process on
localhost: no third-party API, no API key, and a model whose training data is
documented and permissively licensed. Speech is synthesized on CPU and returned
as MP3, so the caller concatenates chunks exactly as it did with the previous
hosted provider.

Boundaries, like lector's: one inbound endpoint, no outbound network, no shell.
The MP3 encode is done in-process with libmp3lame (no ffmpeg subprocess).
"""
import os
import numpy as np
import lameenc
from flask import Flask, request, abort, Response, jsonify
from kokoro_onnx import Kokoro

DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.environ.get("KOKORO_MODEL", os.path.join(DIR, "models", "kokoro-v1.0.onnx"))
VOICES_PATH = os.environ.get("KOKORO_VOICES_BIN", os.path.join(DIR, "models", "voices-v1.0.bin"))
LANG = os.environ.get("KOKORO_LANG", "en-us")
BITRATE = int(os.environ.get("KOKORO_BITRATE", "64"))

# Curated narrator voices (Kokoro v1.0 ids). a/b = American/British, f/m = female/male.
ALLOWED = {"af_heart", "am_michael", "af_bella", "am_adam", "bf_emma", "bm_george", "af_nicole"}
DEFAULT_VOICE = "af_heart"

app = Flask(__name__)
_kokoro = Kokoro(MODEL_PATH, VOICES_PATH)  # loads the model once, at startup


def to_mp3(samples, sample_rate):
    """Encode mono float32 samples in [-1, 1] to MP3 bytes, in-process."""
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    enc = lameenc.Encoder()
    enc.set_bit_rate(BITRATE)
    enc.set_in_sample_rate(int(sample_rate))
    enc.set_channels(1)
    enc.set_quality(2)  # 2 = high quality, 7 = fastest
    return enc.encode(pcm) + enc.flush()


@app.route("/tts", methods=["POST"])
def tts():
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    voice = data.get("voice") or DEFAULT_VOICE
    speed = float(data.get("speed") or 1.0)
    if not text:
        abort(400)
    if voice not in ALLOWED:
        voice = DEFAULT_VOICE
    samples, sample_rate = _kokoro.create(text, voice=voice, speed=speed, lang=LANG)
    return Response(to_mp3(samples, sample_rate), mimetype="audio/mpeg")


@app.route("/voices")
def voices():
    return jsonify(voices=sorted(ALLOWED))


@app.route("/healthz")
def healthz():
    return "ok\n", 200


if __name__ == "__main__":
    app.run("127.0.0.1", 3477)
