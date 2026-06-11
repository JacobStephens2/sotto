# Local Kokoro-82M TTS backend. espeak-ng is the misaki phonemizer's fallback
# for out-of-vocabulary words; curl is for the one-time model download.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends espeak-ng curl \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /usr/sbin/nologin kokoro
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py docker-entrypoint.sh ./
RUN chmod +x docker-entrypoint.sh \
 && mkdir -p models && chown -R kokoro:kokoro /app

USER kokoro
EXPOSE 3477
# Generous start period: the first start downloads ~360 MB of model weights.
HEALTHCHECK --interval=30s --timeout=5s --start-period=300s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3477/healthz', timeout=4)"]

ENTRYPOINT ["./docker-entrypoint.sh"]
