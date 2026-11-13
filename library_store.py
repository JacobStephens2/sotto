"""Filename-keyed Library storage, bound to an already-authorized account."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil


@dataclass(frozen=True)
class Entry:
    name: str
    title: str
    size: int
    mtime: float
    metadata: dict
    duration_secs: int | float | None
    has_text: bool
    source_name: str


@dataclass(frozen=True)
class UploadResult:
    created: bool
    size: int


def _sidecar(audio, suffix):
    # All supported audio extensions have four characters, including the dot.
    # Slicing also preserves the legacy convention for a bare '.mp3' filename.
    return audio.with_name(audio.name[:-4] + suffix)


def _metadata(path):
    try:
        with path.open() as stream:
            value = json.load(stream)
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _mp3_duration(path):
    """Use the first frame's bitrate, as both narration backends produce CBR."""
    try:
        size = path.stat().st_size
        with path.open("rb") as stream:
            head = stream.read(10)
            off = 0
            if head[:3] == b"ID3":
                off = 10 + (((head[6] & 0x7f) << 21) | ((head[7] & 0x7f) << 14)
                            | ((head[8] & 0x7f) << 7) | (head[9] & 0x7f))
            stream.seek(off)
            hdr = stream.read(4)
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
    except (OSError, IndexError):
        return None


class Library:
    def __init__(self, root, owner):
        self._directory = Path(root) / owner
        self._directory.mkdir(parents=True, exist_ok=True)

    def _audio_path(self, name):
        if Path(name).name != name or not name.endswith((".mp3", ".m4a", ".aac")):
            return None
        return self._directory / name

    def audio_file(self, name):
        path = self._audio_path(name)
        return path if path is not None and path.is_file() else None

    def source_file(self, name):
        audio = self.audio_file(name)
        if audio is None:
            return None
        path = _sidecar(audio, ".md")
        return path if path.is_file() else None

    def download_file(self, name):
        """Web downloads also accept an existing standalone source file."""
        if Path(name).name != name:
            return None
        if name.endswith(".md"):
            path = self._directory / name
            return path if path.is_file() else None
        return self.audio_file(name)

    def read_source(self, name):
        path = self.source_file(name)
        if path is not None:
            try:
                return path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
        return None

    def lookup(self, name):
        path = self.audio_file(name)
        if path is None:
            return None
        title = ""
        try:
            title = _sidecar(path, ".title").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            pass
        metadata = _metadata(_sidecar(path, ".meta"))
        stat = path.stat()
        return Entry(name=name,
                     title=title or re.sub(r"[-_]+", " ", name[:-4]).strip().capitalize(),
                     size=stat.st_size, mtime=stat.st_mtime, metadata=metadata,
                     duration_secs=(_mp3_duration(path) if name.endswith(".mp3")
                                    else metadata.get("duration_secs")),
                     has_text=self.source_file(name) is not None,
                     source_name=_sidecar(path, ".md").name)

    def entries(self):
        return [entry for name in os.listdir(self._directory)
                if (entry := self.lookup(name)) is not None]

    def metadata_history(self):
        """Calibration includes provenance even after its audio has gone missing."""
        try:
            names = os.listdir(self._directory)
        except OSError:
            return []
        return [record for name in names
                if name.endswith(".meta") and (record := _metadata(self._directory / name))]

    def delete(self, name):
        path = self.audio_file(name)
        if path is None:
            return False
        for target in (path, _sidecar(path, ".md"), _sidecar(path, ".title"), _sidecar(path, ".meta")):
            try:
                target.unlink()
            except OSError:
                pass
        return True

    def save_narration(self, audio, *, title, source, metadata, job_id):
        slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60] or "narration"
        name = slug + ".mp3"
        if (self._directory / name).exists():
            name = f"{slug}-{job_id[:6]}.mp3"
        path = self._directory / name
        shutil.copy2(audio, path)
        if source:
            _sidecar(path, ".md").write_text(source, encoding="utf-8")
        _sidecar(path, ".title").write_text(title, encoding="utf-8")
        with _sidecar(path, ".meta").open("w") as stream:
            json.dump({key: metadata.get(key) for key in ("secs", "words", "voice")}, stream)
        return name

    def upload(self, name, audio, *, source=None, metadata=None, if_absent=False):
        path = self._audio_path(name)
        if path is None:
            raise ValueError("unsupported audio filename")
        existed = path.exists()
        if existed and if_absent:
            raise FileExistsError(name)
        temporary = path.with_name(path.name + ".tmp")
        with temporary.open("wb") as stream:
            shutil.copyfileobj(audio, stream)
        os.replace(temporary, path)
        if source is not None:
            with _sidecar(path, ".md").open("wb") as stream:
                shutil.copyfileobj(source, stream)
        metadata = metadata or {}
        with _sidecar(path, ".meta").open("w") as stream:
            json.dump({key: metadata.get(key) for key in ("secs", "words", "voice", "duration_secs")}, stream)
        _sidecar(path, ".title").write_text(
            str(metadata.get("title") or "")[:120] or name[:-4], encoding="utf-8")
        return UploadResult(created=not existed, size=path.stat().st_size)

    def set_title(self, name, title):
        """Change a title and its sync revision; None clears to filename fallback.

        A missing audio file stays deleted, including its optional sidecars.
        """
        audio = self._audio_path(name)
        if audio is None or not audio.is_file():
            return False
        sidecar = _sidecar(audio, ".title")
        if title is None:
            try:
                sidecar.unlink()
            except OSError:
                pass
        else:
            sidecar.write_text(title.strip()[:120], encoding="utf-8")
        os.utime(audio, None)
        return True
