"""Server-side Narration jobs and their restart checkpoints."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
from threading import Lock, Thread
import time
from uuid import uuid4

from library_store import Library


_ACTIVE = ("queued", "running")
_TERMINAL = ("done", "error", "stopped")
_RETENTION_SECONDS = 7 * 86400
_SNAPSHOT_FIELDS = ("status", "title", "owner", "voice", "total", "done", "words",
                    "notify", "created", "secs", "saved", "error")


@dataclass
class _Job:
    id: str
    record: dict
    source: str | None = None
    cancel: bool = False
    lock: Lock = field(default_factory=Lock, init=False, repr=False)


class NarrationJobs:
    def __init__(self, jobs_dir, library_dir, *, clean, chunk, synthesize, chunk_limit,
                 execution_voice, audit, notify):
        self._directory = Path(jobs_dir)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._library_dir = library_dir
        self._clean = clean
        self._chunk = chunk
        self._synthesize = synthesize
        self._chunk_limit = chunk_limit
        self._execution_voice = execution_voice
        self._audit = audit
        self._notify = notify
        self._jobs = {}
        self._registry_lock = Lock()
        self._library_lock = Lock()

    def _path(self, job_id, suffix):
        return self._directory / (job_id + suffix)

    def _persist(self, job):
        # State is replaced only after the audio for the checkpoint is durable.
        path = self._path(job.id, ".json")
        temporary = path.with_suffix(".json.tmp")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(job.record, stream)
        temporary.replace(path)

    def _register(self, job):
        with self._registry_lock:
            if job.id in self._jobs:
                return False
            self._jobs[job.id] = job
            return True

    def _get(self, job_id):
        with self._registry_lock:
            return self._jobs.get(job_id)

    def _start(self, job):
        title = job.record.get("title", "Untitled")
        Thread(target=self._run, args=(job, title), daemon=True).start()

    def submit(self, owner, source, voice, title, *, notify=False, autosave=False):
        if not title:
            heading = re.search(r"^#\s+(.+)$", source, re.M) or re.search(r"^(.{3,80})$", source, re.M)
            title = heading.group(1).strip() if heading else "Untitled document"
        job = _Job(uuid4().hex, dict(status="queued", title=title, owner=owner, voice=voice,
                                    limit=self._chunk_limit(voice), created=time.time(),
                                    done=0, total=None, notify=notify, autosave=autosave), source)
        self._path(job.id, ".md.src").write_bytes(source.encode("utf-8"))
        self._persist(job)
        self._audit(owner, title, "api-narrate" if autosave else "queued",
                    f"{len(source.split())}w voice={voice}")
        self._register(job)
        self._start(job)
        return job.id

    def restore(self):
        """Load retained jobs and start a worker for each interrupted job."""
        now = time.time()
        for path in sorted(self._directory.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(record, dict):
                continue
            job = _Job(path.stem, record)
            if record.get("status") in _TERMINAL:
                if now - record.get("created", now) > _RETENTION_SECONDS:
                    for suffix in (".json", ".md.src", ".mp3"):
                        try:
                            self._path(job.id, suffix).unlink()
                        except OSError:
                            pass
                else:
                    self._register(job)
                continue
            job.source = self._read_source(job)
            if job.source is None:
                record.update(status="error", error="interrupted; source text unavailable")
                self._persist(job)
                self._register(job)
                continue
            if self._register(job):
                self._audit(record.get("owner"), record.get("title", "?"), "resumed",
                            f"{record.get('done', 0)}/{record.get('total', '?')}ch")
                self._start(job)

    def _snapshot(self, job):
        record = job.record
        done, total = record.get("done", 0), record.get("total")
        pct = int(100 * done / total) if total else (100 if record.get("status") == "done" else 0)
        result = {key: record[key] for key in _SNAPSHOT_FIELDS if key in record}
        result.setdefault("title", "Untitled")
        return dict(result, id=job.id, done=done, total=total, pct=pct, cancel=job.cancel)

    def snapshot(self, job_id):
        job = self._get(job_id)
        if job is not None:
            with job.lock:
                return self._snapshot(job)
        return None

    def active_for(self, owner):
        with self._registry_lock:
            jobs = list(self._jobs.values())
        active = []
        for job in jobs:
            with job.lock:
                if job.record.get("owner") == owner and job.record.get("status") in _ACTIVE:
                    active.append(self._snapshot(job))
        return sorted(active, key=lambda job: job.get("created", 0), reverse=True)

    def _read_source(self, job):
        if job.source is not None:
            return job.source
        try:
            return self._path(job.id, ".md.src").read_bytes().decode("utf-8")
        except (OSError, UnicodeError):
            return None

    def source(self, job_id):
        job = self._get(job_id)
        if job is not None:
            with job.lock:
                return self._read_source(job)
        return None

    def _audio_file(self, job):
        path = self._path(job.id, ".mp3")
        return path if path.is_file() else None

    def playable_audio(self, job_id):
        job = self._get(job_id)
        if job is not None:
            with job.lock:
                if job.record.get("status") in ("running", "done"):
                    return self._audio_file(job)
        return None

    def stop(self, job_id):
        job = self._get(job_id)
        if job is not None:
            with job.lock:
                if job.record.get("status") in _ACTIVE:
                    job.cancel = True
                    self._audit(job.record.get("owner"), job.record["title"], "stop-requested", "")

    def rename(self, job_id, title):
        job = self._get(job_id)
        if job is None or not title:
            return
        with job.lock:
            record = job.record
            if title != record.get("title"):
                owner = record["owner"]
                record["title"] = title
                self._persist(job)
                if record.get("saved"):
                    Library(self._library_dir, owner).set_title(record["saved"], title)
                self._audit(owner, title, "rename", job.id[:8])

    def save(self, job_id):
        """Save a completed job once and return its Library filename."""
        job = self._get(job_id)
        if job is None:
            return None
        with job.lock:
            record = job.record
            audio = self._audio_file(job)
            if record.get("status") != "done" or audio is None:
                return None
            if not record.get("saved"):
                owner, title = record["owner"], record["title"]
                with self._library_lock:
                    name = Library(self._library_dir, owner).save_narration(
                        audio, title=title, source=self._read_source(job), metadata=record, job_id=job.id)
                record["saved"] = name
                self._audit(owner, title, "saved", name)
            self._persist(job)
            return record["saved"]

    def _checkpoint(self, job, audio, total):
        done, offset = job.record.get("done", 0), job.record.get("bytes")
        if 0 < done <= total and offset is not None and audio.is_file() and 0 <= offset <= audio.stat().st_size:
            return done, offset
        return 0, 0

    def _synthesize_audio(self, job, voice, title, started):
        record = job.record
        text = self._clean(job.source)
        limit = record.get("limit") or self._chunk_limit(voice)
        chunks = self._chunk(text, limit)
        total = len(chunks)
        audio = self._path(job.id, ".mp3")
        done, offset = self._checkpoint(job, audio, total)
        cancelled = False
        with audio.open("r+b" if done else "wb") as stream:
            with job.lock:
                if done:
                    stream.truncate(offset)
                    stream.seek(offset)
                record.update(status="running", total=total, done=done, bytes=offset, voice=voice,
                              limit=limit, words=record.get("words") or len(text.split()))
                self._persist(job)
            for index in range(done, total):
                with job.lock:
                    if job.cancel:
                        cancelled = True
                        break
                sound = self._synthesize(chunks[index], voice)
                with job.lock:
                    stream.write(sound)
                    stream.flush()
                    os.fsync(stream.fileno())
                    record.update(done=index + 1, bytes=stream.tell())
                    self._persist(job)
        with job.lock:
            secs = round(time.time() - started)
            if cancelled:
                record.update(status="stopped", secs=secs)
                self._persist(job)
                try:
                    audio.unlink()
                except OSError:
                    pass
                self._audit(record.get("owner"), title, "stopped", f"{record['done']}/{total}ch")
            else:
                record.update(status="done", file=str(audio), secs=secs)
                self._persist(job)
                self._audit(record.get("owner"), title, "done", f"{record['words']}w/{total}ch/{secs}s")
        return not cancelled

    def _run(self, job, title):
        started = time.time()
        record = job.record
        owner = record.get("owner")
        try:
            voice = self._execution_voice(owner, record.get("voice"))
            completed = self._synthesize_audio(job, voice, title, started)
        except Exception as error:
            with job.lock:
                record.update(status="error", error=str(error))
                self._persist(job)
                self._audit(owner, title, "error", str(error)[:200])
                failed = dict(self._snapshot(job), title=title)
            if failed.get("notify"):
                self._notify(failed, False)
            return
        if completed and (record.get("autosave") or record.get("notify")):
            try:
                self.save(job.id)
            except Exception as error:
                self._audit(owner, title, "error", str(error)[:200])
                if record.get("notify"):
                    self._notify(dict(self.snapshot(job.id), title=title), False)
            else:
                if record.get("notify"):
                    self._notify(dict(self.snapshot(job.id), title=title), True)
