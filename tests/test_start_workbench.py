import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import start_workbench


class FakeProcess:
    pid = 1234

    def poll(self):
        return None


class StartWorkbenchTests(unittest.TestCase):
    def test_launcher_prefers_pythonw_and_breaks_away_from_parent_job(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pythonw = root / ".venv" / "Scripts" / "pythonw.exe"
            pythonw.parent.mkdir(parents=True)
            pythonw.write_text("", encoding="utf-8")
            calls = []

            def popen(*args, **kwargs):
                calls.append((args, kwargs))
                return FakeProcess()

            with (
                patch.object(start_workbench, "ROOT", root),
                patch.object(start_workbench, "ready", side_effect=[False, True]),
                patch.object(start_workbench.subprocess, "Popen", side_effect=popen),
                patch.object(start_workbench.webbrowser, "open"),
            ):
                self.assertEqual(start_workbench.main(), 0)

            command = calls[0][0][0]
            flags = calls[0][1]["creationflags"]
            calls[0][1]["stdout"].close()
            self.assertEqual(Path(command[0]), pythonw)
            self.assertTrue(flags & getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000))


if __name__ == "__main__":
    unittest.main()
