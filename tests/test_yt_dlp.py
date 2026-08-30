import unittest
from types import SimpleNamespace

from ticktock.yt_dlp import YtDlp


class YtDlpTest(unittest.TestCase):
    def test_download_requests_use_chrome_impersonation(self) -> None:
        config = SimpleNamespace(
            yt_dlp_path="yt-dlp",
            sleep_requests=None,
            sleep_interval=None,
            max_sleep_interval=None,
        )

        args = YtDlp(config)._base_args()

        self.assertIn("--impersonate", args)
        self.assertEqual("chrome", args[args.index("--impersonate") + 1])


if __name__ == "__main__":
    unittest.main()
