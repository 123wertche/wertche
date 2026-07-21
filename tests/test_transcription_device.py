import ast
import unittest
from pathlib import Path

from transcription_device import TranscriptionDeviceError, choose_device, transcribe_with_fallback


class DeviceTests(unittest.TestCase):
    def test_entrypoint_imports_device_helpers_before_main_guard(self):
        root = Path(__file__).resolve().parents[1]
        for name in ("download_douyin_latest.py", "postprocess_bili_videos.py"):
            tree = ast.parse((root / name).read_text(encoding="utf-8"))
            import_line = min(
                node.lineno
                for node in tree.body
                if isinstance(node, ast.ImportFrom) and node.module == "transcription_device"
            )
            main_guard_line = min(
                node.lineno
                for node in tree.body
                if isinstance(node, ast.If)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.left, ast.Name)
                and node.test.left.id == "__name__"
            )
            self.assertLess(import_line, main_guard_line, name)

    def test_auto_prefers_cuda_and_falls_back_to_cpu(self):
        decision = choose_device("auto", probe=lambda: (True, "ready"))
        calls = []
        def run(device):
            calls.append(device)
            if device == "cuda":
                raise TranscriptionDeviceError("CUDA out of memory", gpu_related=True)
            return Path("speech.txt")
        path, final = transcribe_with_fallback(run, decision)
        self.assertEqual(calls, ["cuda", "cpu"])
        self.assertEqual(final.selected, "cpu")
        self.assertEqual(path, Path("speech.txt"))

    def test_non_gpu_failure_is_not_retried(self):
        decision = choose_device("auto", probe=lambda: (True, "ready"))
        with self.assertRaises(TranscriptionDeviceError):
            transcribe_with_fallback(lambda device: (_ for _ in ()).throw(TranscriptionDeviceError("bad media", gpu_related=False)), decision)


if __name__ == "__main__":
    unittest.main()
