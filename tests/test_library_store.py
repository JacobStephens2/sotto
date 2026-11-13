import io
import json
import os
from pathlib import Path
import tempfile
import unittest

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
        self.assertEqual(self.library.save_narration(completed, title="?!", source="", metadata={},
                                                    job_id="123456"), "narration.mp3")

    def test_upload_conflict_and_replacement_preserve_omitted_source(self):
        result = self.library.upload("uploaded.m4a", io.BytesIO(b"first"), source=io.BytesIO(b"source"),
                                     metadata={"title": " Initial ", "words": 100, "duration_secs": 42})
        self.assertTrue(result.created)
        self.assertEqual(result.size, 5)
        self.assertEqual(self.library.lookup("uploaded.m4a").title, "Initial")
        with self.assertRaises(FileExistsError):
            self.library.upload("uploaded.m4a", io.BytesIO(b"conflicting"), if_absent=True)
        self.assertEqual(self.library.audio_file("uploaded.m4a").read_bytes(), b"first")
        result = self.library.upload("uploaded.m4a", io.BytesIO(b"second"))
        self.assertFalse(result.created)
        self.assertEqual(result.size, 6)
        self.assertEqual(self.library.lookup("uploaded.m4a").title, "uploaded")
        self.assertEqual(self.library.read_source("uploaded.m4a"), "source")
        self.assertEqual(self.library.lookup("uploaded.m4a").metadata,
                         {"secs": None, "words": None, "voice": None, "duration_secs": None})
        self.assertEqual(self.library.audio_file("uploaded.m4a").read_bytes(), b"second")
        self.assertFalse((self.root / OWNER / "uploaded.m4a.tmp").exists())

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
        self.assertFalse(audio.with_suffix(".title").exists())
        self.library.delete(entry.name)
        self.assertFalse(self.library.set_title(entry.name, "No resurrection"))
        self.assertIsNone(self.library.lookup(entry.name))
        self.assertFalse(audio.with_suffix(".title").exists())

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
