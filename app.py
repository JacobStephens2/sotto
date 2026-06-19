#!/usr/bin/env python3
"""sotto - paste a markdown document, get a narrated MP3.

Boundaries (see /about): the OpenAI key lives only in this process's environment
(never the client, never the repo); accounts are password-gated with hashed
credentials and signed sessions; every job and account action is logged; the app
produces audio and nothing else - it never sends, publishes, or posts.
"""
import functools, hashlib, os, re, io, json, time, uuid, shutil, secrets, smtplib, threading, datetime
import urllib.request, urllib.error
from email.message import EmailMessage
from flask import (Flask, request, redirect, url_for, send_file, abort, Response,
                   render_template_string, session, jsonify, g)
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
JOBS_DIR = os.path.join(APP_DIR, "jobs")
SAMPLES_DIR = os.path.join(APP_DIR, "samples")
LIBRARY_DIR = os.path.join(APP_DIR, "library")
STATE_DIR = os.path.join(APP_DIR, "state")
FONTS_DIR = os.path.join(APP_DIR, "fonts")
USERS_PATH = os.path.join(STATE_DIR, "users.json")
SECRET_PATH = os.path.join(STATE_DIR, "secret.key")
LOG_PATH = os.path.join(APP_DIR, "lector.log")
for d in (JOBS_DIR, LIBRARY_DIR, STATE_DIR):
    os.makedirs(d, exist_ok=True)

CHUNK_LIMIT = 3600          # OpenAI input ceiling per request
KOKORO_CHUNK_LIMIT = 1000   # smaller for the local model: bounds per-request memory and latency
# Rough seconds-per-word for the on-form time estimate (calibrated from real runs:
# Kokoro ~0.26 s/word on this box, OpenAI ~0.06 s/word). Used by JS only.
KOKORO_SECS_PER_WORD = 0.26
OPENAI_SECS_PER_WORD = 0.06
MAX_INPUT = 400 * 1024
INSTRUCTIONS = ("Read as a calm, measured, articulate audiobook narrator. "
                "Natural pacing, clear diction, a short pause at each section heading.")

# TTS backends. Kokoro-82M runs locally (no third-party API, no cost). The hosted
# OpenAI gpt-4o-mini-tts bills per call, so it is gated to an allowlist of accounts
# (see may_use_openai); everyone else can only use Kokoro and never incurs charges.
# LECTOR_TTS_BACKEND is the site default backend ("kokoro" or "openai").
TTS_BACKEND = os.environ.get("LECTOR_TTS_BACKEND", "openai").lower()
KOKORO_URL = os.environ.get("KOKORO_URL", "http://127.0.0.1:3477/tts")
OPENAI_MODEL = "gpt-4o-mini-tts"
KOKORO_MODEL_LABEL = "Kokoro-82M (local, ONNX)"
OPENAI_VOICES = ["onyx", "alloy", "nova", "shimmer", "sage", "fable", "echo"]
KOKORO_VOICES = ["af_heart", "am_michael", "af_bella", "am_adam", "bf_emma", "bm_george", "af_nicole"]
ALL_VOICES = KOKORO_VOICES + OPENAI_VOICES
KOKORO_DEFAULT, OPENAI_DEFAULT = "af_heart", "onyx"
# Accounts allowed to use the paid OpenAI backend. Empty/unset => unrestricted
# (any account may use it); a comma-separated list => only those accounts may.
_oa = os.environ.get("LECTOR_OPENAI_ALLOWED", "").strip()
OPENAI_ALLOWED = {e.strip().lower() for e in _oa.split(",") if e.strip()} if _oa else None
USERNAME_RE = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
TOKENS_PATH = os.path.join(STATE_DIR, "tokens.json")
SHARES_PATH = os.path.join(STATE_DIR, "shares.json")
BASE_URL = os.environ.get("LECTOR_BASE_URL", "https://sotto.stephens.page")
SMTP_HOST = os.environ.get("SMTP_HOST")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "resend")
SMTP_PASS = os.environ.get("SMTP_PASS")
SMTP_FROM = os.environ.get("SMTP_FROM", "you@example.com")

app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=512 * 1024 * 1024,   # API uploads; convert() self-caps text at MAX_INPUT
                  SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SECURE=True,
                  SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=datetime.timedelta(days=30),
                  USE_X_SENDFILE=(os.environ.get("LECTOR_XSENDFILE") == "1"))

if not os.path.exists(SECRET_PATH):
    with open(os.open(SECRET_PATH, os.O_CREAT | os.O_WRONLY, 0o600), "w") as f:
        f.write(secrets.token_hex(32))
app.secret_key = open(SECRET_PATH).read().strip()

JOBS = {}
LOG_LOCK = threading.Lock()
USER_LOCK = threading.Lock()
SHARE_LOCK = threading.Lock()


# ----------------------------------------------------------------- job persistence
# Each job mirrors its state to disk so a restart or crash does not lose it:
#   <id>.json    lightweight state (status, progress, byte offset, ...)
#   <id>.md.src  the source text, written once
#   <id>.mp3     the partial/finished audio, fsync'd at each chunk boundary
# Interrupted (queued/running) jobs resume from the last completed chunk on start.
PERSIST_KEYS = ("status", "title", "owner", "voice", "limit", "total", "done",
                "bytes", "words", "notify", "autosave", "created", "secs", "saved", "file", "error")


def persist_job(job_id):
    job = JOBS.get(job_id)
    if not job:
        return
    data = {k: job[k] for k in PERSIST_KEYS if k in job}
    p = os.path.join(JOBS_DIR, job_id + ".json")
    try:
        with open(p + ".tmp", "w") as f:
            json.dump(data, f)
        os.replace(p + ".tmp", p)
    except OSError:
        pass


def remove_job_files(job_id):
    for ext in (".json", ".md.src", ".mp3"):
        try:
            os.remove(os.path.join(JOBS_DIR, job_id + ext))
        except OSError:
            pass


# ----------------------------------------------------------------------- accounts
def load_users():
    try:
        return json.load(open(USERS_PATH))
    except Exception:
        return {}


def save_users(users):
    tmp = USERS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp, USERS_PATH)


def user_lib(name):
    d = os.path.join(LIBRARY_DIR, name)
    os.makedirs(d, exist_ok=True)
    return d


def send_email(to, subject, html):
    """Send a transactional email via Resend SMTP. Returns True on success."""
    if not (SMTP_HOST and SMTP_PASS):
        log("-", to, "email-unconfigured", subject)
        return False
    msg = EmailMessage()
    msg["From"] = SMTP_FROM
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(re.sub(r"<[^>]+>", "", html))
    msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
            s.starttls()
            s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        log("-", to, "email-sent", subject)
        return True
    except Exception as e:
        log("-", to, "email-error", str(e)[:160])
        return False


def _load_tokens():
    try:
        return json.load(open(TOKENS_PATH))
    except Exception:
        return {}


def new_token(email, kind, ttl):
    tok = secrets.token_urlsafe(32)
    now = time.time()
    with USER_LOCK:
        toks = {k: v for k, v in _load_tokens().items() if v.get("exp", 0) > now}
        toks[tok] = {"email": email, "kind": kind, "exp": now + ttl}
        with open(TOKENS_PATH + ".tmp", "w") as f:
            json.dump(toks, f)
        os.replace(TOKENS_PATH + ".tmp", TOKENS_PATH)
    return tok


def peek_token(tok):
    e = _load_tokens().get(tok)
    return e if e and e.get("exp", 0) > time.time() else None


def pop_token(tok):
    with USER_LOCK:
        toks = _load_tokens()
        e = toks.pop(tok, None)
        with open(TOKENS_PATH + ".tmp", "w") as f:
            json.dump(toks, f)
        os.replace(TOKENS_PATH + ".tmp", TOKENS_PATH)
    return e if e and e.get("exp", 0) > time.time() else None


def current_user():
    return session.get("user")


def is_admin():
    return bool(load_users().get(current_user(), {}).get("admin"))


# ---------------------------------------------------------------- narration engine
def clean_markdown(md):
    out = []
    for raw in md.split("\n"):
        line = raw.rstrip()
        if re.match(r"^\s*(---+|```)\s*$", line):
            out.append("")
            continue
        if line.lstrip().startswith("|"):
            if re.match(r"^\s*\|[\s\|:\-]+\|?\s*$", line):
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|") if c.strip()]
            line = ". ".join(cells)
        for _ in range(3):
            line = re.sub(r"\[([^\]]*)\]\((?:[^)]*)\)", r"\1", line)
        line = re.sub(r"https?://\S+", "", line)
        line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        line = re.sub(r"^\s*>\s?", "", line)
        line = re.sub(r"^\s*[-*]\s+", "", line)
        line = line.replace("`", "").replace("**", "").replace("__", "")
        line = re.sub(r"(?<!\w)[*_](?=\w)", "", line)
        line = re.sub(r"(?<=\w)[*_](?!\w)", "", line)
        line = line.replace("*", "")
        out.append(line)
    text = "\n".join(out)
    text = re.sub(r"[①-⑨]", lambda m: " item " + str(ord(m.group()) - 0x245F), text)
    text = re.sub(r"\b([\w-]+)\.md\b", r"\1", text)
    text = text.replace("§", "section ").replace("→", " to ").replace("↔", " and ")
    text = text.replace("≤", "at most ").replace("≥", "at least ")
    text = text.replace("×", " times ").replace("%", " percent")
    text = text.replace("·", ". ").replace("&middot;", ". ").replace("&nbsp;", " ")
    text = text.replace("&amp;", "and").replace("&emsp;", " ")
    text = re.sub(r"(\d)\s*[–—\-]\s*(\d)", r"\1 to \2", text)
    text = text.replace("—", ", ").replace("–", ", ")
    text = re.sub(r"(\d)K\b", r"\1 thousand", text)
    text = re.sub(r"\$\s?(\d[\d,\.]*)", r"\1 dollars", text)
    text = re.sub(r"(\d)\+", r"\1 plus", text)
    for pat, val in {r"\bADRs\b": "architecture decision records",
                     r"\bADR\b": "architecture decision record",
                     r"\bhr/wk\b": "hours per week", r"\bK8s\b": "Kubernetes",
                     r"\bIaC\b": "infrastructure as code", r"\bJDs\b": "job descriptions",
                     r"\bJD\b": "job description", r"\bPR #148\b": "pull request 148"}.items():
        text = re.sub(pat, val, text)
    fixed = []
    for ln in text.split("\n"):
        s = ln.strip()
        if s and not re.search(r"[.!?:;,]$", s) and len(s) < 120:
            s += "."
        fixed.append(s)
    text = re.sub(r"[ \t]+", " ", "\n".join(fixed))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def chunk(text, limit=CHUNK_LIMIT):
    chunks, buf = [], ""
    for p in [p.strip() for p in text.split("\n\n") if p.strip()]:
        parts = re.split(r"(?<=[.!?])\s+", p) if len(p) > limit else [p]
        for part in parts:
            add = ("\n\n" if buf else "") + part
            if len(buf) + len(add) > limit and buf:
                chunks.append(buf)
                buf = part
            else:
                buf += add
    if buf:
        chunks.append(buf)
    return chunks


