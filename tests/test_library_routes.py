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
        for name in ("app.py", "library_store.py"):
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, self.root / name)
        env = patch.dict(os.environ, {"LECTOR_RESUME": "0", "SMTP_HOST": "", "SMTP_PASS": ""})
        env.start()
        self.addCleanup(env.stop)
        module_name = "sotto_test_" + self.root.name
        spec = importlib.util.spec_from_file_location(module_name, self.root / "app.py")
        self.module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = self.module
        self.addCleanup(sys.modules.pop, module_name, None)
        spec.loader.exec_module(self.module)
        self.module.app.config.update(TESTING=True, USE_X_SENDFILE=False)
        self.client = self.module.app.test_client()
        with self.client.session_transaction() as session:
            session.update(user=OWNER, csrf="test-csrf")
        tokens = {hashlib.sha256(token.encode()).hexdigest(): {"email": owner}
                  for token, owner in (("reader-token", OWNER), ("other-token", OTHER))}
        (self.root / "state" / "api_tokens.json").write_text(json.dumps(tokens))
        self.auth = {"Authorization": "Bearer reader-token"}

    def post(self, path, **data):
        return self.client.post(path, data={"_csrf": "test-csrf", **data})

    def entries(self, auth=None):
        response = self.client.get("/api/v1/library", headers=auth or self.auth)
        self.assertEqual(response.status_code, 200)
        return response.json["entries"]

    def upload(self, name="entry.mp3", *, audio=AUDIO, source=None, meta=None, headers=None):
        data = {"audio": (io.BytesIO(audio), name)}
        if source is not None:
            data["text"] = (io.BytesIO(source.encode()), "source.md")
        if meta is not None:
            data["meta"] = meta if isinstance(meta, str) else json.dumps(meta)
        return self.client.put(f"/api/v1/library/{name}", data=data, headers=headers or self.auth)

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

    def finished_job(self, job_id="abcdef123456", **fields):
        audio = self.root / "jobs" / (job_id + ".mp3")
        audio.write_bytes(AUDIO)
        job = {"status": "done", "title": "Original title", "owner": OWNER,
               "file": str(audio), "md": "# Exact source", "secs": 20,
               "words": 100, "voice": "am_michael", **fields}
        self.module.JOBS[job_id] = job
        return job_id, job

    def test_saved_job_rename_advances_sync_revision(self):
        job_id, job = self.finished_job()
        self.assertEqual(self.post(f"/job/{job_id}/save").status_code, 302)
        name = job["saved"]
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
        job_id, job = self.finished_job()
        self.post(f"/job/{job_id}/save")
        name = job["saved"]
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
        job_id, job = self.finished_job()
        self.post(f"/job/{job_id}/save")
        name = job["saved"]
        self.assertEqual(self.client.delete(f"/api/v1/library/{name}", headers=self.auth).status_code, 204)
        self.assertEqual(self.post(f"/job/{job_id}/rename", title="Job only").status_code, 302)
        self.assertEqual(self.entries(), [])
        self.assertEqual(self.client.get(f"/library/{name}/view").status_code, 404)
        self.assertEqual(json.loads((self.root / "jobs" / (job_id + ".json")).read_text())["title"], "Job only")
        self.assertEqual(list((self.root / "library" / OWNER).iterdir()), [])

    def test_repeated_manual_save_keeps_marker_and_persistence(self):
        job_id, job = self.finished_job()
        for _ in range(2):
            self.assertEqual(self.post(f"/job/{job_id}/save").location, "/library")
        entry, = self.entries()
        self.assertEqual(entry["name"], "original-title.mp3")
        self.assertEqual(job["saved"], entry["name"])
        persisted = json.loads((self.root / "jobs" / (job_id + ".json")).read_text())
        self.assertEqual(persisted["saved"], entry["name"])
        self.assertEqual([event["status"] for event in self.audit()], ["saved"])
        response = self.client.get(f"/api/v1/jobs/{job_id}", headers=self.auth)
        self.assertEqual(response.json["name"], entry["name"])

    def test_job_ownership_and_admin_rename_bind_storage_to_job_owner(self):
        job_id, job = self.finished_job()
        self.post(f"/job/{job_id}/save")
        name = job["saved"]
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
                persisted = json.loads((self.root / "jobs" / (job_id + ".json")).read_text())
                # Wait for persistence and the notification audit after the save marker.
                while ("saved" not in persisted or (flag == "notify" and self.audit()[-1]["status"] != "email-unconfigured")) and time.monotonic() < deadline:
                    time.sleep(0.005)
                    persisted = json.loads((self.root / "jobs" / (job_id + ".json")).read_text())
                self.assertEqual(persisted["saved"], response.json["name"])
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
