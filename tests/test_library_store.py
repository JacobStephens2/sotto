from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from threading import Event
import unittest
from unittest.mock import patch

from library_store import Library


OWNER = "reader@example.com"
AUDIO = b"\xff\xfb\x90\x00" + b"\x00" * 15996


class LibraryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Library(self.root, OWNER)

    def legacy(self, name, *, audio=AUDIO, title=None, source=None, meta=None):
        path = self.root / OWNER / name
        path.write_bytes(audio)
        if title is not None:
            path.with_suffix(".title").write_text(title, encoding="utf-8")
        if source is not None:
            path.with_suffix(".md").write_text(source, encoding="utf-8")
        if meta is not None:
            path.with_suffix(".meta").write_text(json.dumps(meta))
        return path

    def test_legacy_formats_resolve_titles_provenance_duration_and_source(self):
        self.legacy("Old_Record.mp3", title="  Exact Display Title \n", source="# Source",
                    meta={"words": 100, "secs": 26, "voice": "am_michael", "duration_secs": 999})
        self.legacy("other-file.m4a", meta={"duration_secs": 42})
        self.legacy("third.aac", meta={"duration_secs": 7})
        entries = {entry.name: entry for entry in self.library.entries()}
        self.assertEqual(set(entries), {"Old_Record.mp3", "other-file.m4a", "third.aac"})
        entry = self.library.lookup("Old_Record.mp3")
        self.assertEqual(entry.title, "Exact Display Title")
        self.assertEqual(entry.size, 16000)
        self.assertEqual(entry.duration_secs, 1)
        self.assertEqual(entry.metadata, {"words": 100, "secs": 26, "voice": "am_michael", "duration_secs": 999})
        self.assertTrue(entry.has_text)
        self.assertEqual(entry.source_name, "Old_Record.md")
        self.assertEqual(self.library.read_source(entry.name), "# Source")
        self.assertEqual(entries["other-file.m4a"].title, "Other file")
        self.assertEqual(entries["other-file.m4a"].duration_secs, 42)
        self.assertEqual(entries["third.aac"].duration_secs, 7)
        self.assertFalse(entries["third.aac"].has_text)
        self.assertIsNone(self.library.lookup("missing.mp3"))

    def test_saved_narration_keeps_exact_title_source_and_collision_naming(self):
        completed = self.root / "completed.mp3"
        completed.write_bytes(AUDIO)
        args = dict(title="An Exact Title!", source="# Exact source",
                    metadata={"secs": 26, "words": 100, "voice": "am_michael"},
                    job_id="abcdef123456")
        name = self.library.save_narration(completed, **args)
        self.assertEqual(name, "an-exact-title.mp3")
        self.assertEqual(self.library.lookup(name).title, "An Exact Title!")
        self.assertEqual(self.library.lookup(name).metadata, args["metadata"])
        self.assertEqual(self.library.read_source(name), "# Exact source")
        self.assertEqual(self.library.audio_file(name).read_bytes(), AUDIO)
        self.assertEqual(self.library.save_narration(completed, **args), "an-exact-title-abcdef.mp3")
        self.assertEqual(self.library.save_narration(completed, **args), "an-exact-title-abcdef-2.mp3")
        self.assertEqual(self.library.save_narration(completed, title="?!", source="", metadata={},
                                                    job_id="123456"), "narration.mp3")

    def test_conditional_upload_can_claim_name_while_narration_is_staging(self):
        completed = self.root / "completed.mp3"
        completed.write_bytes(AUDIO)
        os.utime(completed, (1000000000, 1000000000))
        uploader = Library(self.root, OWNER)
        copying, release = Event(), Event()
        copy2 = shutil.copy2
        provenance = {"secs": 26, "words": 100, "voice": "am_michael"}

        def pause_copy(src, dst, **kwargs):
            if src == completed:
                copying.set()
                if not release.wait(5):
                    raise TimeoutError("test did not release narration copy")
            return copy2(src, dst, **kwargs)

        with patch.object(shutil, "copy2", pause_copy), ThreadPoolExecutor(2) as pool:
            saved = pool.submit(self.library.save_narration, completed, title="Fixture",
                                source="Narration source", metadata=provenance, job_id="abcdef123456")
            try:
                self.assertTrue(copying.wait(5))
                uploaded = pool.submit(uploader.upload, "fixture.mp3", io.BytesIO(b"Upload audio"),
                                       source=io.BytesIO(b"Upload source"),
                                       metadata={"title": "Upload", "words": 20}, if_absent=True)
                self.assertTrue(uploaded.result(timeout=5).created)
            finally:
                release.set()
            self.assertEqual(saved.result(timeout=5), "fixture-abcdef.mp3")

        upload = self.library.lookup("fixture.mp3")
        self.assertEqual((upload.title, upload.metadata["words"]), ("Upload", 20))
        self.assertEqual(self.library.read_source(upload.name), "Upload source")
        self.assertEqual(self.library.audio_file(upload.name).read_bytes(), b"Upload audio")
        narration = uploader.lookup("fixture-abcdef.mp3")
        self.assertEqual((narration.title, narration.metadata, narration.mtime),
                         ("Fixture", provenance, 1000000000))
        self.assertEqual(uploader.read_source(narration.name), "Narration source")
        self.assertEqual(uploader.audio_file(narration.name).read_bytes(), AUDIO)

    def test_narration_can_claim_name_while_conditional_upload_is_staging(self):
        completed = self.root / "completed.mp3"
        completed.write_bytes(AUDIO)
        uploader = Library(self.root, OWNER)
        copying, release = Event(), Event()

        class PausedAudio(io.BytesIO):
            def read(self, size):
                copying.set()
                if not release.wait(5):
                    raise TimeoutError("test did not release upload copy")
                return super().read(size)

        name = "fixture.mp3"
        provenance = {"secs": 26, "words": 100, "voice": "am_michael"}
        with ThreadPoolExecutor(2) as pool:
            uploaded = pool.submit(uploader.upload, name, PausedAudio(b"Upload audio"),
                                   source=io.BytesIO(b"Upload source"),
                                   metadata={"title": "Upload", "words": 20}, if_absent=True)
            try:
                self.assertTrue(copying.wait(5))
                saved = pool.submit(self.library.save_narration, completed, title="Fixture",
                                    source="Narration source", metadata=provenance, job_id="abcdef123456")
                self.assertEqual(saved.result(timeout=5), name)
            finally:
                release.set()
            with self.assertRaises(FileExistsError):
                uploaded.result(timeout=5)

        entry, = uploader.entries()
        self.assertEqual((entry.name, entry.title, entry.metadata), (name, "Fixture", provenance))
        self.assertEqual(uploader.read_source(name), "Narration source")
        self.assertEqual(uploader.audio_file(name).read_bytes(), AUDIO)

    def test_upload_conflict_and_replacement_preserve_omitted_source(self):
        result = self.library.upload("uploaded.m4a", io.BytesIO(b"first"), source=io.BytesIO(b"source"),
                                     metadata={"title": " Initial ", "words": 100, "duration_secs": 42})
        self.assertTrue(result.created)
        self.assertEqual(result.size, 5)
        self.assertEqual(self.library.lookup("uploaded.m4a").title, "Initial")
        unreadable = io.BytesIO()
        unreadable.close()
        with self.assertRaises(FileExistsError):
            self.library.upload("uploaded.m4a", unreadable, if_absent=True)
        self.assertEqual(self.library.audio_file("uploaded.m4a").read_bytes(), b"first")
        result = self.library.upload("uploaded.m4a", io.BytesIO(b"second"))
        self.assertFalse(result.created)
        self.assertEqual(result.size, 6)
        self.assertEqual(self.library.lookup("uploaded.m4a").title, "uploaded")
        self.assertEqual(self.library.read_source("uploaded.m4a"), "source")
        self.assertEqual(self.library.lookup("uploaded.m4a").metadata,
                         {"secs": None, "words": None, "voice": None, "duration_secs": None})
        self.assertEqual(self.library.audio_file("uploaded.m4a").read_bytes(), b"second")

    def test_failed_source_stream_preserves_entry_and_upload_can_retry(self):
        class BrokenSource(io.BytesIO):
            def read(self, size):
                data = super().read(size)
                if not data:
                    raise OSError("source stream interrupted")
                return data

        name = "fixture.m4a"
        path = self.legacy(name, audio=b"Before", title="Original", source="Original source",
                           meta={"words": 100, "duration_secs": 42})
        os.utime(path, (1000000000, 1000000000))
        writer = Library(self.root, OWNER)
        original = self.library.lookup(name)

        with self.assertRaisesRegex(OSError, "source stream interrupted"):
            writer.upload(name, io.BytesIO(b"After"), source=BrokenSource(b"Partial source"),
                          metadata={"title": "Replacement", "words": 20})

        self.assertEqual(self.library.audio_file(name).read_bytes(), b"Before")
        self.assertEqual(self.library.read_source(name), "Original source")
        self.assertEqual(self.library.lookup(name), original)
        result = writer.upload(name, io.BytesIO(b"After"), source=io.BytesIO(b"Complete source"),
                               metadata={"title": "Replacement", "words": 20})
        self.assertFalse(result.created)
        self.assertEqual(self.library.audio_file(name).read_bytes(), b"After")
        self.assertEqual(self.library.read_source(name), "Complete source")
        replacement = self.library.lookup(name)
        self.assertEqual((replacement.title, replacement.metadata["words"]), ("Replacement", 20))
        self.assertGreater(replacement.mtime, original.mtime)

    def test_upload_replaces_entry_with_long_supported_filename(self):
        name = "a" * 241 + ".mp3"
        self.assertTrue(self.library.upload(name, io.BytesIO(b"Previous")).created)
        self.assertFalse(self.library.upload(name, io.BytesIO(b"Replacement")).created)
        self.assertEqual(self.library.audio_file(name).read_bytes(), b"Replacement")

    def test_failed_audio_publication_restores_sidecars_and_upload_can_retry(self):
        name = "fixture.m4a"
        path = self.legacy(name, audio=b"Before", title="Original", meta={"words": 100})
        self.legacy("fixture.aac", audio=b"Same stem")
        writer = Library(self.root, OWNER)
        original = self.library.entries()
        replace = Path.replace

        def fail_audio(staged, destination):
            if destination == path:
                raise OSError("audio publication interrupted")
            return replace(staged, destination)

        def upload():
            return writer.upload(name, io.BytesIO(b"After"), source=io.BytesIO(b"New source"),
                                 metadata={"title": "Replacement", "words": 20})

        with patch.object(Path, "replace", fail_audio):
            with self.assertRaisesRegex(OSError, "audio publication interrupted"):
                upload()

        self.assertCountEqual(self.library.entries(), original)
        self.assertIsNone(self.library.read_source(name))
        self.assertEqual(self.library.audio_file(name).read_bytes(), b"Before")
        self.assertFalse(upload().created)
        self.assertEqual(self.library.audio_file(name).read_bytes(), b"After")
        self.assertEqual(self.library.read_source("fixture.aac"), "New source")
        self.assertEqual(self.library.lookup("fixture.aac").title, "Replacement")

    def test_listing_waits_for_publication_in_same_owner_directory(self):
        name = "fixture.aac"
        path = self.legacy(name, audio=b"Before", title="Original", meta={"words": 100})
        writer = Library(self.root / OWNER / "..", OWNER)
        other = Library(self.root, "other@example.com")
        publishing, release, listing = Event(), Event(), Event()
        replace = Path.replace

        def pause_audio(staged, destination):
            if destination.resolve() == path:
                publishing.set()
                if not release.wait(5):
                    raise TimeoutError("test did not release audio publication")
            return replace(staged, destination)

        def entries():
            listing.set()
            return self.library.entries()

        with patch.object(Path, "replace", pause_audio), ThreadPoolExecutor(3) as pool:
            uploaded = pool.submit(writer.upload, name, io.BytesIO(b"Longer audio"),
                                   metadata={"title": "Replacement", "words": 20})
            try:
                self.assertTrue(publishing.wait(5))
                listed = pool.submit(entries)
                self.assertTrue(listing.wait(5))
                self.assertEqual(pool.submit(other.entries).result(timeout=5), [])
                with self.assertRaises(TimeoutError):
                    listed.result(timeout=0.05)
            finally:
                release.set()
            self.assertFalse(uploaded.result(timeout=5).created)
            entry, = listed.result(timeout=5)

        self.assertEqual((entry.name, entry.title, entry.metadata["words"], entry.size),
                         (name, "Replacement", 20, 12))

    def test_history_includes_orphans_and_removal_keeps_shared_stem_behavior(self):
        self.legacy("shared.mp3", source="shared source", title="Shared display", meta={"words": 100})
        self.legacy("shared.aac")
        orphan = self.root / OWNER / "orphan.meta"
        orphan.write_text('{"secs": 30, "words": 100, "voice": "am_michael"}')
        (self.root / OWNER / "broken.meta").write_text("{broken")
        self.assertCountEqual(self.library.metadata_history(),
                              [{"words": 100}, {"secs": 30, "words": 100, "voice": "am_michael"}])
        other = Library(self.root, "other@example.com")
        other.upload("shared.mp3", io.BytesIO(AUDIO), source=io.BytesIO(b"other source"))
        self.assertTrue(self.library.delete("shared.mp3"))
        self.assertIsNone(self.library.lookup("shared.mp3"))
        self.assertEqual(self.library.lookup("shared.aac").title, "Shared")
        self.assertFalse(self.library.lookup("shared.aac").has_text)
        self.assertEqual(self.library.lookup("shared.aac").metadata, {})
        self.assertEqual(other.read_source("shared.mp3"), "other source")
        self.assertEqual(self.library.metadata_history(),
                         [{"secs": 30, "words": 100, "voice": "am_michael"}])
        self.assertFalse(self.library.delete("shared.mp3"))

    def test_title_mutation_keeps_identity_and_clear_uses_filename_fallback(self):
        audio = self.legacy("old_title.mp3", title="Before")
        os.utime(audio, (1000000000, 1000000000))
        self.assertTrue(self.library.set_title("old_title.mp3", "  " + "x" * 130 + "  "))
        entry = self.library.lookup("old_title.mp3")
        self.assertEqual(entry.title, "x" * 120)
        self.assertGreater(entry.mtime, 1000000000)
        self.assertEqual(self.library.audio_file(entry.name).read_bytes(), AUDIO)
        self.assertTrue(self.library.set_title(entry.name, None))
        self.assertEqual(self.library.lookup(entry.name).title, "Old title")
        self.library.delete(entry.name)
        self.assertFalse(self.library.set_title(entry.name, "No resurrection"))
        self.assertIsNone(self.library.lookup(entry.name))

    def test_optional_sidecars_fall_back_and_source_replaces_invalid_utf8(self):
        audio = self.legacy("missing-title.mp3", audio=b"not mp3")
        audio.with_suffix(".title").write_bytes(b"\xff")
        audio.with_suffix(".meta").write_text("{broken")
        audio.with_suffix(".md").write_bytes(b"source \xff")
        entry, = self.library.entries()
        self.assertEqual(entry.title, "Missing title")
        self.assertIsNone(entry.duration_secs)
        self.assertEqual(entry.metadata, {})
        self.assertTrue(entry.has_text)
        self.assertEqual(self.library.read_source(entry.name), "source \ufffd")
        audio.with_suffix(".meta").write_text("[1, 2]")
        self.assertEqual(self.library.lookup(entry.name).metadata, {})
        audio.with_suffix(".md").unlink()
        audio.with_suffix(".md").mkdir()
        self.assertIsNone(self.library.read_source(entry.name))
        self.assertFalse(self.library.lookup(entry.name).has_text)

    def test_download_resolution_keeps_standalone_source_and_owner_boundaries(self):
        self.legacy("legacy.Name_1.aac", source="source")
        (self.root / OWNER / "standalone.md").write_text("standalone")
        self.assertEqual(self.library.download_file("standalone.md").read_text(), "standalone")
        self.assertIsNone(self.library.source_file("standalone.aac"))
        self.assertEqual(self.library.source_file("legacy.Name_1.aac").read_text(), "source")
        for name in ("../completed.mp3", "/completed.mp3", "legacy.Name_1.meta", "missing.mp3"):
            with self.subTest(name=name):
                self.assertIsNone(self.library.download_file(name))
        other = Library(self.root, "other@example.com")
        self.assertIsNone(other.lookup("legacy.Name_1.aac"))
        self.assertIsNone(other.download_file("standalone.md"))

    def test_bare_extension_legacy_entry_uses_existing_shared_sidecars(self):
        (self.root / OWNER / ".mp3").write_bytes(AUDIO)
        (self.root / OWNER / ".title").write_text("Legacy title")
        (self.root / OWNER / ".md").write_text("Legacy source")
        entry, = self.library.entries()
        self.assertEqual((entry.name, entry.title, entry.source_name), (".mp3", "Legacy title", ".md"))
        self.assertEqual(entry.duration_secs, 1)
        self.assertEqual(self.library.read_source(".mp3"), "Legacy source")

    def test_mp3_duration_keeps_id3_offset_and_lower_mpeg_bitrates(self):
        self.legacy("tagged.mp3", audio=b"ID3\x04\x00\x00\x00\x00\x00\x04" + b"tag!" + AUDIO)
        self.assertEqual(self.library.lookup("tagged.mp3").duration_secs, 1)
        self.legacy("mpeg2.mp3", audio=b"\xff\xf3\x80\x00" + b"\x00" * 7996)
        self.assertEqual(self.library.lookup("mpeg2.mp3").duration_secs, 1)
        for audio in (b"ID3", b"\xff\xfb\x00\x00", b"\xff\xfb\xf0\x00", b""):
            self.legacy("invalid.mp3", audio=audio)
            self.assertIsNone(self.library.lookup("invalid.mp3").duration_secs)


if __name__ == "__main__":
    unittest.main()
