#!/usr/bin/env python3
"""Generate one short MP3 preview per Kokoro voice into ../samples/.

Run once after the model is in place; the lector home page plays these from
/sample/<voice>. Commit the resulting files (they are small demo assets).

    .venv/bin/python generate_samples.py
"""
import os
from server import ALLOWED, to_mp3, _kokoro, LANG

SAMPLE_TEXT = ("lector reads your documents aloud, so a long plan is easier to "
               "absorb on a walk than at a desk.")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "samples")

os.makedirs(OUT, exist_ok=True)
for voice in sorted(ALLOWED):
    samples, sr = _kokoro.create(SAMPLE_TEXT, voice=voice, speed=1.0, lang=LANG)
    path = os.path.join(OUT, voice + ".mp3")
    with open(path, "wb") as f:
        f.write(to_mp3(samples, sr))
    print("wrote", os.path.relpath(path))
