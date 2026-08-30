import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ticktock.thumbnails import Thumbnailer


class ThumbnailerTest(unittest.TestCase):
    def test_generates_matching_jpeg_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.touch()

            def run(command, **kwargs):
                Path(command[-1]).write_bytes(b"jpeg")
                return subprocess.CompletedProcess(command, 0)

            with patch("ticktock.thumbnails.subprocess.run", side_effect=run) as mocked_run:
                generated = Thumbnailer("custom-ffmpeg").generate(video)

            self.assertTrue(generated)
            self.assertEqual(b"jpeg", video.with_suffix(".jpg").read_bytes())
            self.assertEqual("custom-ffmpeg", mocked_run.call_args.args[0][0])
            self.assertFalse(video.with_suffix(".tmp.jpg").exists())

    def test_skips_existing_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.touch()
            video.with_suffix(".jpg").touch()

            with patch("ticktock.thumbnails.subprocess.run") as mocked_run:
                generated = Thumbnailer().generate(video)

            self.assertFalse(generated)
            mocked_run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