def _post(url, body, headers, label, timeout=180):
    """POST and return the response bytes, retrying a few times with backoff."""
    req = urllib.request.Request(url, data=body, headers=headers)
    last = None
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"{label} failed: {last}")


def tts_openai(text, voice):
    body = json.dumps({"model": OPENAI_MODEL, "voice": voice, "input": text,
                       "instructions": INSTRUCTIONS}).encode()
    return _post("https://api.openai.com/v1/audio/speech", body,
                 {"Authorization": "Bearer " + os.environ["OPENAI_API_KEY"],
                  "Content-Type": "application/json"}, "OpenAI TTS")


def tts_kokoro(text, voice):
    body = json.dumps({"text": text, "voice": voice}).encode()
    return _post(KOKORO_URL, body, {"Content-Type": "application/json"}, "Kokoro TTS", timeout=300)


def backend_of_voice(voice):
    return "openai" if voice in OPENAI_VOICES else "kokoro"


def may_use_openai(user):
    """Whether this account may use the paid OpenAI backend."""
    if "OPENAI_API_KEY" not in os.environ:
        return False
    return OPENAI_ALLOWED is None or (user or "").lower() in OPENAI_ALLOWED


def voices_for(user):
    """Voices this user may pick: Kokoro for all; OpenAI only if allowed."""
    return KOKORO_VOICES + (OPENAI_VOICES if may_use_openai(user) else [])


def voice_groups_for(user):
    groups = [("Kokoro-82M - runs locally on this server (free)", KOKORO_VOICES)]
    if may_use_openai(user):
        groups.append(("OpenAI " + OPENAI_MODEL + " - hosted, uses API credits", OPENAI_VOICES))
    return groups


def default_backend_for(user):
    """The site default backend if this user may use it, else Kokoro."""
    return "openai" if (TTS_BACKEND == "openai" and may_use_openai(user)) else "kokoro"


def default_voice_for(user):
    return OPENAI_DEFAULT if default_backend_for(user) == "openai" else KOKORO_DEFAULT


def preferred_voice(user):
    """The account's last-used voice if still available to it, else the default."""
    pref = load_users().get(user, {}).get("last_voice")
    return pref if pref in voices_for(user) else default_voice_for(user)


def remember_voice(user, voice):
    """Persist the account's voice choice for next time (no-op if unchanged)."""
    if load_users().get(user, {}).get("last_voice") == voice:
        return
    with USER_LOCK:
        users = load_users()
        if user in users:
            users[user]["last_voice"] = voice
            save_users(users)


def tts(text, voice):
    return tts_openai(text, voice) if backend_of_voice(voice) == "openai" else tts_kokoro(text, voice)


def fmt_duration(secs):
    """Human-readable duration: seconds when brief, minutes/hours when longer."""
    secs = int(secs or 0)
    if secs < 90:
        return f"{secs}s"
    m, s = divmod(secs, 60)
    if m < 60:
        return f"{m} min" if s < 5 else f"{m} min {s}s"
    h, m = divmod(m, 60)
    return f"{h} h {m} min" if m else f"{h} h"


app.jinja_env.globals["fmt_duration"] = fmt_duration


def _h(s):
    """Minimal HTML escape for values interpolated into emails."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def save_to_library(job, owner, job_id):
    """Copy a finished job's audio (and source text) into the owner's Library."""
    if job.get("saved") or not os.path.isfile(job.get("file", "")):
        return job.get("saved")
    slug = re.sub(r"[^a-z0-9]+", "-", job["title"].lower()).strip("-")[:60] or "narration"
    lib = user_lib(owner)
    name = slug + ".mp3"
    if os.path.exists(os.path.join(lib, name)):
        name = f"{slug}-{job_id[:6]}.mp3"
    shutil.copy2(job["file"], os.path.join(lib, name))
    src = job.get("md", "")
    if src:
        with open(os.path.join(lib, name[:-4] + ".md"), "w", encoding="utf-8") as f:
            f.write(src)
    # Keep the exact display name beside the audio so the Library shows it verbatim
    # (the filename is a lossy lowercased slug).
    with open(os.path.join(lib, name[:-4] + ".title"), "w", encoding="utf-8") as f:
        f.write(job.get("title", ""))
    # And how it was made, for the entry's detail page.
    with open(os.path.join(lib, name[:-4] + ".meta"), "w") as f:
        json.dump({"secs": job.get("secs"), "words": job.get("words"),
                   "voice": job.get("voice")}, f)
    job["saved"] = name
    log(owner, job["title"], "saved", name)
    return name


def lib_title(lib_dir, name):
    """Display title for a library item: the saved .title sidecar if present,
    otherwise derived from the filename (for entries saved before titles existed)."""
    tp = os.path.join(lib_dir, name[:-4] + ".title")
    if os.path.isfile(tp):
        try:
            t = open(tp, encoding="utf-8").read().strip()
            if t:
                return t
        except OSError:
            pass
    return re.sub(r"[-_]+", " ", name[:-4]).strip().capitalize()


AUDIO_EXT_RE = r"\.(mp3|m4a|aac)"


def audio_mime(name):
    return {"mp3": "audio/mpeg", "m4a": "audio/mp4", "aac": "audio/aac"}[name.rsplit(".", 1)[1]]


def strip_ext(name):
    return re.sub(AUDIO_EXT_RE + "$", "", name)


def audio_duration(path):
    """Duration in seconds: frame-parsed for mp3; uploaded formats carry it in .meta."""
    if path.endswith(".mp3"):
        return mp3_duration(path)
    try:
        return json.load(open(strip_ext(path) + ".meta")).get("duration_secs")
    except Exception:
        return None


def mp3_duration(path):
    """Approximate MP3 length in seconds from the first frame's bitrate (the
    output is CBR from both backends, so size/bitrate is accurate)."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            head = f.read(10)
            off = 0
            if head[:3] == b"ID3":
                off = 10 + (((head[6] & 0x7f) << 21) | ((head[7] & 0x7f) << 14)
                            | ((head[8] & 0x7f) << 7) | (head[9] & 0x7f))
            f.seek(off)
            hdr = f.read(4)
        if len(hdr) < 4 or hdr[0] != 0xFF or (hdr[1] & 0xE0) != 0xE0:
            return None
        mpeg1 = ((hdr[1] >> 3) & 0x3) == 3
        br_i = (hdr[2] >> 4) & 0xF
        if br_i in (0, 0xF):
            return None
        table = ([0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320] if mpeg1
                 else [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160])
        kbps = table[br_i]
        return int((size - off) * 8 / (kbps * 1000)) if kbps else None
    except Exception:
        return None


def run_job(job_id, md, voice, title, owner, resume=False):
    # Runs in a detached daemon thread, so it continues after the user leaves the
    # job page. Progress is fsync'd and mirrored to disk after every chunk, so an
    # interrupted job resumes from the last completed chunk on the next startup.
    # It stops early if the owner sets job["cancel"]; when started with "notify"
    # it saves the result and emails the owner a link.
    job = JOBS[job_id]
    started = time.time()
    try:
        if backend_of_voice(voice) == "openai" and not may_use_openai(owner):
            voice = KOKORO_DEFAULT  # safety: never bill OpenAI for an unauthorized account
        text = clean_markdown(md)
        limit = job.get("limit") or (KOKORO_CHUNK_LIMIT if backend_of_voice(voice) == "kokoro" else CHUNK_LIMIT)
        chunks = chunk(text, limit)
        total = len(chunks)
        out_path = os.path.join(JOBS_DIR, job_id + ".mp3")
        start_i = job.get("done", 0) if resume else 0
        if resume and 0 < start_i <= total and os.path.isfile(out_path):
            f = open(out_path, "r+b")          # continue the existing partial file
            f.truncate(job.get("bytes", 0))    # drop any half-written trailing chunk
            f.seek(job.get("bytes", 0))
        else:
            start_i = 0
            f = open(out_path, "wb")           # fresh, or partial file was lost
            job["bytes"] = 0
        job.update(status="running", total=total, done=start_i, voice=voice, limit=limit,
                   words=job.get("words") or len(text.split()))
        persist_job(job_id)
        cancelled = False
        try:
            for i in range(start_i, total):
                if job.get("cancel"):
                    cancelled = True
                    break
                f.write(tts(chunks[i], voice))
                f.flush()
                os.fsync(f.fileno())
                job["done"] = i + 1
                job["bytes"] = f.tell()
                persist_job(job_id)
        finally:
            f.close()
        if cancelled:
            job.update(status="stopped", secs=round(time.time() - started))
            persist_job(job_id)
            try:
                os.remove(out_path)
            except OSError:
                pass
            log(owner, title, "stopped", f"{job.get('done', 0)}/{total}ch")
            return
        job.update(status="done", file=out_path, secs=round(time.time() - started))
        persist_job(job_id)
        log(owner, title, "done", f"{job['words']}w/{total}ch/{job['secs']}s")
        if job.get("notify") or job.get("autosave"):
            # autosave: API clients (the Android app) have no manual "save" step,
            # so a job they submit must land in the Library on its own.
            saved = save_to_library(job, owner, job_id)   # durable target (email link / API pickup)
            persist_job(job_id)
            if job.get("notify"):
                link = f"{BASE_URL}/library#{saved}" if saved else f"{BASE_URL}/job/{job_id}"
                send_email(owner, f'sotto: "{title}" is ready',
                           f"<p>Your narration <b>{_h(title)}</b> is ready "
                           f"({job['words']} words, narrated in {fmt_duration(job['secs'])}).</p>"
                           f'<p><a href="{link}">Listen in your Library</a>.</p>')
    except Exception as e:
        job.update(status="error", error=str(e))
        persist_job(job_id)
        log(owner, title, "error", str(e)[:200])
        if job.get("notify"):
            send_email(owner, f'sotto: "{title}" could not be completed',
                       f"<p>Sorry - synthesizing <b>{_h(title)}</b> did not finish.</p>"
                       f'<p>You can <a href="{BASE_URL}/">try again</a>.</p>')


def log(who, title, status, detail):
    line = json.dumps({"t": datetime.datetime.now().isoformat(timespec="seconds"),
                       "user": who, "title": str(title)[:80], "status": status, "detail": detail})
    with LOG_LOCK:
        with open(LOG_PATH, "a") as f:
            f.write(line + "\n")


# ------------------------------------------------------------------------ templates
# Inline SVG favicon: a speaker + sound waves on the brand navy - "documents read aloud".
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
           '<rect width="32" height="32" rx="5" fill="#2A3F8F"/>'
           '<path d="M8 13h4l5-5v16l-5-5H8z" fill="#E6C66A"/>'
           '<path d="M20 12a5 5 0 0 1 0 8" fill="none" stroke="#E6C66A" stroke-width="2" stroke-linecap="round"/>'
           '<path d="M22.5 9a9 9 0 0 1 0 14" fill="none" stroke="#E6C66A" stroke-width="2" stroke-linecap="round"/>'
           '</svg>')

PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>{{title}}</title>
<link rel="icon" type="image/svg+xml" href="/favicon.svg">
<style>
/* Sotto's illuminated-manuscript style, matched to the Android app: the
   Books-of-Hours triad (lapis, gold, rubric) on vellum with iron-gall ink;
   EB Garamond for headings, UnifrakturMaguntia for the wordmark; squared
   corners. Dark mode is the same page by candlelight. */
@font-face{font-family:'EB Garamond';src:url('/font/eb_garamond.ttf') format('truetype');font-weight:400 700;font-display:swap}
@font-face{font-family:'Medieval';src:url('/font/medieval_sharp.ttf') format('truetype');font-display:swap}
:root{color-scheme:light dark;
 --vellum:#F3E9CF;--surface:#F8EFD7;--ink:#2A2014;--fade:#534935;
 --lapis:#2A3F8F;--gold:#8A6A12;--goldpale:#F1DFA6;--rubric:#A12C22;
 --on-lapis:#FBF3DD;--outline:#887A5C;--rule:#D0C3A2}
@media (prefers-color-scheme:dark){:root{
 --vellum:#1C1710;--surface:#14100A;--ink:#EBE0C8;--fade:#CFC2A2;
 --lapis:#AEC2F5;--gold:#E6C66A;--goldpale:#584400;--rubric:#F2B3A8;
 --on-lapis:#0E1F52;--outline:#988B6D;--rule:#4C4534}}
body{font:17px/1.6 -apple-system,Segoe UI,Roboto,sans-serif;max-width:46rem;margin:1.2rem auto;padding:0 1.1rem;color:var(--ink);background:var(--vellum)}
nav{display:flex;gap:.9rem;align-items:center;font-size:.9rem;border-bottom:1px solid var(--rule);padding-bottom:.6rem;margin-bottom:1.2rem}
nav .brand,.brand{font-family:'Medieval',serif;font-size:1.5rem;font-weight:400;text-transform:capitalize;color:var(--lapis);letter-spacing:.02em}nav .sp{flex:1}nav .who{color:var(--fade)}
h1{font-family:'Medieval',serif;font-size:2.1rem;font-weight:400;text-transform:capitalize;letter-spacing:.02em;color:var(--lapis);margin:0 0 .2rem}
h1 a{color:inherit;text-decoration:none}
h1.pagetitle{font-family:'EB Garamond',Georgia,serif;font-weight:600;font-size:1.9rem;text-transform:none;letter-spacing:0;color:var(--ink)}
h2,h3{font-family:'EB Garamond',Georgia,serif}
.sub{color:var(--rubric);font-family:'EB Garamond',Georgia,serif;font-size:1.15rem;margin:.1rem 0 1.4rem}
textarea{width:100%;min-height:13rem;font:14px/1.5 ui-monospace,Menlo,monospace;padding:.7rem;border:1px solid var(--outline);border-radius:3px;box-sizing:border-box;background:var(--surface);color:var(--ink)}
label{display:block;font-weight:600;margin:1rem 0 .3rem}
select,input{font:inherit;padding:.45rem;border:1px solid var(--outline);border-radius:3px;background:var(--surface);color:var(--ink)}
input[type=file]{border:0;padding:.4rem 0}
button{font:inherit;font-weight:600;background:var(--lapis);color:var(--on-lapis);border:0;border-radius:3px;padding:.6rem 1.3rem;margin-top:1rem;cursor:pointer}
.row{display:flex;gap:1.5rem;flex-wrap:wrap;align-items:end}
.muted{color:var(--fade);font-size:.92rem}a{color:var(--lapis)}
footer{margin-top:2.5rem;border-top:1px solid var(--rule);padding-top:1rem;color:var(--fade);font-size:.86rem}
footer::before{content:"\\2767";display:block;text-align:center;color:var(--gold);font-size:1.3rem;line-height:1;margin:0 0 .9rem}
.colophon{margin-top:.8rem;font-size:.8rem;color:var(--fade)}
.bar{height:.5rem;background:var(--goldpale);border-radius:2px;overflow:hidden;margin:.6rem 0}.bar>i{display:block;height:100%;background:var(--lapis)}
audio{width:100%;margin:.6rem 0 .2rem}
.skiprow{display:flex;gap:.5rem;margin:0 0 .4rem}
.skiprow button{margin:0;padding:.3rem .8rem;font-size:.85rem;background:var(--goldpale);color:var(--ink);border:1px solid var(--gold)}
.voicegroup{font-weight:600;font-size:.82rem;color:var(--gold);margin:.9rem 0 .15rem}
.voicegrid{display:flex;flex-wrap:wrap;gap:.7rem;margin:.3rem 0}
.vc{display:flex;flex-direction:column;gap:.2rem;font-size:.8rem;color:var(--fade)}.vc audio{width:12.5rem;height:2.2rem;margin:0}
table.u{border-collapse:collapse;width:100%}table.u td,table.u th{border-bottom:1px solid var(--rule);text-align:left;padding:.4rem .3rem;font-size:.95rem}
pre.src{white-space:pre-wrap;word-break:break-word;font:13px/1.5 ui-monospace,Menlo,monospace;background:var(--surface);padding:.7rem;border-radius:3px;overflow:auto;max-height:24rem;margin:.5rem 0 0;border:1px solid var(--rule)}
.shareurl{width:100%;box-sizing:border-box;font:12px ui-monospace,Menlo,monospace;padding:.4rem;margin:.3rem 0 0;color:var(--ink);background:var(--surface)}
.linkbtn{background:none;color:var(--lapis);border:0;padding:0;margin:0;font:inherit;font-size:.92rem;font-weight:600;cursor:pointer;text-decoration:underline}
</style></head><body>
<nav>{% if user %}<a class=brand href="/">sotto</a><a href="/library">library</a><span class=sp></span>
<span class=who>{{user}}</span><a href="/account">account</a>{% if admin %}<a href="/admin">admin</a>{% endif %}<a href="/logout">log out</a>
{% else %}<span class=brand>sotto</span>{% endif %}</nav>
{{body|safe}}
<footer>sotto reads documents aloud - it never emails, posts, or acts on your behalf; the only
thing it makes public is a share link you create yourself, which you can revoke.
{% if provider=='kokoro' %}By default, audio is synthesized on this server by Kokoro-82M
(ONNX), an openly licensed model trained on documented public-domain and permissively licensed
audio; those voices are synthetic and never leave the server.{% if may_openai %} OpenAI voices are
also available to your account and send text to OpenAI's hosted API (billable).{% endif %}{% else %}Audio is synthesized by
OpenAI ({{model}}); the voices are synthetic and the model's training provenance is not disclosed
by the vendor. The API key lives only in this server's environment.{% endif %}
<a href="/about">How it works &amp; boundaries</a>.
<div class=colophon>Colophon: set in EB Garamond &amp; MedievalSharp (SIL Open Font License).</div></footer>
<script>function lskip(id,n){var a=document.getElementById(id);if(a){a.currentTime=Math.max(0,(a.currentTime||0)+n);}}</script>
</body></html>"""

HOME = """<h1><a href="/">sotto</a></h1>
<p class=sub>Paste a markdown document. Get an MP3 you can listen to. &middot; <a href="/library">Library</a></p>
<form method=post action="/convert" enctype=multipart/form-data>
<input type=hidden name=_csrf value="{{csrf}}">
<label for=title>Name (optional)</label>
<input id=title name=title type=text maxlength=120 placeholder="Name this oration; defaults to the document's heading" style="width:100%;box-sizing:border-box">
<label for=md>Markdown</label>
<textarea id=md name=md placeholder="# Paste markdown here, or choose a .md file below"></textarea>
<p id=eta class=muted style="margin:.4rem 0 0;min-height:1.2em"></p>
<div class=row>
<div><label for=file>...or upload a file</label><input id=file type=file name=file accept=".md,.markdown,.txt"></div>
<div><label for=voice>Voice</label><select id=voice name=voice>{% for label, vs in groups %}<optgroup label="{{label}}">{% for v in vs %}<option{% if v==default %} selected{% endif %}>{{v}}</option>{% endfor %}</optgroup>{% endfor %}</select></div>
</div>
<label>Hear the voices</label>
{% for label, vs in groups %}<div class=voicegroup>{{label}}</div>
<div class=voicegrid>{% for v in vs %}<div class=vc><span>{{v}}</span><audio controls preload=none src="/sample/{{v}}"></audio></div>{% endfor %}</div>
{% endfor %}
<label style="font-weight:400;display:flex;align-items:center;gap:.5rem;margin-top:1.1rem"><input type=checkbox name=notify value=1 checked style="width:auto;margin:0"> Email me a link when it's ready (it runs on the server, so you can close this page)</label>
<button type=submit>Convert to audio</button>
</form>
<p class=muted style=margin-top:1.4rem>Citations like <code>&sect;102</code> are read as "section 102"; tables are read as plain sentences; links and raw URLs are dropped.</p>
<script>
(function(){
 var md=document.getElementById('md'),file=document.getElementById('file'),voice=document.getElementById('voice'),eta=document.getElementById('eta');
 var OAV={{ openai_voices|tojson }},RK={{kokoro_rate}},RO={{openai_rate}},fileWords=null;
 function fmt(s){s=Math.round(s);if(s<90)return s+' sec';var m=Math.round(s/60);if(m<60)return m+' min';var h=Math.floor(m/60);return h+' h '+(m%60)+' min';}
 function words(t){t=(t||'').trim();return t?t.split(/\\s+/).length:0;}
 function rate(){return OAV.indexOf(voice.value)>=0?RO:RK;}
 function show(){var w=fileWords!=null?fileWords:words(md.value);
  if(!w){eta.textContent='';return;}
  eta.textContent='Estimated narration time: about '+fmt(w*rate())+' · '+w.toLocaleString()+' words.';}
 md.addEventListener('input',function(){fileWords=null;show();});
 voice.addEventListener('change',show);
 file.addEventListener('change',function(){var f=file.files&&file.files[0];
  if(!f){fileWords=null;show();return;}
  var r=new FileReader();r.onload=function(){fileWords=words(r.result);show();};r.readAsText(f);});
 show();
})();
</script>"""

JOB = """<h1><a href="/">sotto</a></h1>
<p class=sub>{{job.title}}</p>
{% if job.status in ['queued','running','done'] %}<details style="margin:0 0 .8rem"><summary class=muted style="cursor:pointer">Rename</summary>
<form method=post action="/job/{{id}}/rename" style="margin-top:.4rem">
<input type=hidden name=_csrf value="{{csrf}}">
<input name=title type=text maxlength=120 value="{{job.title}}" style="width:65%;box-sizing:border-box">
<button class=linkbtn type=submit style="margin-left:.5rem">Save name</button>
</form></details>{% endif %}
{% if job.status in ['queued','running'] %}
<p><b>Narrating...</b> <span id=prog>{{job.get('done',0)}} / {{job.get('total','?')}}</span> chunks
{% if job.get('words') %}({{job.words}} words){% endif %}{% if elapsed %} <span class=muted>&middot; <span id=el>{{elapsed}}</span> so far</span>{% endif %}</p>
<div class=bar><i id=bar style="width:{{pct}}%"></i></div>
<p class=muted>This runs on the server. {% if job.get('notify') %}You can close this page - we'll email {{user}} a link when it's ready.{% else %}It keeps running if you close this page; reopen this URL to check on it.{% endif %}</p>
<div id=preview style="display:{% if job.get('done',0) %}block{% else %}none{% endif %};margin-top:1.1rem">
<p class=muted style="margin:0 0 .2rem"><span id=pvmsg>Loading a preview of the oration so far...</span></p>
<audio id=pv controls preload=none></audio>
<div class=skiprow><button type=button onclick="loadpv()">Load latest</button><button type=button onclick="lskip('pv',-15)">&laquo; 15s</button><button type=button onclick="lskip('pv',15)">15s &raquo;</button></div>
</div>
{% if job.get('cancel') %}<p class=muted>Stopping after the current chunk...</p>
{% else %}<form method=post action="/job/{{id}}/stop"><input type=hidden name=_csrf value="{{csrf}}"><button class=linkbtn type=submit>Stop narrating</button></form>{% endif %}
<script>
var JID="{{id}}",PK="lpos-"+JID;
function pvmsg(t){var m=document.getElementById('pvmsg');if(m)m.textContent=t;}
function spos(a){try{sessionStorage.setItem(PK,JSON.stringify({t:a.currentTime||0,p:!a.paused}))}catch(e){}}
function gpos(){try{return JSON.parse(sessionStorage.getItem(PK))}catch(e){return null}}
function loadpv(){var a=document.getElementById('pv');var t=a.currentTime||0;
 if(!t){var s=gpos();if(s)t=s.t||0;}   // restore position across a page refresh
 pvmsg("Loading a preview of the oration so far...");
 a.src="/job/"+JID+"/audio?n="+Date.now();a.load();
 a.addEventListener('loadedmetadata',function h(){try{a.currentTime=t;}catch(e){}pvmsg("Preview of the oration so far:");a.removeEventListener('loadedmetadata',h);});
 a.addEventListener('error',function h(){pvmsg("Preview will be ready shortly...");a.removeEventListener('error',h);});}
(function(){var pv=document.getElementById('preview');var a=document.getElementById('pv');var primed=false;
['timeupdate','pause','play'].forEach(function(ev){a.addEventListener(ev,function(){spos(a);});});
var s=gpos();
if(pv&&pv.style.display!=="none"){primed=true;loadpv();
 if(s&&s.p){a.addEventListener('loadedmetadata',function h(){a.play().catch(function(){});a.removeEventListener('loadedmetadata',h);});}}
function poll(){fetch("/job/"+JID+"/status",{cache:"no-store"}).then(function(r){return r.json();}).then(function(d){
 if(d.status!=="running"&&d.status!=="queued"){spos(a);location.reload();return;}
 document.getElementById('prog').textContent=d.done+" / "+(d.total||"?");
 document.getElementById('bar').style.width=d.pct+"%";
 if(d.elapsed){var e=document.getElementById('el');if(e)e.textContent=d.elapsed;}
 if(d.done>0){pv.style.display="block";if(!primed){primed=true;loadpv();}}
 setTimeout(poll,4000);
}).catch(function(){setTimeout(poll,6000);});}
setTimeout(poll,4000);})();
</script>
{% elif job.status=='stopped' %}
<p><b>Stopped.</b> You stopped this narration{% if job.get('total') %} after {{job.get('done',0)}} of {{job.total}} chunks{% endif %}.</p>
<p><a href="/">Convert another</a></p>
{% elif job.status=='done' %}
<p><b>Ready.</b> {{job.words}} words, {{job.total}} chunks, narrated in {{ fmt_duration(job.secs) }}.</p>
<audio id=pj controls preload=metadata src="/job/{{id}}/audio"></audio>
<div class=skiprow><button type=button onclick="lskip('pj',-15)">&laquo; 15s</button><button type=button onclick="lskip('pj',15)">15s &raquo;</button></div>
<script>
(function(){var a=document.getElementById('pj'),PK="lpos-{{id}}",s=null;
try{s=JSON.parse(sessionStorage.getItem(PK))}catch(e){}
if(s&&s.t){a.addEventListener('loadedmetadata',function h(){try{a.currentTime=s.t}catch(e){}if(s.p)a.play().catch(function(){});a.removeEventListener('loadedmetadata',h);});}
['timeupdate','pause','play'].forEach(function(ev){a.addEventListener(ev,function(){try{sessionStorage.setItem(PK,JSON.stringify({t:a.currentTime||0,p:!a.paused}))}catch(e){}});});
a.addEventListener('ended',function(){try{sessionStorage.removeItem(PK)}catch(e){}});
})();
</script>
<p><a href="/job/{{id}}/audio" download="{{slug}}.mp3">Download MP3</a> &middot; <a href="/">Convert another</a></p>
{% if job.get('saved') %}<p class=muted>Saved to <a href="/library#{{job.saved}}">Library</a> as {{job.saved}}.</p>
{% else %}<form method=post action="/job/{{id}}/save"><input type=hidden name=_csrf value="{{csrf}}"><button type=submit>Save to Library</button></form>{% endif %}
{% else %}
<p><b>Error.</b> {{job.get('error','unknown')}}</p><p><a href="/">Try again</a></p>
{% endif %}"""

LIB = """<h1><a href="/">sotto</a></h1>
<p class=sub>Library &middot; {{user}}'s saved narrations</p>
{% if active %}
<h2 style="font-size:1.05rem;margin:1.1rem 0 .3rem">In progress</h2>
{% for a in active %}<div data-job="{{a.id}}" style="margin:.6rem 0">
<a href="/job/{{a.id}}">{{a.title}}</a> <span class=muted>&middot; <span class=apct>{{a.done}} / {{a.total or '?'}}</span> chunks{% if a.status=='queued' %} &middot; queued{% endif %}</span>
<div class=bar><i class=abar style="width:{{a.pct}}%"></i></div>
</div>{% endfor %}
<hr style="border:0;border-top:1px solid #e3e3e3;margin:1.3rem 0">
{% endif %}
{% if items %}{% for it in items %}
<div id="{{it.name}}" style="margin:1.3rem 0;scroll-margin-top:1rem">
<b><a href="/library/{{it.name}}/view" style="text-decoration:none">{{it.title}}</a></b> <span class=muted>{% if it.length %}&middot; {{it.length}} {% endif %}&middot; {{it.size}}</span><br>
<audio id="lb{{loop.index}}" controls preload=none src="/library/{{it.name}}"></audio>
<div class=skiprow><button type=button onclick="lskip('lb{{loop.index}}',-15)">&laquo; 15s</button><button type=button onclick="lskip('lb{{loop.index}}',15)">15s &raquo;</button></div>
<a href="/library/{{it.name}}" download>Download audio</a>{% if it.text is not none %} &middot; <a href="/library/{{it.text_name}}" download>Download text</a>
<details style="margin-top:.5rem"><summary class=muted style="cursor:pointer">Source text</summary>
<pre class=src>{{it.text}}</pre></details>{% endif %}
{% if it.share_url %}
<div class=muted style="margin-top:.5rem">Shared{% if it.share_text %} with source text{% endif %} &middot; <form method=post action="/library/{{it.name}}/unshare" style="display:inline;margin:0"><input type=hidden name=_csrf value="{{csrf}}"><button class=linkbtn type=submit>stop sharing</button></form></div>
<input class=shareurl readonly onclick="this.select()" value="{{it.share_url}}">
{% else %}
<form method=post action="/library/{{it.name}}/share" style="margin-top:.5rem">
<input type=hidden name=_csrf value="{{csrf}}">
{% if it.text is not none %}<label style="font-weight:400;display:inline;margin:0"><input type=checkbox name=text value=1 checked style="width:auto"> include source text</label> &middot; {% endif %}<button class=linkbtn type=submit>create share link</button>
</form>
{% endif %}
<details style="margin-top:.4rem"><summary class=muted style="cursor:pointer">Rename</summary>
<form method=post action="/library/{{it.name}}/rename" style="margin-top:.4rem">
<input type=hidden name=_csrf value="{{csrf}}">
<input name=title type=text maxlength=120 value="{{it.title}}" style="width:65%;box-sizing:border-box">
<button class=linkbtn type=submit style="margin-left:.5rem">Save</button>
</form></details>
</div>
{% endfor %}{% elif not active %}<p class=muted>Nothing saved yet. Convert a document, then press "Save to Library" on the result.</p>{% endif %}
<p><a href="/">Back</a></p>
<script>
(function(){var rows=document.querySelectorAll('[data-job]');if(!rows.length)return;
function tick(){rows.forEach(function(row){var id=row.getAttribute('data-job');
 fetch('/job/'+id+'/status',{cache:'no-store'}).then(function(r){return r.json();}).then(function(d){
  if(d.status!=='running'&&d.status!=='queued'){location.reload();return;}
  row.querySelector('.apct').textContent=d.done+' / '+(d.total||'?');
  row.querySelector('.abar').style.width=d.pct+'%';
 }).catch(function(){});});setTimeout(tick,5000);}
setTimeout(tick,5000);})();
</script>"""

ENTRY = """<h1><a href="/">sotto</a></h1>
<p class=sub><a href="/library">Library</a> &middot; saved narration</p>
<h2 style="font-size:1.25rem;margin:.2rem 0 .1rem">{{heading}}</h2>
<p class=muted style="margin:.1rem 0 .6rem">{% if length %}{{length}} &middot; {% endif %}{{size}}{% if secs %} &middot; narrated in {{ fmt_duration(secs) }}{% endif %}{% if words %} &middot; {{words}} words{% endif %}</p>
<audio id=de controls preload=metadata src="/library/{{name}}"></audio>
<div class=skiprow><button type=button onclick="lskip('de',-15)">&laquo; 15s</button><button type=button onclick="lskip('de',15)">15s &raquo;</button></div>
<p><a href="/library/{{name}}" download>Download audio</a>{% if text is not none %} &middot; <a href="/library/{{text_name}}" download>Download text</a>{% endif %}</p>
<label for=rt>Name</label>
<form method=post action="/library/{{name}}/rename">
<input type=hidden name=_csrf value="{{csrf}}"><input type=hidden name=back value=view>
<input id=rt name=title type=text maxlength=120 value="{{heading}}" style="width:65%;box-sizing:border-box">
<button class=linkbtn type=submit style="margin-left:.5rem">Save name</button>
</form>
{% if share_url %}
<div class=muted style="margin-top:1rem">Shared{% if share_text %} with source text{% endif %} &middot; <form method=post action="/library/{{name}}/unshare" style="display:inline;margin:0"><input type=hidden name=_csrf value="{{csrf}}"><input type=hidden name=back value=view><button class=linkbtn type=submit>stop sharing</button></form></div>
<input class=shareurl readonly onclick="this.select()" value="{{share_url}}">
{% else %}
<form method=post action="/library/{{name}}/share" style="margin-top:1rem">
<input type=hidden name=_csrf value="{{csrf}}"><input type=hidden name=back value=view>
{% if text is not none %}<label style="font-weight:400;display:inline;margin:0"><input type=checkbox name=text value=1 checked style="width:auto"> include source text</label> &middot; {% endif %}<button class=linkbtn type=submit>create share link</button>
</form>
{% endif %}
{% if text is not none %}<details style="margin-top:1rem"><summary class=muted style="cursor:pointer">Source text</summary>
<pre class=src>{{text}}</pre></details>{% endif %}
<p style="margin-top:1.4rem"><a href="/library">Back to Library</a></p>"""

SHARE_VIEW = """<h1 class=pagetitle>{{heading}}</h1>
<p class=sub>Shared with you via sotto &middot; narrated audio</p>
<audio id=sh controls preload=metadata src="/share/{{token}}/audio"></audio>
<div class=skiprow><button type=button onclick="lskip('sh',-15)">&laquo; 15s</button><button type=button onclick="lskip('sh',15)">15s &raquo;</button></div>
<p><a href="/share/{{token}}/audio" download>Download audio</a>{% if has_text %} &middot; <a href="/share/{{token}}/text" download>Download text</a>{% endif %}</p>
{% if has_text %}<details><summary class=muted style="cursor:pointer">Source text</summary>
<pre class=src>{{text}}</pre></details>{% endif %}
<p class=muted style="margin-top:1.4rem">Anyone with this link can listen. It was shared deliberately by its owner, who can revoke it.</p>"""

LOGIN = """<h1>sotto</h1><p class=sub>Reads your documents aloud. Please sign in.</p>
{% if error %}<p style="color:#b00">{{error}}</p>{% endif %}
<form method=post action="/login{{nextq}}">
<input type=hidden name=_csrf value="{{csrf}}">
<label for=u>Email</label><input id=u name=username type=email autocomplete=username autofocus>
<label for=p>Password</label><input id=p name=password type=password autocomplete=current-password>
<button type=submit>Sign in</button>
</form>
<p class=muted><a href="/forgot">Forgot password?</a></p>"""

ACCOUNT = """<h1><a href="/">sotto</a></h1><p class=sub>Account &middot; {{user}}</p>
{% if msg %}<p style="color:#197">{{msg}}</p>{% endif %}{% if error %}<p style="color:#b00">{{error}}</p>{% endif %}
<form method=post action="/account">
<input type=hidden name=_csrf value="{{csrf}}">
<label for=c>Current password</label><input id=c name=current type=password autocomplete=current-password>
<label for=n>New password</label><input id=n name=new type=password autocomplete=new-password>
<button type=submit>Change password</button>
</form>
<h2 style="font-size:1.1rem;margin-top:1.8rem">App access tokens</h2>
<p class=muted>Issued by the Sotto Android app when you connect this account. Revoking one signs that device out.</p>
{% if tokens %}<table class=u><tr><th>Label</th><th>Created</th><th>Last used</th><th></th></tr>
{% for t in tokens %}<tr><td>{{t.label or "(unlabeled)"}}</td><td>{{t.created}}</td><td>{{t.last_used}}</td>
<td><form method=post action="/account/tokens/revoke" style="margin:0"><input type=hidden name=_csrf value="{{csrf}}"><input type=hidden name=hash value="{{t.hash}}"><button class=linkbtn type=submit>revoke</button></form></td></tr>{% endfor %}
</table>{% else %}<p class=muted>No tokens.</p>{% endif %}"""

ADMIN = """<h1><a href="/">sotto</a></h1><p class=sub>Admin &middot; accounts</p>
{% if msg %}<p style="color:#197">{{msg}}</p>{% endif %}{% if error %}<p style="color:#b00">{{error}}</p>{% endif %}
<table class=u><tr><th>Email</th><th>Role</th><th></th></tr>
{% for u,info in users.items() %}<tr><td>{{u}}</td><td>{{'admin' if info.admin else 'user'}}</td>
<td>{% if u != user %}<form method=post action="/admin/delete" style="margin:0"><input type=hidden name=_csrf value="{{csrf}}"><input type=hidden name=username value="{{u}}"><button style="padding:.25rem .7rem;margin:0;font-size:.8rem;background:#8a1a1a">delete</button></form>{% endif %}</td></tr>{% endfor %}
</table>
<h2 style="font-size:1.1rem;margin-top:1.6rem">Add account</h2>
<form method=post action="/admin/add">
<input type=hidden name=_csrf value="{{csrf}}">
<label for=nu>Email</label><input id=nu name=username type=email placeholder="name@example.com">
<label style="font-weight:400"><input type=checkbox name=admin value=1 style="width:auto"> administrator</label>
<button type=submit>Send invite</button>
</form>"""


FORGOT = """<h1>sotto</h1><p class=sub>Reset your password</p>
{% if sent %}<p>If an account exists for <b>{{email}}</b>, a password-reset link is on its way. Check your inbox.</p>
<p class=muted><a href="/login">Back to sign in</a></p>
{% else %}<form method=post action="/forgot"><input type=hidden name=_csrf value="{{csrf}}">
<label for=e>Email</label><input id=e name=email type=email autocomplete=username autofocus>
<button type=submit>Send reset link</button></form>
<p class=muted><a href="/login">Back to sign in</a></p>{% endif %}"""

RESET = """<h1>sotto</h1><p class=sub>{{ 'Set your password' if kind=='invite' else 'Choose a new password' }}</p>
{% if error %}<p style="color:#b00">{{error}}</p>{% endif %}
<p class=muted>For <b>{{email}}</b>.</p>
<form method=post><input type=hidden name=_csrf value="{{csrf}}">
<label for=p>New password</label><input id=p name=new type=password autocomplete=new-password autofocus>
<button type=submit>{{ 'Set password' if kind=='invite' else 'Reset password' }}</button></form>"""

RESET_BAD = """<h1>sotto</h1><p class=sub>Link expired</p>
<p>This link is invalid or has expired. <a href="/forgot">Request a new one</a>, or ask an administrator to re-send your invite.</p>"""

RESET_DONE = """<h1>sotto</h1><p class=sub>Password set</p><p>Your password is set. <a href="/login">Sign in</a>.</p>"""


def render(body_tpl, title, **ctx):
    u = current_user()
    provider = default_backend_for(u)
    model = OPENAI_MODEL if provider == "openai" else KOKORO_MODEL_LABEL
    common = dict(provider=provider, may_openai=may_use_openai(u), user=u, admin=is_admin())
    body = render_template_string(body_tpl, csrf=session.get("csrf", ""), **common, **ctx)
    return render_template_string(PAGE, title=title, model=model, body=body, **common)


# --------------------------------------------------------------------------- gate
PUBLIC = {"login", "healthz", "static", "forgot", "reset",
          "share", "share_audio", "share_text", "favicon", "font_file",
          "api_token", "api_me", "api_library", "api_audio", "api_text",
          "api_put", "api_patch", "api_delete"}


@app.before_request
def gate():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(16)
    is_api = bool(request.endpoint and request.endpoint.startswith("api_"))
    if not is_api and request.endpoint not in PUBLIC and not current_user():
        nxt = request.full_path if request.method == "GET" else None
        return redirect(url_for("login", next=nxt) if nxt else url_for("login"))
    if is_api:
        return   # token-authenticated JSON API: own auth in require_token, no session, no CSRF
    if request.method == "POST" and request.endpoint != "static":
        if not request.form.get("_csrf") or request.form.get("_csrf") != session.get("csrf"):
            abort(400)


# ------------------------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    nxt = request.args.get("next") or "/"
    if current_user():
        return redirect("/")
    error = None
    if request.method == "POST":
        users = load_users()
        u = (request.form.get("username") or "").strip().lower()
        info = users.get(u)
        if info and check_password_hash(info["pw"], request.form.get("password") or ""):
            session.permanent = True
            session["user"] = u
            session["csrf"] = secrets.token_urlsafe(16)
            log(u, "-", "login", request.headers.get("X-Forwarded-For", "-"))
            return redirect(nxt if nxt.startswith("/") else "/")
        error = "Incorrect username or password."
        log(u or "-", "-", "login-fail", "")
    nq = ("?next=" + nxt) if nxt and nxt != "/" else ""
    body = render_template_string(LOGIN, error=error, csrf=session.get("csrf"), nextq=nq)
    prov = default_backend_for(None)
    mdl = OPENAI_MODEL if prov == "openai" else KOKORO_MODEL_LABEL
    return render_template_string(PAGE, title="sotto - sign in", model=mdl, body=body,
                                  provider=prov, may_openai=False, user=None, admin=False)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/forgot", methods=["GET", "POST"])
def forgot():
    sent = False
    email = ""
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        sent = True
        if email in load_users():
            link = f"{BASE_URL}/reset/{new_token(email, 'reset', 3600)}"
            send_email(email, "Reset your sotto password",
                       "<p>We received a request to reset your sotto password.</p>"
                       f'<p><a href="{link}">Choose a new password</a>. This link expires in one hour.</p>'
                       "<p>If you did not request this, you can ignore this email.</p>")
        log(email or "-", "-", "reset-request", "")
    return render(FORGOT, "sotto - reset", sent=sent, email=email)


@app.route("/reset/<token>", methods=["GET", "POST"])
def reset(token):
    entry = peek_token(token)
    if not entry:
        return render(RESET_BAD, "sotto - link expired")
    if request.method == "POST":
        entry = pop_token(token)
        if not entry:
            return render(RESET_BAD, "sotto - link expired")
        new = request.form.get("new") or ""
        if len(new) < 8:
            return render(RESET, "sotto - set password", kind=entry["kind"],
                          email=entry["email"], error="Password must be at least 8 characters.")
        with USER_LOCK:
            users = load_users()
            if entry["email"] in users:
                users[entry["email"]]["pw"] = generate_password_hash(new)
                save_users(users)
        log(entry["email"], "-", "password-set", entry["kind"])
        return render(RESET_DONE, "sotto - done")
    return render(RESET, "sotto - set password", kind=entry["kind"], email=entry["email"], error=None)


@app.route("/account", methods=["GET", "POST"])
def account():
    msg = error = None
    if request.method == "POST":
        users = load_users()
        me = users[current_user()]
        if not check_password_hash(me["pw"], request.form.get("current") or ""):
            error = "Current password is incorrect."
        elif len(request.form.get("new") or "") < 8:
            error = "New password must be at least 8 characters."
        else:
            with USER_LOCK:
                users = load_users()
                users[current_user()]["pw"] = generate_password_hash(request.form["new"])
                save_users(users)
            log(current_user(), "-", "password-change", "")
            msg = "Password changed."
    mine = [dict(hash=h, **t) for h, t in _load_api_tokens().items() if t.get("email") == current_user()]
    mine.sort(key=lambda t: t.get("created", ""), reverse=True)
    return render(ACCOUNT, "sotto - account", msg=msg, error=error, tokens=mine)


@app.route("/account/tokens/revoke", methods=["POST"])
def account_token_revoke():
    h = request.form.get("hash") or ""
    with API_TOKEN_LOCK:
        toks = _load_api_tokens()
        entry = toks.get(h)
        if entry and entry.get("email") == current_user():
            toks.pop(h)
            _save_api_tokens(toks)
            log(current_user(), entry.get("label") or "-", "api-token-revoke", h[:8])
    return redirect(url_for("account"))


@app.route("/admin")
def admin():
    if not is_admin():
        abort(403)
    return render(ADMIN, "sotto - admin", users=load_users(), msg=None, error=None)


@app.route("/admin/add", methods=["POST"])
def admin_add():
    if not is_admin():
        abort(403)
    u = (request.form.get("username") or "").strip().lower()
    error = msg = None
    if not USERNAME_RE.match(u):
        error = "Enter a valid email address."
    elif u in load_users():
        error = "That account already exists."
    else:
        with USER_LOCK:
            users = load_users()
            users[u] = {"pw": generate_password_hash(secrets.token_urlsafe(24)),
                        "admin": bool(request.form.get("admin")),
                        "created": datetime.date.today().isoformat()}
            save_users(users)
        user_lib(u)
        link = f"{BASE_URL}/reset/{new_token(u, 'invite', 7 * 24 * 3600)}"
        ok = send_email(u, "You've been invited to sotto",
                        "<p>An administrator created a sotto account for you.</p>"
                        f'<p><a href="{link}">Set your password</a>, then sign in at {BASE_URL}. '
                        "This link expires in seven days.</p>")
        log(current_user(), u, "account-create", "admin" if request.form.get("admin") else "user")
        msg = (f"Created {u}. Invite emailed." if ok
               else f"Created {u}, but the email failed - send them this link: {link}")
    return render(ADMIN, "sotto - admin", users=load_users(), msg=msg, error=error)


@app.route("/admin/delete", methods=["POST"])
def admin_delete():
    if not is_admin():
        abort(403)
    u = (request.form.get("username") or "").strip().lower()
    error = msg = None
    if u == current_user():
        error = "You cannot delete your own account."
    elif u in load_users():
        with USER_LOCK:
            users = load_users()
            users.pop(u, None)
            save_users(users)
        log(current_user(), u, "account-delete", "")
        msg = f"Deleted account '{u}'. Their saved files remain on disk."
    return render(ADMIN, "sotto - admin", users=load_users(), msg=msg, error=error)


# --------------------------------------------------------------------- conversion
def calibrated_rates(user):
    """Seconds-per-word per backend, learned from this user's saved .meta history,
    falling back to the defaults. Uses the MEDIAN per-job rate so a resumed job
    (whose recorded time undercounts true wall-clock) doesn't skew the estimate."""
    samples = {"kokoro": [], "openai": []}
    try:
        names = os.listdir(user_lib(user))
    except OSError:
        names = []
    for n in names:
        if not n.endswith(".meta"):
            continue
        try:
            m = json.load(open(os.path.join(user_lib(user), n)))
        except Exception:
            continue
        secs, words = m.get("secs"), m.get("words")
        if secs and words and words >= 50:   # skip tiny/empty runs
            samples[backend_of_voice(m.get("voice") or "")].append(secs / words)

    def med(xs, default):
        if not xs:
            return default
        xs = sorted(xs)
        mid = len(xs) // 2
        return xs[mid] if len(xs) % 2 else (xs[mid - 1] + xs[mid]) / 2

    return (round(med(samples["kokoro"], KOKORO_SECS_PER_WORD), 4),
            round(med(samples["openai"], OPENAI_SECS_PER_WORD), 4))


@app.route("/")
def home():
    u = current_user()
    kr, orr = calibrated_rates(u)
    return render(HOME, "sotto", groups=voice_groups_for(u), default=preferred_voice(u),
                  openai_voices=OPENAI_VOICES if may_use_openai(u) else [],
                  kokoro_rate=kr, openai_rate=orr)


@app.route("/convert", methods=["POST"])
def convert():
    md = request.form.get("md", "")
    up = request.files.get("file")
    if up and up.filename:
        md = up.read().decode("utf-8", "replace")
    md = md.strip()
    if not md:
        return redirect(url_for("home"))
    if len(md.encode("utf-8")) > MAX_INPUT:
        return "Input too large (limit 400 KB).", 413
    owner = current_user()
    voice = request.form.get("voice", default_voice_for(owner))
    if voice not in voices_for(owner):   # enforce: unauthorized accounts can't pick OpenAI voices
        voice = default_voice_for(owner)
    remember_voice(owner, voice)         # preselect this voice next time
    title = (request.form.get("title") or "").strip()[:120]
    if not title:
        m = re.search(r"^#\s+(.+)$", md, re.M) or re.search(r"^(.{3,80})$", md, re.M)
        title = (m.group(1).strip() if m else "Untitled document")
    job_id = uuid.uuid4().hex
    limit = KOKORO_CHUNK_LIMIT if backend_of_voice(voice) == "kokoro" else CHUNK_LIMIT
    JOBS[job_id] = {"status": "queued", "title": title, "owner": owner, "voice": voice,
                    "limit": limit, "created": time.time(), "done": 0, "total": None,
                    "md": md, "notify": bool(request.form.get("notify"))}
    try:
        with open(os.path.join(JOBS_DIR, job_id + ".md.src"), "w", encoding="utf-8") as f:
            f.write(md)
    except OSError:
        pass
    persist_job(job_id)
    log(owner, title, "queued", f"{len(md.split())}w voice={voice}")
    threading.Thread(target=run_job, args=(job_id, md, voice, title, owner), daemon=True).start()
    return redirect(url_for("job_page", job_id=job_id))


def owned_job(job_id):
    job = JOBS.get(job_id)
    if not job or (job.get("owner") != current_user() and not is_admin()):
        abort(404)
    return job


@app.route("/job/<job_id>")
def job_page(job_id):
    job = owned_job(job_id)
    pct = int(100 * job.get("done", 0) / (job.get("total") or 1)) if job["status"] == "running" else (100 if job["status"] == "done" else 0)
    slug = re.sub(r"[^a-z0-9]+", "-", job["title"].lower()).strip("-")[:60] or "sotto"
    elapsed = fmt_duration(time.time() - job["created"]) if job.get("created") else None
    # A running job updates via JS polling (see JOB template) rather than a full
    # page refresh, so previewing the partial audio is not interrupted.
    return render(JOB, "sotto - " + job["title"][:40], job=job, id=job_id, pct=pct, slug=slug,
                  elapsed=elapsed)


@app.route("/job/<job_id>/audio")
def job_audio(job_id):
    job = owned_job(job_id)
    path = os.path.join(JOBS_DIR, job_id + ".mp3")
    # Serve the partial while running (preview) as well as the finished file.
    if job.get("status") not in ("running", "done") or not os.path.isfile(path):
        abort(404)
    slug = re.sub(r"[^a-z0-9]+", "-", job["title"].lower()).strip("-")[:60] or "sotto"
    return send_file(path, mimetype="audio/mpeg", download_name=slug + ".mp3",
                     conditional=not app.config["USE_X_SENDFILE"])


@app.route("/job/<job_id>/status")
def job_status(job_id):
    job = owned_job(job_id)
    total = job.get("total") or 0
    done = job.get("done", 0)
    pct = int(100 * done / total) if total else (100 if job.get("status") == "done" else 0)
    elapsed = fmt_duration(time.time() - job["created"]) if job.get("created") else None
    return {"status": job.get("status"), "done": done, "total": job.get("total"),
            "words": job.get("words"), "pct": pct, "elapsed": elapsed}


@app.route("/job/<job_id>/save", methods=["POST"])
def job_save(job_id):
    job = owned_job(job_id)
    if job.get("status") != "done" or not os.path.isfile(job.get("file", "")):
        abort(404)
    save_to_library(job, job["owner"], job_id)
    persist_job(job_id)
    return redirect(url_for("library"))


@app.route("/job/<job_id>/rename", methods=["POST"])
def job_rename(job_id):
    job = owned_job(job_id)
    new = (request.form.get("title") or "").strip()[:120]
    if new and new != job.get("title"):
        job["title"] = new
        persist_job(job_id)
        if job.get("saved"):   # already in the library -> keep its display name in step
            with open(os.path.join(user_lib(job["owner"]), job["saved"][:-4] + ".title"),
                      "w", encoding="utf-8") as f:
                f.write(new)
        log(job["owner"], new, "rename", job_id[:8])
    return redirect(url_for("job_page", job_id=job_id))


@app.route("/job/<job_id>/stop", methods=["POST"])
def job_stop(job_id):
    job = owned_job(job_id)
    if job.get("status") in ("queued", "running"):
        job["cancel"] = True   # run_job checks this between chunks
        log(job["owner"], job["title"], "stop-requested", "")
    return redirect(url_for("job_page", job_id=job_id))


def _load_shares():
    try:
        return json.load(open(SHARES_PATH))
    except Exception:
        return {}


def _save_shares(shares):
    tmp = SHARES_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(shares, f, indent=2)
    os.replace(tmp, SHARES_PATH)


def _user_shares(owner):
    """Map an owner's shared filenames to their share token + text flag."""
    out = {}
    for tok, s in _load_shares().items():
        if s.get("owner") == owner:
            out[s.get("name")] = {"token": tok, "text": bool(s.get("text"))}
    return out


@app.route("/library")
def library():
    lib = user_lib(current_user())
    shares = _user_shares(current_user())
    items = []
    for n in sorted(os.listdir(lib)):
        if n.endswith((".mp3", ".m4a", ".aac")):
            mb = os.path.getsize(os.path.join(lib, n)) / 1048576
            dur = audio_duration(os.path.join(lib, n))
            title = lib_title(lib, n)
            text = None
            tp = os.path.join(lib, n[:-4] + ".md")
            if os.path.isfile(tp):
                try:
                    text = open(tp, encoding="utf-8", errors="replace").read()
                except Exception:
                    text = None
            sh = shares.get(n)
            items.append({"name": n, "title": title, "size": f"{mb:.1f} MB",
                          "length": fmt_duration(dur) if dur else None,
                          "text": text, "text_name": (n[:-4] + ".md") if text is not None else None,
                          "share_url": (BASE_URL + "/share/" + sh["token"]) if sh else None,
                          "share_text": sh["text"] if sh else False})
    # In-progress orations: this user's jobs still being synthesized.
    active = []
    for jid, j in JOBS.items():
        if j.get("owner") == current_user() and j.get("status") in ("queued", "running"):
            total = j.get("total") or 0
            done = j.get("done", 0)
            active.append({"id": jid, "title": j.get("title", "Untitled"),
                           "status": j.get("status"), "done": done, "total": j.get("total"),
                           "pct": int(100 * done / total) if total else 0,
                           "created": j.get("created", 0)})
    active.sort(key=lambda a: a["created"], reverse=True)
    return render(LIB, "sotto - library", items=items, active=active)


@app.route("/library/<name>")
def library_file(name):
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.(mp3|m4a|aac|md)", name):
        abort(404)
    path = os.path.join(user_lib(current_user()), name)
    if not os.path.isfile(path):
        abort(404)
    mime = "text/markdown; charset=utf-8" if name.endswith(".md") else audio_mime(name)
    return send_file(path, mimetype=mime, conditional=not app.config["USE_X_SENDFILE"])


@app.route("/library/<name>/rename", methods=["POST"])
def library_rename(name):
    if not re.fullmatch(r"[A-Za-z0-9._-]+" + AUDIO_EXT_RE, name):
        abort(404)
    lib = user_lib(current_user())
    if not os.path.isfile(os.path.join(lib, name)):
        abort(404)
    new = (request.form.get("title") or "").strip()[:120]
    tp = os.path.join(lib, name[:-4] + ".title")  # only the display title changes; file/URL stay put
    if new:
        with open(tp, "w", encoding="utf-8") as f:
            f.write(new)
    else:
        try:
            os.remove(tp)   # blank -> revert to the filename-derived name
        except OSError:
            pass
    os.utime(os.path.join(lib, name), None)   # bump mtime: renames sync last-write-wins
    log(current_user(), new or name, "rename", name)
    if request.form.get("back") == "view":
        return redirect(url_for("library_entry", name=name))
    return redirect(url_for("library") + "#" + name)


@app.route("/library/<name>/view")
def library_entry(name):
    if not re.fullmatch(r"[A-Za-z0-9._-]+" + AUDIO_EXT_RE, name):
        abort(404)
    lib = user_lib(current_user())
    path = os.path.join(lib, name)
    if not os.path.isfile(path):
        abort(404)
    dur = audio_duration(path)
    meta = {}
    try:
        meta = json.load(open(path[:-4] + ".meta"))
    except Exception:
        pass
    text = None
    tp = path[:-4] + ".md"
    if os.path.isfile(tp):
        try:
            text = open(tp, encoding="utf-8", errors="replace").read()
        except Exception:
            text = None
    sh = _user_shares(current_user()).get(name)
    title = lib_title(lib, name)
    return render(ENTRY, "sotto - " + title[:40], name=name, heading=title,
                  size=f"{os.path.getsize(path) / 1048576:.1f} MB",
                  length=fmt_duration(dur) if dur else None,
                  secs=meta.get("secs"), words=meta.get("words"),
                  text=text, text_name=name[:-4] + ".md",
                  share_url=(BASE_URL + "/share/" + sh["token"]) if sh else None,
                  share_text=sh["text"] if sh else False)


# ------------------------------------------------------------------ share links
# A share link is a capability: an unguessable token grants read-only access to
# one saved item (audio, and optionally its source text). It is created and
# revoked only by the owner, and every create/revoke writes an audit line.
@app.route("/library/<name>/share", methods=["POST"])
def library_share(name):
    if not re.fullmatch(r"[A-Za-z0-9._-]+" + AUDIO_EXT_RE, name):
        abort(404)
    lib = user_lib(current_user())
    if not os.path.isfile(os.path.join(lib, name)):
        abort(404)
    want_text = bool(request.form.get("text")) and os.path.isfile(os.path.join(lib, name[:-4] + ".md"))
    with SHARE_LOCK:
        shares = _load_shares()
        tok = next((t for t, s in shares.items()
                    if s.get("owner") == current_user() and s.get("name") == name), None)
        if not tok:
            tok = secrets.token_urlsafe(24)
        shares[tok] = {"owner": current_user(), "name": name, "text": want_text,
                       "created": datetime.datetime.now().isoformat(timespec="seconds")}
        _save_shares(shares)
    log(current_user(), name, "share-create", "with-text" if want_text else "audio-only")
    if request.form.get("back") == "view":
        return redirect(url_for("library_entry", name=name))
    return redirect(url_for("library"))


@app.route("/library/<name>/unshare", methods=["POST"])
def library_unshare(name):
    with SHARE_LOCK:
        shares = _load_shares()
        gone = [t for t, s in shares.items()
                if s.get("owner") == current_user() and s.get("name") == name]
        for t in gone:
            shares.pop(t, None)
        if gone:
            _save_shares(shares)
    if gone:
        log(current_user(), name, "share-revoke", "")
    if request.form.get("back") == "view":
        return redirect(url_for("library_entry", name=name))
    return redirect(url_for("library"))


def _shared(token):
    """Return a valid share record for a token, or None."""
    s = _load_shares().get(token)
    if not s or not re.fullmatch(r"[A-Za-z0-9._-]+" + AUDIO_EXT_RE, s.get("name", "")):
        return None
    if not os.path.isfile(os.path.join(user_lib(s["owner"]), s["name"])):
        return None
    return s


@app.route("/share/<token>")
def share(token):
    s = _shared(token)
    if not s:
        abort(404)
    name = s["name"]
    title = lib_title(user_lib(s["owner"]), name)
    text = None
    if s.get("text"):
        tp = os.path.join(user_lib(s["owner"]), name[:-4] + ".md")
        if os.path.isfile(tp):
            try:
                text = open(tp, encoding="utf-8", errors="replace").read()
            except Exception:
                text = None
    return render(SHARE_VIEW, "sotto - " + title[:40], token=token, heading=title,
                  text=text, has_text=text is not None)


@app.route("/share/<token>/audio")
def share_audio(token):
    s = _shared(token)
    if not s:
        abort(404)
    return send_file(os.path.join(user_lib(s["owner"]), s["name"]), mimetype=audio_mime(s["name"]),
                     conditional=not app.config["USE_X_SENDFILE"])


@app.route("/share/<token>/text")
def share_text(token):
    s = _shared(token)
    if not s or not s.get("text"):
        abort(404)
    path = os.path.join(user_lib(s["owner"]), s["name"][:-4] + ".md")
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="text/markdown; charset=utf-8",
                     conditional=not app.config["USE_X_SENDFILE"])


@app.route("/sample/<voice>")
def sample(voice):
    if voice not in ALL_VOICES:
        abort(404)
    path = os.path.join(SAMPLES_DIR, voice + ".mp3")
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="audio/mpeg", conditional=not app.config["USE_X_SENDFILE"])


@app.route("/about")
def about():
    return render(ABOUT, "sotto - about")


@app.route("/favicon.svg")
@app.route("/favicon.ico")
def favicon():
    return Response(FAVICON, mimetype="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


# Self-hosted brand fonts (no third-party CDN, consistent with the boundary
# story): EB Garamond for headings, MedievalSharp for the wordmark - the same
# faces as the Android app's illuminated theme. Both SIL OFL. (MedievalSharp
# replaced UnifrakturMaguntia, whose blackletter capital S read as a "g".)
FONT_FILES = {"eb_garamond.ttf", "medieval_sharp.ttf"}


@app.route("/font/<name>")
def font_file(name):
    if name not in FONT_FILES:
        abort(404)
    resp = send_file(os.path.join(FONTS_DIR, name), mimetype="font/ttf", conditional=True)
    resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    return resp


@app.route("/healthz")
def healthz():
    return "ok\n", 200


ABOUT = """<h1><a href="/">sotto</a></h1>
<p class=sub>How it works, and the boundaries it keeps</p>
<p>sotto turns a markdown document into a narrated MP3. It cleans the markup first
(links and raw URLs dropped, <code>&sect;102</code> read as "section 102", tables flattened
into sentences), splits the text into chunks, sends each to {% if provider=='kokoro' %}a
text-to-speech model running on this server{% else %}OpenAI's text-to-speech API{% endif %},
and concatenates the audio.</p>
<p>It is also a small, deliberate example of how an AI automation can be built so a
person stays in command of it:</p>
<ul>
<li><b>Auth gate.</b> Every account is password-protected; passwords are stored only as
salted hashes, and sessions are signed, HTTPS-only cookies.</li>
{% if provider=='kokoro' %}
<li><b>Secret isolation.</b> There is no third-party API key to protect: speech is synthesized
on this server, so no credential and no audio ever leave it.</li>
<li><b>Bounded scope.</b> The only outbound call is to a text-to-speech model running on this
same machine; input is size-capped; there is no shell and no arbitrary network access.</li>
<li><b>Not delegated.</b> sotto produces audio and stops. It never acts on its own - it does
not email, post, or publish anything unless you deliberately create a share link, which you
control and can revoke at any time.</li>
<li><b>Traceability.</b> Every job and account action writes one audit line.</li>
<li><b>Provenance honesty.</b> The voice is synthetic, produced by Kokoro-82M - an openly
licensed (Apache-2.0) model trained on documented public-domain and permissively licensed audio.
sotto can name what reads to you rather than passing the audio off as neutral.</li>
{% else %}
<li><b>Secret isolation.</b> The OpenAI key lives only in this server process's
environment - never in a page, never in the source repository, never sent to your browser.</li>
<li><b>Bounded scope.</b> The only outbound call is to the text-to-speech API; input is
size-capped; there is no shell and no arbitrary network access.</li>
<li><b>Not delegated.</b> sotto produces audio and stops. It never acts on its own - it does
not email, post, or publish anything unless you deliberately create a share link, which you
control and can revoke at any time.</li>
<li><b>Traceability.</b> Every job and account action writes one audit line.</li>
<li><b>Provenance honesty.</b> The voice is synthetic and the model vendor does not disclose
its training data or the labor behind it; sotto says so rather than passing the audio off as neutral.</li>
{% endif %}
</ul>
<p><a href="/">Back</a></p>"""




# -------------------------------------------------------------------- API v1
# Token-authenticated JSON API for the Sotto Android app's sync flavor
# (contract: sotto-android docs/12-api-contract.md). Tokens are stored hashed;
# the web account page lists and revokes them. Narration never happens here -
# the API only moves finished orations and metadata.
API_TOKENS_PATH = os.path.join(STATE_DIR, "api_tokens.json")
API_TOKEN_LOCK = threading.Lock()
_api_rate = {}
API_NAME_RE = r"[a-z0-9-]{1,60}\.(mp3|m4a|aac)"


def _load_api_tokens():
    try:
        return json.load(open(API_TOKENS_PATH))
    except Exception:
        return {}


def _save_api_tokens(toks):
    with open(API_TOKENS_PATH + ".tmp", "w") as f:
        json.dump(toks, f, indent=1)
    os.replace(API_TOKENS_PATH + ".tmp", API_TOKENS_PATH)


def _api_err(status, key, detail=""):
    return jsonify({"error": key, "detail": detail}), status


def require_token(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return _api_err(401, "auth", "Bearer token required")
        h = hashlib.sha256(auth[7:].encode()).hexdigest()
        entry = _load_api_tokens().get(h)
        if not entry:
            return _api_err(401, "auth", "unknown or revoked token")
        with API_TOKEN_LOCK:
            toks = _load_api_tokens()
            if h in toks:
                toks[h]["last_used"] = datetime.datetime.now().isoformat(timespec="seconds")
                _save_api_tokens(toks)
        g.api_user = entry["email"]
        return f(*args, **kwargs)
    return wrapper


@app.route("/api/v1/token", methods=["POST"])
def api_token():
    ip = (request.headers.get("X-Forwarded-For") or request.remote_addr or "-").split(",")[0].strip()
    now_ts = time.time()
    _api_rate[ip] = [t for t in _api_rate.get(ip, []) if now_ts - t < 60]
    if len(_api_rate[ip]) >= 5:
        return _api_err(429, "rate-limited", "5 token requests per minute")
    _api_rate[ip].append(now_ts)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    info = load_users().get(email)
    if not info or not check_password_hash(info["pw"], data.get("password") or ""):
        log(email or "-", "-", "api-token-fail", ip)
        return _api_err(401, "auth", "incorrect email or password")
    tok = secrets.token_urlsafe(32)
    created = datetime.datetime.now().isoformat(timespec="seconds")
    with API_TOKEN_LOCK:
        toks = _load_api_tokens()
        toks[hashlib.sha256(tok.encode()).hexdigest()] = {
            "email": email, "created": created, "last_used": created,
            "label": str(data.get("label") or "")[:40]}
        _save_api_tokens(toks)
    log(email, "-", "api-token-create", data.get("label") or "")
    return jsonify({"token": tok, "created": created}), 201


@app.route("/api/v1/me")
@require_token
def api_me():
    u = g.api_user
    # Voices the account may request server-side. OpenAI voices appear only for
    # accounts in LECTOR_OPENAI_ALLOWED (the paid backend); everyone else sees
    # Kokoro only and can never incur API charges.
    return jsonify({"email": u, "may_openai": may_use_openai(u),
                    "kokoro_voices": KOKORO_VOICES,
                    "openai_voices": OPENAI_VOICES if may_use_openai(u) else [],
                    "default_voice": default_voice_for(u)})


@app.route("/api/v1/narrate", methods=["POST"])
@require_token
def api_narrate():
    """Submit text for server-side narration. The job runs on the server (so an
    allowed account can use the paid OpenAI backend) and auto-saves to the
    owner's Library on completion; poll /api/v1/jobs/<id> for the result name."""
    owner = g.api_user
    data = request.get_json(silent=True) or {}
    md = (data.get("text") or "").strip()
    if not md:
        return _api_err(400, "validation", "text required")
    if len(md.encode("utf-8")) > MAX_INPUT:
        return _api_err(413, "too-large", "input limit 400 KB")
    voice = (data.get("voice") or default_voice_for(owner)).strip()
    if voice not in voices_for(owner):
        # Reject rather than silently downgrade: an explicit OpenAI request from
        # an unauthorized account should fail loudly, not bill nothing quietly.
        return _api_err(403, "voice", f"{voice} not available to this account")
    title = (data.get("title") or "").strip()[:120]
    if not title:
        m = re.search(r"^#\s+(.+)$", md, re.M) or re.search(r"^(.{3,80})$", md, re.M)
        title = (m.group(1).strip() if m else "Untitled document")
    remember_voice(owner, voice)
    job_id = uuid.uuid4().hex
    limit = KOKORO_CHUNK_LIMIT if backend_of_voice(voice) == "kokoro" else CHUNK_LIMIT
    JOBS[job_id] = {"status": "queued", "title": title, "owner": owner, "voice": voice,
                    "limit": limit, "created": time.time(), "done": 0, "total": None,
                    "md": md, "notify": bool(data.get("notify")), "autosave": True}
    try:
        with open(os.path.join(JOBS_DIR, job_id + ".md.src"), "w", encoding="utf-8") as f:
            f.write(md)
    except OSError:
        pass
    persist_job(job_id)
    log(owner, title, "api-narrate", f"{len(md.split())}w voice={voice}")
    threading.Thread(target=run_job, args=(job_id, md, voice, title, owner), daemon=True).start()
    return jsonify({"job_id": job_id, "status": "queued", "voice": voice,
                    "backend": backend_of_voice(voice)}), 202


@app.route("/api/v1/jobs/<job_id>")
@require_token
def api_job(job_id):
    job = JOBS.get(job_id)
    if not job or job.get("owner") != g.api_user:
        return _api_err(404, "not-found", "no such job")
    total = job.get("total") or 0
    done = job.get("done", 0)
    pct = int(100 * done / total) if total else (100 if job.get("status") == "done" else 0)
    return jsonify({"status": job.get("status"), "done": done, "total": job.get("total"),
                    "words": job.get("words"), "pct": pct, "error": job.get("error"),
                    "name": job.get("saved")})   # set once the result is in the Library


@app.route("/api/v1/library")
@require_token
def api_library():
    lib = user_lib(g.api_user)
    entries = []
    for n in sorted(os.listdir(lib)):
        if not n.endswith((".mp3", ".m4a", ".aac")):
            continue
        p = os.path.join(lib, n)
        meta = {}
        try:
            meta = json.load(open(p[:-4] + ".meta"))
        except Exception:
            pass
        entries.append({
            "name": n, "title": lib_title(lib, n),
            "words": meta.get("words"), "secs": meta.get("secs"),
            "voice": meta.get("voice"), "size": os.path.getsize(p),
            "duration_secs": audio_duration(p), "mtime": int(os.path.getmtime(p)),
            "has_text": os.path.isfile(p[:-4] + ".md")})
    return jsonify({"entries": entries})


def _api_entry_path(name):
    if not re.fullmatch(API_NAME_RE, name):
        abort(404)
    path = os.path.join(user_lib(g.api_user), name)
    if not os.path.isfile(path):
        abort(404)
    return path


@app.route("/api/v1/library/<name>/audio")
@require_token
def api_audio(name):
    return send_file(_api_entry_path(name), mimetype=audio_mime(name),
                     conditional=not app.config["USE_X_SENDFILE"])


@app.route("/api/v1/library/<name>/text")
@require_token
def api_text(name):
    tp = _api_entry_path(name)[:-4] + ".md"
    if not os.path.isfile(tp):
        abort(404)
    return send_file(tp, mimetype="text/markdown; charset=utf-8",
                     conditional=not app.config["USE_X_SENDFILE"])


@app.route("/api/v1/library/<name>", methods=["PUT"])
@require_token
def api_put(name):
    if not re.fullmatch(API_NAME_RE, name):
        return _api_err(400, "validation", "name must match " + API_NAME_RE)
    audio = request.files.get("audio")
    if audio is None:
        return _api_err(400, "validation", "multipart part 'audio' required")
    lib = user_lib(g.api_user)
    path = os.path.join(lib, name)
    existed = os.path.exists(path)
    if existed and request.headers.get("If-None-Match") == "*":
        return _api_err(409, "conflict", "entry exists")
    audio.save(path + ".tmp")
    os.replace(path + ".tmp", path)
    text = request.files.get("text")
    if text is not None:
        text.save(path[:-4] + ".md")
    try:
        meta = json.loads(request.form.get("meta") or "{}")
    except ValueError:
        meta = {}
    with open(path[:-4] + ".meta", "w") as f:
        json.dump({k: meta.get(k) for k in ("secs", "words", "voice", "duration_secs")}, f)
    with open(path[:-4] + ".title", "w", encoding="utf-8") as f:
        f.write(str(meta.get("title") or "")[:120] or strip_ext(name))
    log(g.api_user, meta.get("title") or name, "api-upload",
        f"{name} {os.path.getsize(path)}B {'replaced' if existed else 'created'}")
    return jsonify({"name": name}), 200 if existed else 201


@app.route("/api/v1/library/<name>", methods=["PATCH"])
@require_token
def api_patch(name):
    path = _api_entry_path(name)
    title = ((request.get_json(silent=True) or {}).get("title") or "").strip()[:120]
    if not title:
        return _api_err(400, "validation", "title required")
    with open(path[:-4] + ".title", "w", encoding="utf-8") as f:
        f.write(title)
    os.utime(path, None)   # LWW: renames bump the entry's mtime
    log(g.api_user, title, "api-rename", name)
    return jsonify({"name": name, "title": title})


@app.route("/api/v1/library/<name>", methods=["DELETE"])
@require_token
def api_delete(name):
    path = _api_entry_path(name)
    with SHARE_LOCK:   # revoke any share links pointing at it
        shares = _load_shares()
        gone = [t for t, sh in shares.items()
                if sh.get("owner") == g.api_user and sh.get("name") == name]
        for t in gone:
            shares.pop(t, None)
        if gone:
            _save_shares(shares)
    for ext in ("", ".md", ".title", ".meta"):
        try:
            os.remove((path[:-4] + ext) if ext else path)
        except OSError:
            pass
    log(g.api_user, name, "api-delete", f"shares-revoked={len(gone)}")
    return "", 204


def resume_jobs():
    """On startup: reload persisted jobs, prune old finished ones, and resume any
    that were interrupted (queued/running) from their last completed chunk."""
    now = time.time()
    for fn in sorted(os.listdir(JOBS_DIR)):
        if not fn.endswith(".json"):
            continue
        job_id = fn[:-5]
        try:
            data = json.load(open(os.path.join(JOBS_DIR, fn)))
        except Exception:
            continue
        if data.get("status") in ("done", "error", "stopped"):
            if now - data.get("created", now) > 7 * 86400:
                remove_job_files(job_id)          # prune finished jobs after a week
            else:
                JOBS[job_id] = data               # keep viewable across restarts
            continue
        src = os.path.join(JOBS_DIR, job_id + ".md.src")
        if not os.path.isfile(src):
            data.update(status="error", error="interrupted; source text unavailable")
            JOBS[job_id] = data
            persist_job(job_id)
            continue
        try:
            md = open(src, encoding="utf-8").read()
        except OSError:
            continue
        data["md"] = md
        JOBS[job_id] = data
        log(data.get("owner"), data.get("title", "?"), "resumed",
            f"{data.get('done', 0)}/{data.get('total', '?')}ch")
        threading.Thread(target=run_job,
                         args=(job_id, md, data.get("voice", KOKORO_DEFAULT),
                               data.get("title", "Untitled"), data.get("owner")),
                         kwargs={"resume": True}, daemon=True).start()


# Only the real service sets LECTOR_RESUME=1 (see deploy/lector.service), so a
# test import of this module never re-spawns workers for in-flight jobs.
if os.environ.get("LECTOR_RESUME") == "1":
    resume_jobs()


if __name__ == "__main__":
    app.run("127.0.0.1", 3476, debug=True)
