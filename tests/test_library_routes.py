from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from threading import Event
import time
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
OWNER = "reader@example.com"
OTHER = "other@example.com"
AUDIO = b"\xff\xfb\x90\x00" + b"\x00" * 15996  # one second at 128 kbps


class LibraryRoutesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ("app.py", "library_store.py", "narration_jobs.py"):
            shutil.copy2(ROOT / name, self.root / name)
        env = patch.dict(os.environ, {"LECTOR_RESUME": "0", "LECTOR_TTS_BACKEND": "kokoro",
                                      "LECTOR_OPENAI_ALLOWED": "someone-else@example.com",
                                      "SMTP_HOST": "", "SMTP_PASS": ""})
        env.start()
        self.addCleanup(env.stop)
        self.import_count = 0
        self.module = self.load_application()
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as session:
            session.update(user=OWNER, csrf="test-csrf")
        tokens = {hashlib.sha256(token.encode()).hexdigest(): {"email": owner}
                  for token, owner in (("reader-token", OWNER), ("other-token", OTHER))}
        (self.root / "state" / "api_tokens.json").write_text(json.dumps(tokens))
        self.auth = {"Authorization": "Bearer reader-token"}

    def load_application(self, resume=False):
        self.import_count += 1
        module_name = f"sotto_test_{self.root.name}_{self.import_count}"
        spec = importlib.util.spec_from_file_location(module_name, self.root / "app.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        self.addCleanup(sys.modules.pop, module_name, None)
        with patch.dict(os.environ, {"LECTOR_RESUME": "1" if resume else "0"}):
            spec.loader.exec_module(module)
        module.app.config.update(TESTING=True, USE_X_SENDFILE=False)
        return module

    def restarted_client(self):
        # These jobs are all done; service startup reloads them without workers.
        client = self.load_application(resume=True).app.test_client()
        with client.session_transaction() as session:
            session.update(user=OWNER, csrf="test-csrf")
        return client

    def post(self, path, **data):
        return self.client.post(path, data={"_csrf": "test-csrf", **data})

    def entries(self, auth=None):
        response = self.client.get("/api/v1/library", headers=auth or self.auth)
        self.assertEqual(response.status_code, 200)
        return response.json["entries"]

    def upload(self, name="entry.mp3", *, audio=AUDIO, source=None, meta=None, headers=None, client=None):
        data = {"audio": (io.BytesIO(audio), name)}
        if source is not None:
            data["text"] = (io.BytesIO(source.encode()), "source.md")
        if meta is not None:
            data["meta"] = meta if isinstance(meta, str) else json.dumps(meta)
        return (client or self.client).put(f"/api/v1/library/{name}", data=data, headers=headers or self.auth)

    def web_as(self, owner):
        with self.client.session_transaction() as session:
            session.update(user=owner, csrf="test-csrf")

    def share_url(self, name="entry.mp3", include_text=True):
        response = self.post(f"/library/{name}/share", **({"text": "1"} if include_text else {}))
        self.assertEqual(response.status_code, 302)
        page = self.client.get("/library").get_data(as_text=True)
        return "/share/" + re.search(r"/share/([A-Za-z0-9_-]+)", page).group(1)

    def audit(self):
        return [json.loads(line) for line in (self.root / "lector.log").read_text().splitlines()]

    def finished_job(self, job_id="abcdef123456", source="# Exact source"):
        jobs = self.root / "jobs"
        audio = jobs / (job_id + ".mp3")
        audio.write_bytes(AUDIO)
        job = {"status": "done", "title": "Original title", "owner": OWNER,
               "file": str(audio), "secs": 20, "words": 100, "voice": "am_michael"}
        (jobs / (job_id + ".json")).write_text(json.dumps(job))
        if source is not None:
            (jobs / (job_id + ".md.src")).write_bytes(source.encode())
        self.client = self.restarted_client()
        return job_id

    def wait_for_job(self, job_id, predicate):
        deadline = time.monotonic() + 5
        while True:
            response = self.client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
            self.assertEqual(response.status_code, 200)
            if predicate(response.json):
                return response.json
            if response.json["status"] == "error" or time.monotonic() >= deadline:
                self.fail(f"Job did not reach the expected state: {response.json}")
            time.sleep(0.005)

    def test_web_job_saved_after_restart_retains_submitted_markdown(self):
        source = "# Exact source\n\nA **marked-up** café."
        with patch.object(self.module, "tts_kokoro", return_value=AUDIO):
            response = self.post("/convert", md=source, voice="am_michael")
            self.assertEqual(response.status_code, 302)
            job_id = response.location.rsplit("/", 1)[1]
            self.wait_for_job(job_id, lambda job: job["status"] == "done")

        client = self.restarted_client()
        self.assertIn(source, client.get(f"/job/{job_id}").get_data(as_text=True))
        self.assertEqual(client.post(f"/job/{job_id}/save", data={"_csrf": "test-csrf"}).location, "/library")
        entry, = client.get("/api/v1/library", headers=self.auth).json["entries"]
        with client.get(f"/api/v1/library/{entry['name']}/text", headers=self.auth) as response:
            self.assertEqual((entry["has_text"], response.status_code), (True, 200))
            self.assertEqual(response.data, source.encode())

    def test_completed_legacy_job_without_source_can_still_save_audio(self):
        job_id = self.finished_job(source=None)
        self.assertEqual(self.post(f"/job/{job_id}/save").location, "/library")
        entry, = self.entries()
        self.assertFalse(entry["has_text"])
        with self.client.get(f"/api/v1/library/{entry['name']}/audio", headers=self.auth) as response:
            self.assertEqual(response.data, AUDIO)

    def test_web_upload_and_token_submission_share_live_progress_and_audio_preview(self):
        users = self.root / "state" / "users.json"
        users.write_text(json.dumps({OWNER: {}, OTHER: {"admin": True}}))
        source = "# In-progress fixture\n\n" + "one " * 150 + "first.\n\n" + "two " * 150 + "second."
        for caller in ("web", "token"):
            with self.subTest(caller=caller):
                second_chunk = Event()
                release = Event()

                def synthesize(text, voice):
                    if "second." in text:
                        second_chunk.set()
                        if not release.wait(5):
                            raise TimeoutError("test did not release synthesis")
                    return AUDIO

                title = f"Live {caller} narration"
                with patch.object(self.module, "tts_kokoro", side_effect=synthesize) as synth:
                    if caller == "web":
                        response = self.post("/convert", md="overridden", voice="onyx", title=title,
                                             file=(io.BytesIO(source.encode()), "source.md"))
                        self.assertEqual(response.status_code, 302)
                        job_id = response.location.rsplit("/", 1)[1]
                        expected_voice = "af_heart"
                    else:
                        response = self.client.post("/api/v1/narrate", headers=self.auth,
                                                    json={"text": source, "voice": "am_michael", "title": title})
                        self.assertEqual(response.status_code, 202)
                        job_id = response.json["job_id"]
                        expected_voice = "am_michael"
                        self.assertEqual(response.json, {"job_id": job_id, "status": "queued",
                                                         "voice": expected_voice, "backend": "kokoro"})
                    try:
                        self.assertTrue(second_chunk.wait(5))
                        self.assertEqual(json.loads(users.read_text())[OWNER]["last_voice"], expected_voice)
                        self.assertEqual(synth.call_args.args[1], expected_voice)
                        path = f"/job/{job_id}"
                        status = self.client.get(path + "/status").json
                        self.assertRegex(status.pop("elapsed"), r"^\d+s$")
                        self.assertEqual(status, {"status": "running", "done": 1, "total": 2,
                                                  "words": 304, "pct": 50})
                        token_status = self.client.get(f"/api/v1/jobs/{job_id}", headers=self.auth).json
                        self.assertEqual(token_status, {"status": "running", "done": 1, "total": 2,
                                                        "words": 304, "pct": 50, "error": None, "name": None})
                        self.assertIn("# In-progress fixture", self.client.get(path).get_data(as_text=True))
                        self.assertIn(path, self.client.get("/library").get_data(as_text=True))
                        with self.client.get(path + "/audio", headers={"Range": "bytes=0-3"}) as preview:
                            self.assertEqual((preview.status_code, preview.data), (206, AUDIO[:4]))
                        self.assertEqual(self.post(path + "/save").status_code, 404)

                        self.web_as(OTHER)
                        self.assertEqual(self.client.get(path).status_code, 200)
                        self.assertNotIn(path, self.client.get("/library").get_data(as_text=True))
                        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}",
                                                         headers={"Authorization": "Bearer other-token"}).status_code, 404)
                    finally:
                        self.web_as(OWNER)
                        release.set()
                        result = self.wait_for_job(job_id, lambda job: job["status"] == "done"
                                                   and (caller == "web" or job["name"]))
                expected_name = "live-token-narration.mp3" if caller == "token" else None
                self.assertEqual(result["name"], expected_name)

    def test_narration_request_validation_stays_specific_to_each_caller(self):
        token_cases = (({}, 400, "validation"),
                       ({"text": "text", "voice": "onyx"}, 403, "voice"),
                       ({"text": "é" * 204801}, 413, "too-large"))
        for payload, code, error in token_cases:
            with self.subTest(code=code):
                response = self.client.post("/api/v1/narrate", headers=self.auth, json=payload)
                self.assertEqual((response.status_code, response.json["error"]), (code, error))
        self.assertEqual(self.post("/convert", md="  ").location, "/")
        self.assertEqual(self.post("/convert", md="é" * 204801).status_code, 413)

    def test_token_poll_reports_autosave_failure_and_completed_audio_can_be_saved(self):
        blocked_source = self.root / "library" / OWNER / "fixture.md"
        blocked_source.mkdir(parents=True)
        source = "# Fixture\n\nSource is kept on retry."
        with patch.object(self.module, "tts_kokoro", return_value=AUDIO):
            response = self.client.post("/api/v1/narrate", headers=self.auth,
                                        json={"text": source, "voice": "am_michael"})
            self.assertEqual(response.status_code, 202)
            job_id = response.json["job_id"]
            status = self.wait_for_job(job_id, lambda job: job["error"] or job["name"])
        self.assertEqual((status["status"], status["name"]), ("error", None))
        self.assertTrue(status["error"])
        self.assertEqual(self.entries(), [])
        with self.client.get(f"/job/{job_id}/audio") as response:
            self.assertEqual((response.status_code, response.data), (200, AUDIO))

        blocked_source.rmdir()
        self.assertEqual(self.post(f"/job/{job_id}/save").location, "/library")
        status = self.client.get(f"/api/v1/jobs/{job_id}", headers=self.auth).json
        self.assertEqual((status["status"], status["name"], status["error"]), ("done", "fixture.mp3", None))
        entry, = self.entries()
        self.assertEqual((entry["name"], entry["has_text"]), ("fixture.mp3", True))

    def test_saved_job_rename_advances_sync_revision(self):
        job_id = self.finished_job()
        self.assertEqual(self.post(f"/job/{job_id}/save").status_code, 302)
        name = self.entries()[0]["name"]
        audio = self.root / "library" / OWNER / name
        os.utime(audio, (1000000000, 1000000000))
        response = self.post(f"/job/{job_id}/rename", title=" Renamed title ")
        self.assertEqual(response.location, f"/job/{job_id}")
        entry, = self.entries()
        self.assertEqual(entry["title"], "Renamed title")
        self.assertEqual(entry["name"], name)
        self.assertGreater(entry["mtime"], 1000000000)
        with self.client.get(f"/api/v1/library/{name}/audio", headers=self.auth) as response:
            self.assertEqual(response.data, AUDIO)

    def test_upload_is_visible_on_web_and_preserves_json_and_audit_contracts(self):
        response = self.upload(source="# Exact source", meta={"title": "Uploaded title", "words": 100,
                                                              "secs": 26, "voice": "am_michael"})
        self.assertEqual((response.status_code, response.json), (201, {"name": "entry.mp3"}))
        entry, = self.entries()
        self.assertEqual(set(entry), {"name", "title", "words", "secs", "voice", "size",
                                     "duration_secs", "mtime", "has_text"})
        self.assertEqual({key: entry[key] for key in entry if key != "mtime"},
                         {"name": "entry.mp3", "title": "Uploaded title", "words": 100, "secs": 26,
                          "voice": "am_michael", "size": 16000, "duration_secs": 1, "has_text": True})
        for path in ("/library", "/library/entry.mp3/view"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn("Uploaded title", response.get_data(as_text=True))
            self.assertIn("# Exact source", response.get_data(as_text=True))
        event, = self.audit()
        self.assertEqual((event["user"], event["title"], event["status"], event["detail"]),
                         (OWNER, "Uploaded title", "api-upload", "entry.mp3 16000B created"))

    def test_web_and_token_renames_advance_revision_keep_audio_and_trim_titles(self):
        self.upload()
        for mode in ("web", "token"):
            with self.subTest(mode=mode):
                os.utime(self.root / "library" / OWNER / "entry.mp3", (1000000000, 1000000000))
                title = "  " + mode * 60 + "  "
                if mode == "web":
                    response = self.post("/library/entry.mp3/rename", title=title, back="view")
                    self.assertEqual(response.location, "/library/entry.mp3/view")
                else:
                    response = self.client.patch("/api/v1/library/entry.mp3", json={"title": title},
                                                 headers=self.auth)
                    self.assertEqual((response.status_code, response.json),
                                     (200, {"name": "entry.mp3", "title": (mode * 60)[:120]}))
                entry, = self.entries()
                self.assertEqual(entry["title"], (mode * 60)[:120])
                self.assertEqual(entry["name"], "entry.mp3")
                self.assertGreater(entry["mtime"], 1000000000)
                with self.client.get("/api/v1/library/entry.mp3/audio", headers=self.auth) as response:
                    self.assertEqual(response.data, AUDIO)
        self.assertEqual([event["status"] for event in self.audit()], ["api-upload", "rename", "api-rename"])

    def test_blank_title_policies_and_missing_entry_validation_order_stay_distinct(self):
        job_id = self.finished_job()
        self.post(f"/job/{job_id}/save")
        name = self.entries()[0]["name"]
        audio = self.root / "library" / OWNER / name
        os.utime(audio, (1000000000, 1000000000))
        self.assertEqual(self.post(f"/job/{job_id}/rename", title="  ").status_code, 302)
        self.assertEqual(self.entries()[0]["title"], "Original title")
        self.assertEqual(self.entries()[0]["mtime"], 1000000000)
        response = self.client.patch(f"/api/v1/library/{name}", json={"title": " "}, headers=self.auth)
        self.assertEqual((response.status_code, response.json),
                         (400, {"error": "validation", "detail": "title required"}))
        self.assertEqual(self.entries()[0]["mtime"], 1000000000)
        response = self.post(f"/library/{name}/rename", title="  ")
        self.assertEqual(response.location, "/library#" + name)
        self.assertEqual(self.entries()[0]["title"], "Original title")
        self.assertGreater(self.entries()[0]["mtime"], 1000000000)
        self.assertEqual(self.client.patch("/api/v1/library/missing.mp3", json={"title": ""},
                                          headers=self.auth).status_code, 404)
        self.assertEqual(self.post("/library/missing.mp3/rename", title="").status_code, 404)

    def test_deleted_saved_job_rename_keeps_job_without_recreating_entry(self):
        job_id = self.finished_job()
        self.post(f"/job/{job_id}/save")
        name = self.entries()[0]["name"]
        self.assertEqual(self.client.delete(f"/api/v1/library/{name}", headers=self.auth).status_code, 204)
        self.assertEqual(self.post(f"/job/{job_id}/rename", title="Job only").status_code, 302)
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.client.get(f"/library/{name}/view").status_code, 404)
        client = self.restarted_client()
        self.assertIn("Job only", client.get(f"/job/{job_id}").get_data(as_text=True))
        self.assertEqual(client.get("/api/v1/library", headers=self.auth).json, {"entries": []})

    def test_token_patch_returns_missing_when_delete_wins_after_preflight(self):
        self.assertEqual(self.upload(source="Original source").status_code, 201)
        path = "/api/v1/library/entry.mp3"
        request_class = self.module.app.request_class
        get_json = request_class.get_json

        def delete_during_patch(request, *args, **kwargs):
            data = get_json(request, *args, **kwargs)
            deleted = self.module.app.test_client().delete(path, headers=self.auth)
            self.assertEqual(deleted.status_code, 204)
            return data

        with patch.object(request_class, "get_json", delete_during_patch):
            response = self.client.patch(path, json={"title": "Too late"}, headers=self.auth)
        self.assertEqual((response.status_code, response.json),
                         (404, {"error": "not-found", "detail": "no such entry"}))
        self.assertEqual(self.entries(), [])
        self.assertEqual([event["status"] for event in self.audit()], ["api-upload", "api-delete"])

    def test_numeric_collision_name_can_be_downloaded_by_sync_client(self):
        title = "a" * 52
        job_id = self.finished_job()
        occupied = {f"{title}.mp3", f"{title}-{job_id[:6]}.mp3"}
        for name in occupied:
            self.assertEqual(self.upload(name).status_code, 201)
        self.assertEqual(self.post(f"/job/{job_id}/rename", title=title).status_code, 302)
        self.assertEqual(self.post(f"/job/{job_id}/save").location, "/library")
        name, = {entry["name"] for entry in self.entries()} - occupied
        with self.client.get(f"/api/v1/library/{name}/audio", headers=self.auth) as response:
            self.assertEqual((response.status_code, response.data), (200, AUDIO))

    def test_repeated_manual_save_keeps_marker_and_persistence(self):
        job_id = self.finished_job()
        for _ in range(2):
            self.assertEqual(self.post(f"/job/{job_id}/save").location, "/library")
        entry, = self.entries()
        self.assertEqual(entry["name"], "original-title.mp3")
        self.assertEqual([event["status"] for event in self.audit()], ["saved"])
        client = self.restarted_client()
        response = client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
        self.assertEqual(response.json["name"], entry["name"])

    def test_job_ownership_and_admin_rename_bind_storage_to_job_owner(self):
        job_id = self.finished_job()
        self.post(f"/job/{job_id}/save")
        self.web_as(OTHER)
        self.assertEqual(self.post(f"/job/{job_id}/rename", title="Not mine").status_code, 404)
        self.assertEqual(self.post(f"/job/{job_id}/save").status_code, 404)
        self.assertEqual(self.client.get(f"/api/v1/jobs/{job_id}",
                                         headers={"Authorization": "Bearer other-token"}).status_code, 404)
        (self.root / "state" / "users.json").write_text(json.dumps({OTHER: {"admin": True}}))
        self.assertEqual(self.post(f"/job/{job_id}/rename", title="Admin rename").status_code, 302)
        self.assertEqual(self.entries()[0]["title"], "Admin rename")
        self.assertEqual(self.entries({"Authorization": "Bearer other-token"}), [])

    def test_completion_autosave_and_notification_save_use_same_library(self):
        # Markdown fences clean to empty text, so real workers finish without TTS.
        for flag in ("autosave", "notify"):
            with self.subTest(flag=flag):
                if flag == "autosave":
                    response = self.client.post("/api/v1/narrate", headers=self.auth,
                                                json={"text": "```", "title": flag, "voice": "am_michael"})
                    self.assertEqual(response.status_code, 202)
                    job_id = response.json["job_id"]
                else:
                    response = self.post("/convert", md="```", title=flag, voice="am_michael", notify="1")
                    self.assertEqual(response.status_code, 302)
                    job_id = response.location.rsplit("/", 1)[1]
                deadline = time.monotonic() + 5
                while True:
                    response = self.client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
                    if response.json["name"] or response.json["status"] == "error" or time.monotonic() > deadline:
                        break
                    time.sleep(0.005)
                self.assertEqual(response.json["status"], "done")
                self.assertEqual(response.json["name"], flag + ".mp3")
                self.assertEqual({entry["name"] for entry in self.entries()},
                                 {"autosave.mp3"} if flag == "autosave" else {"autosave.mp3", "notify.mp3"})
                # A fresh HTTP client after service startup observes persisted state.
                client = self.restarted_client()
                restored = client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
                while (restored.json.get("name") != response.json["name"] or
                       (flag == "notify" and self.audit()[-1]["status"] != "email-unconfigured")) and time.monotonic() < deadline:
                    time.sleep(0.005)
                    client = self.restarted_client()
                    restored = client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
                self.assertEqual(restored.json["name"], response.json["name"])
        self.assertEqual([event["status"] for event in self.audit()],
                         ["api-narrate", "done", "saved", "queued", "done", "saved", "email-unconfigured"])

    def test_upload_replacement_conflict_defaults_and_omitted_source(self):
        self.upload(source="kept source", meta={"title": "Initial"})
        response = self.upload(audio=b"conflict", headers={**self.auth, "If-None-Match": "*"})
        self.assertEqual((response.status_code, response.json),
                         (409, {"error": "conflict", "detail": "entry exists"}))
        with self.client.get("/api/v1/library/entry.mp3/audio", headers=self.auth) as response:
            self.assertEqual(response.data, AUDIO)
        response = self.upload(audio=b"replacement", meta="{broken")
        self.assertEqual((response.status_code, response.json), (200, {"name": "entry.mp3"}))
        entry, = self.entries()
        self.assertEqual(entry["title"], "entry")
        self.assertTrue(entry["has_text"])
        with self.client.get("/api/v1/library/entry.mp3/text", headers=self.auth) as response:
            self.assertEqual(response.data, b"kept source")
        self.assertEqual(self.audit()[-1]["detail"], "entry.mp3 11B replaced")

    def test_concurrent_conditional_uploads_return_201_and_409_with_complete_winner(self):
        copying, release = Event(), Event()
        copy_stream = shutil.copyfileobj
        conditional = {**self.auth, "If-None-Match": "*"}

        def pause_first_audio(src, dst, *args, **kwargs):
            if not copying.is_set() and Path(dst.name).name in {"entry.mp3", "entry.mp3.tmp"}:
                copying.set()
                if not release.wait(5):
                    raise TimeoutError("test did not release upload copy")
            return copy_stream(src, dst, *args, **kwargs)

        with patch.object(shutil, "copyfileobj", pause_first_audio), ThreadPoolExecutor(2) as pool:
            first = pool.submit(self.upload, audio=b"First audio", source="First source",
                                meta={"title": "First", "words": 10}, headers=conditional,
                                client=self.module.app.test_client())
            try:
                self.assertTrue(copying.wait(5))
                second = pool.submit(self.upload, audio=b"Second audio", source="Second source",
                                     meta={"title": "Second", "words": 20}, headers=conditional,
                                     client=self.module.app.test_client()).result(timeout=5)
                self.assertEqual((second.status_code, second.json), (201, {"name": "entry.mp3"}))
            finally:
                release.set()
            conflict = first.result(timeout=5)

        self.assertEqual((conflict.status_code, conflict.json),
                         (409, {"error": "conflict", "detail": "entry exists"}))
        entry, = self.entries()
        self.assertEqual((entry["title"], entry["words"], entry["size"]), ("Second", 20, 12))
        for suffix, content in (("audio", b"Second audio"), ("text", b"Second source")):
            with self.client.get(f"/api/v1/library/entry.mp3/{suffix}", headers=self.auth) as response:
                self.assertEqual((response.status_code, response.data), (200, content))
        self.assertEqual([event["status"] for event in self.audit()], ["api-upload"])

    def test_token_validation_auth_and_legacy_web_names_are_preserved(self):
        self.assertEqual(self.client.get("/api/v1/library").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/library", headers={"Authorization": "Bearer bad"}).status_code, 401)
        for name in ("Legacy_Name.mp3", "a" * 61 + ".mp3", "bad.wav"):
            response = self.upload(name)
            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.json["error"], "validation")
        response = self.client.put("/api/v1/library/valid.mp3", headers=self.auth)
        self.assertEqual(response.json, {"error": "validation", "detail": "multipart part 'audio' required"})
        for name in ("Legacy_Name.mp3", ".hidden.m4a", "name.with.dots.aac"):
            owner_dir = self.root / "library" / OWNER
            owner_dir.mkdir(exist_ok=True)
            (owner_dir / name).write_bytes(AUDIO)
            self.assertEqual(self.client.get(f"/library/{name}/view").status_code, 200)
            self.assertEqual(self.client.get(f"/api/v1/library/{name}/audio", headers=self.auth).status_code, 404)
        self.assertEqual(len(self.entries()), 3)

    def test_web_order_is_newest_first_and_token_order_is_filename_order(self):
        self.upload("a.mp3", meta={"title": "Older entry"})
        self.upload("z.mp3", meta={"title": "Newer entry"})
        for name, timestamp in (("a.mp3", 1000000000), ("z.mp3", 1000000010)):
            os.utime(self.root / "library" / OWNER / name, (timestamp, timestamp))
        self.assertEqual([entry["name"] for entry in self.entries()], ["a.mp3", "z.mp3"])
        page = self.client.get("/library").get_data(as_text=True)
        self.assertLess(page.index("Newer entry"), page.index("Older entry"))

    def test_share_capabilities_owner_isolation_and_delete_revocation(self):
        self.upload(source="owner source", meta={"title": "Owner entry"})
        url = self.share_url(include_text=False)
        self.assertEqual(self.client.get(url + "/text").status_code, 404)
        self.assertNotIn("owner source", self.client.get(url).get_data(as_text=True))
        self.assertEqual(self.share_url(include_text=True), url)
        self.assertIn("owner source", self.client.get(url).get_data(as_text=True))
        self.assertEqual(self.client.get("/share/unknown").status_code, 404)
        other_auth = {"Authorization": "Bearer other-token"}
        self.assertEqual(self.entries(other_auth), [])
        self.assertEqual(self.client.delete("/api/v1/library/entry.mp3", headers=other_auth).status_code, 404)
        self.upload(source="other source", meta={"title": "Other entry"}, headers=other_auth)
        self.web_as(OTHER)
        other_url = self.share_url()
        self.assertNotEqual(other_url, url)
        self.web_as(OWNER)
        response = self.client.delete("/api/v1/library/entry.mp3", headers=self.auth)
        self.assertEqual((response.status_code, response.data), (204, b""))
        self.assertEqual(self.audit()[-1]["detail"], "shares-revoked=1")
        for suffix in ("", "/audio", "/text"):
            self.assertEqual(self.client.get(url + suffix).status_code, 404)
        self.assertIn("other source", self.client.get(other_url).get_data(as_text=True))
        self.assertEqual(self.entries(other_auth)[0]["title"], "Other entry")
        self.assertEqual(self.entries(), [])

    def test_unshare_audit_redirect_and_source_absence(self):
        self.upload()
        url = self.share_url()
        self.assertEqual(self.audit()[-1]["detail"], "audio-only")
        response = self.post("/library/entry.mp3/unshare", back="view")
        self.assertEqual(response.location, "/library/entry.mp3/view")
        self.assertEqual(self.audit()[-1]["status"], "share-revoke")
        self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.get("/api/v1/library/entry.mp3/text", headers=self.auth).status_code, 404)

    def test_download_mime_ranges_xsendfile_and_standalone_source(self):
        for ext, mime in (("mp3", "audio/mpeg"), ("m4a", "audio/mp4"), ("aac", "audio/aac")):
            name = "entry." + ext
            self.upload(name, source="source", meta={"duration_secs": 42})
            url = self.share_url(name)
            for path, headers in ((f"/api/v1/library/{name}/audio", self.auth),
                                  (f"/library/{name}", {}), (url + "/audio", {})):
                with self.client.get(path, headers={**headers, "Range": "bytes=0-3"}) as response:
                    self.assertEqual(response.status_code, 206)
                    self.assertEqual(response.mimetype, mime)
                    self.assertEqual(response.data, AUDIO[:4])
                    self.assertEqual(response.headers["Content-Range"], "bytes 0-3/16000")
                self.module.app.config["USE_X_SENDFILE"] = True
                with self.client.get(path, headers={**headers, "Range": "bytes=0-3"}) as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["X-Sendfile"], str(self.root / "library" / OWNER / name))
                self.module.app.config["USE_X_SENDFILE"] = False
            for path, headers in ((f"/api/v1/library/{name}/text", self.auth),
                                  ("/library/entry.md", {}), (url + "/text", {})):
                with self.client.get(path, headers=headers) as response:
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.mimetype, "text/markdown")
                    self.assertEqual(response.data, b"source")
        (self.root / "library" / OWNER / "standalone.md").write_text("standalone")
        with self.client.get("/library/standalone.md") as response:
            self.assertEqual(response.data, b"standalone")

    def test_calibration_keeps_orphan_records_backend_medians_and_defaults(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("RK=0.26,RO=0.06,", response.get_data(as_text=True))
        owner_dir = self.root / "library" / OWNER
        records = [{"secs": 20, "words": 100, "voice": "am_michael"},
                   {"secs": 40, "words": 100, "voice": "af_heart"},
                   {"secs": 10, "words": 100, "voice": "onyx"},
                   {"secs": 999, "words": 49, "voice": "onyx"}]
        for index, record in enumerate(records):
            (owner_dir / f"orphan-{index}.meta").write_text(json.dumps(record))
        (owner_dir / "broken.meta").write_text("{broken")
        page = self.client.get("/").get_data(as_text=True)
        self.assertIn("RK=0.3,RO=0.1,", page)
        self.web_as(OTHER)
        self.assertIn("RK=0.26,RO=0.06,", self.client.get("/").get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
