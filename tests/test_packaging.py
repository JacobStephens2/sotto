import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PackagingTests(unittest.TestCase):
    def test_docker_sources_import_through_service_entry_point(self):
        with tempfile.TemporaryDirectory() as directory:
            # Use the Dockerfile's actual source manifest, rather than a second list.
            for line in (ROOT / "Dockerfile").read_text().splitlines():
                if not line.startswith("COPY "):
                    continue
                parts = shlex.split(line)
                if parts[-1] == ".":
                    for source in parts[1:-1]:
                        shutil.copy2(ROOT / source, Path(directory) / source)
            env = {**os.environ, "LECTOR_RESUME": "0", "SMTP_HOST": "", "SMTP_PASS": ""}
            env.pop("PYTHONPATH", None)
            result = subprocess.run(
                [sys.executable, "-B", "-c",
                 "import pkgutil; application = pkgutil.resolve_name('app:app'); "
                 "assert application.test_client().get('/healthz').status_code == 200"],
                cwd=directory, env=env, text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
