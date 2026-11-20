from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import time
import unittest
from unittest.mock import patch

from library_store import Library
from narration_jobs import NarrationJobs


OWNER = "reader@example.com"
SOURCE = "oneTWOend"
FIRST_AUDIO = b"<one>"
COMPLETE_AUDIO = b"<one><TWO><end>"


class NarrationJobsTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.jobs_dir = root / "jobs"
        self.jobs_dir.mkdir()
        self.library_dir = root / "library"
        self.audit = []

    def service(self, synthesize=None, *, notify=None):
        return NarrationJobs(
            self.jobs_dir, self.library_dir, clean=str.strip,
            chunk=lambda text, limit: [text[i:i + limit] for i in range(0, len(text), limit)],
            synthesize=synthesize or self.audio, chunk_limit=lambda voice: 2 if voice == "fallback" else 3,
            execution_voice=lambda owner, voice: "fallback" if voice == "paid" else voice,
            audit=lambda *event: self.audit.append(event),
            notify=notify or (lambda job, succeeded: None),
        )

    @staticmethod
    def audio(text, voice):
        return f"<{text}>".encode()

    def wait_for_terminal(self, jobs, job_id):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            snapshot = jobs.snapshot(job_id)
            if snapshot["status"] in ("done", "error", "stopped"):
                return snapshot
            time.sleep(0.005)
        self.fail(f"Job did not finish: {jobs.snapshot(job_id)}")

    def write_record(self, job_id, *, source=SOURCE, audio=None, voice="local", **fields):
        path = self.jobs_dir / f"{job_id}.json"
        path.write_text(json.dumps(dict(title="Fixture", owner=OWNER, voice=voice, **fields)))
        if source is not None:
            (self.jobs_dir / f"{job_id}.md.src").write_bytes(source.encode())
        if audio is not None:
            (self.jobs_dir / f"{job_id}.mp3").write_bytes(audio)
        return path

    def test_checkpoint_preview_and_stop_between_chunks(self):
        second_chunk = Event()
        release = Event()
        calls = []

        def synthesize(text, voice):
            calls.append(text)
            if text == "TWO":
                second_chunk.set()
                if not release.wait(5):
                    raise TimeoutError("test did not release synthesis")
            return self.audio(text, voice)

        jobs = self.service(synthesize)
        job_id = jobs.submit(OWNER, SOURCE, "local", "")
        audio = self.jobs_dir / (job_id + ".mp3")
        try:
            self.assertTrue(second_chunk.wait(5))
            snapshot, = jobs.active_for(OWNER)
            self.assertEqual((snapshot["id"], snapshot["title"], snapshot["status"]), (job_id, SOURCE, "running"))
            self.assertEqual((snapshot["done"], snapshot["total"], snapshot["pct"]), (1, 3, 33))
            self.assertEqual(jobs.active_for("other@example.com"), [])
            snapshot["done"] = 99
            self.assertEqual(jobs.snapshot(job_id)["done"], 1)
            self.assertEqual(jobs.source(job_id), SOURCE)
            self.assertEqual(jobs.playable_audio(job_id).read_bytes(), FIRST_AUDIO)
            checkpoint = json.loads((self.jobs_dir / (job_id + ".json")).read_text())
            self.assertEqual((checkpoint["done"], checkpoint["bytes"], checkpoint["limit"]), (1, 5, 3))
            self.assertIsNone(jobs.save(job_id))
            jobs.stop(job_id)
            self.assertTrue(jobs.snapshot(job_id)["cancel"])
        finally:
            release.set()
            final = self.wait_for_terminal(jobs, job_id)
        self.assertEqual((final["status"], final["done"], final["pct"]), ("stopped", 2, 66))
        self.assertEqual(calls, ["one", "TWO"])
        self.assertEqual(jobs.active_for(OWNER), [])
        self.assertIsNone(jobs.playable_audio(job_id))
        self.assertFalse(audio.exists())
        self.assertEqual([event[2] for event in self.audit], ["queued", "stop-requested", "stopped"])

    def test_recovery_trims_tail_and_keeps_saved_chunk_limit_after_voice_recheck(self):
        calls = []

        def synthesize(text, voice):
            calls.append((text, voice))
            return self.audio(text, voice)

        jobs = self.service(synthesize)
        uninterrupted = jobs.submit(OWNER, SOURCE, "local", "Fixture")
        self.assertEqual(self.wait_for_terminal(jobs, uninterrupted)["status"], "done")
        self.assertEqual(jobs.playable_audio(uninterrupted).read_bytes(), COMPLETE_AUDIO)
        calls.clear()

        # This record was written when the user's paid voice was available.
        self.write_record("interrupted", status="running", voice="paid", limit=3, done=1, bytes=5, total=3,
                          audio=FIRST_AUDIO + b"uncommitted")
        restarted = self.service(synthesize)
        restarted.restore()
        snapshot = self.wait_for_terminal(restarted, "interrupted")
        self.assertEqual((snapshot["status"], snapshot["voice"], snapshot["done"]), ("done", "fallback", 3))
        self.assertEqual(calls, [("TWO", "fallback"), ("end", "fallback")])
        self.assertEqual(restarted.playable_audio("interrupted").read_bytes(), COMPLETE_AUDIO)
        self.assertEqual(restarted.playable_audio(uninterrupted).read_bytes(), COMPLETE_AUDIO)
        self.assertEqual([event[2] for event in self.audit], ["queued", "done", "resumed", "done"])

    def test_queued_job_and_running_job_without_partial_audio_start_from_beginning(self):
        self.write_record("queued", status="queued", done=0, total=None)
        self.write_record("missing", status="running", done=2, bytes=10, total=3)
        jobs = self.service()
        jobs.restore()
        for job_id in ("queued", "missing"):
            with self.subTest(job_id=job_id):
                snapshot = self.wait_for_terminal(jobs, job_id)
                self.assertEqual((snapshot["status"], snapshot["done"], snapshot["pct"]), ("done", 3, 100))
                self.assertEqual(jobs.playable_audio(job_id).read_bytes(), COMPLETE_AUDIO)

    def test_restore_retains_recent_terminal_records_and_prunes_old_ones(self):
        old = time.time() - 8 * 86400
        for status in ("done", "stopped", "error"):
            self.write_record(f"old-{status}", status=status, created=old, audio=FIRST_AUDIO)
            self.write_record(f"recent-{status}", status=status, audio=FIRST_AUDIO)
        self.write_record("no-source", source=None, status="running", done=1, bytes=5, audio=FIRST_AUDIO)
        jobs = self.service()
        jobs.restore()
        for status in ("done", "stopped", "error"):
            self.assertIsNone(jobs.snapshot(f"old-{status}"))
            self.assertEqual(list(self.jobs_dir.glob(f"old-{status}.*")), [])
            self.assertEqual(jobs.snapshot(f"recent-{status}")["status"], status)
        self.assertEqual(jobs.source("recent-done"), SOURCE)
        self.assertEqual(jobs.playable_audio("recent-done").read_bytes(), FIRST_AUDIO)
        self.assertEqual(jobs.snapshot("no-source")["error"], "interrupted; source text unavailable")
        self.assertIsNone(jobs.playable_audio("no-source"))
        self.assertEqual(self.audit, [])

    def test_concurrent_saves_of_one_restored_job_create_one_library_entry(self):
        source = "# Fixture\r\n\r\nExact **Markdown**."
        self.write_record("restored", source=source, status="done", audio=COMPLETE_AUDIO)
        jobs = self.service()
        jobs.restore()
        start = Barrier(4, timeout=5)

        def save():
            start.wait()
            return jobs.save("restored")

        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(lambda _: save(), range(4))), ["fixture.mp3"] * 4)
        restarted = self.service()
        restarted.restore()
        self.assertEqual(restarted.save("restored"), "fixture.mp3")
        library = Library(self.library_dir, OWNER)
        entry, = library.entries()
        self.assertEqual(library.source_file(entry.name).read_bytes(), source.encode())
        self.assertEqual(library.audio_file(entry.name).read_bytes(), COMPLETE_AUDIO)
        self.assertEqual([event[2] for event in self.audit], ["saved"])

    def test_retry_after_a_failed_sidecar_write_creates_one_complete_library_entry(self):
        self.write_record("123456abcdefgh", source="# Exact source", status="done", audio=COMPLETE_AUDIO)
        jobs = self.service()
        jobs.restore()
        original_write = Path.write_text

        def simulate_sidecar_failure(path, *args, **kwargs):
            if path.name == "fixture.md":
                raise OSError("simulated Library write failure")
            return original_write(path, *args, **kwargs)

        with patch.object(Path, "write_text", simulate_sidecar_failure):
            with self.assertRaisesRegex(OSError, "simulated Library write failure"):
                jobs.save("123456abcdefgh")
        library = Library(self.library_dir, OWNER)
        self.assertEqual(library.entries(), [])
        name = jobs.save("123456abcdefgh")
        self.assertEqual([entry.name for entry in library.entries()], [name])
        self.assertEqual(library.source_file(name).read_text(), "# Exact source")

    def test_failed_checkpoint_still_records_outcome_and_notifies(self):
        entered, release, outcome = Event(), Event(), Event()
        notifications = []

        def synthesize(text, voice):
            entered.set()
            if not release.wait(5):
                raise TimeoutError("test did not release synthesis")
            return self.audio(text, voice)

        def notify(job, succeeded):
            notifications.append((job["id"], succeeded))
            outcome.set()

        jobs = self.service(synthesize, notify=notify)
        job_id = jobs.submit(OWNER, SOURCE, "local", "Fixture", notify=True)
        self.assertTrue(entered.wait(5))
        with patch("os.replace", side_effect=OSError("checkpoint unavailable")), \
             patch("threading.excepthook", side_effect=lambda args: outcome.set()):
            release.set()
            self.assertTrue(outcome.wait(5))
            self.assertEqual([event[2] for event in self.audit], ["queued", "error"])
            self.assertEqual(notifications, [(job_id, False)])
            self.assertEqual(jobs.snapshot(job_id)["error"], "checkpoint unavailable")
