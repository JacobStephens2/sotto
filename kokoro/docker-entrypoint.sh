#!/bin/sh
# Fetch the Kokoro-82M weights into the models volume on first start (~360 MB,
# from the kokoro-onnx release - see kokoro/README.md), then serve.
set -eu

MODELS_DIR="${KOKORO_MODELS_DIR:-/app/models}"
BASE_URL="https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

fetch() { # $1 = filename
  if [ ! -s "$MODELS_DIR/$1" ]; then
    echo "downloading $1 ..."
    curl -fL --retry 3 -o "$MODELS_DIR/$1.part" "$BASE_URL/$1"
    mv "$MODELS_DIR/$1.part" "$MODELS_DIR/$1"
  fi
}

fetch kokoro-v1.0.onnx
fetch voices-v1.0.bin

exec waitress-serve --listen 0.0.0.0:3477 --threads 4 --channel-timeout 1800 server:app
