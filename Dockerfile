# lector web app. The TTS engine lives in its own image (kokoro/Dockerfile);
# this one is just Flask + waitress.
FROM python:3.12-slim

RUN useradd --create-home --shell /usr/sbin/nologin lector
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt waitress

COPY app.py .
COPY samples/ samples/

# Library, jobs, and state are volumes (declared in docker-compose.yml) so
# accounts and generated audio survive image rebuilds.
RUN mkdir -p library jobs state && chown -R lector:lector /app

USER lector
EXPOSE 3476
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:3476/', timeout=4)"]

CMD ["waitress-serve", "--listen", "0.0.0.0:3476", "--threads", "24", "--channel-timeout", "30", "app:app"]
