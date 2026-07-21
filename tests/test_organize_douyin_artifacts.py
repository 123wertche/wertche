import tempfile
import unittest
from pathlib import Path

from organize_douyin_artifacts import collect_artifacts


class OrganizeArtifactsTests(unittest.TestCase):
    def test_collects_raw_clean_subtitles_and_metadata_without_name_collisions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            transcript = root / "transcript"
            asr = transcript / "asr"
            asr.mkdir(parents=True)
            paths = {
                "video_path": root / "video.mp4",
                "cover_path": root / "cover.jpg",
                "metadata_path": root / "metadata.json",
                "description_path": root / "video-description.txt",
                "speech_clean_path": transcript / "speech-clean.txt",
                "speech_raw_path": transcript / "speech-raw.txt",
                "audio_path": transcript / "audio_16k.wav",
            }
            for path in paths.values():
                path.write_text("x", encoding="utf-8")
            (root / "manifest.json").write_text("{}", encoding="utf-8")
            (asr / "audio_16k.srt").write_text("x", encoding="utf-8")
            success = {key: str(value) for key, value in paths.items()}

            artifacts = collect_artifacts(success, {})
            folders = {folder.replace("\\", "/") for _, folder in artifacts}

            self.assertIn("02_转写文档/清洗转写", folders)
            self.assertIn("02_转写文档/原始转写", folders)
            self.assertIn("05_字幕", folders)
            self.assertIn("07_元数据与说明/单视频清单", folders)


if __name__ == "__main__":
    unittest.main()
