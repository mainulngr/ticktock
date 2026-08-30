import unittest
from pathlib import Path

from ticktock.emby import EmbySync
from ticktock.models import Channel


class FakeEmbySync(EmbySync):
    def __init__(self) -> None:
        super().__init__("http://emby", "key", Path("/media/tocks"))
        self.requests = []

    def _request(self, method, path, query=None):
        self.requests.append((method, path, query))
        if path == "/Library/VirtualFolders":
            return [{"ItemId": "library", "Locations": ["/media/tocks"]}]
        if path == "/Items":
            if query.get("ParentId") == "library":
                return {"Items": [{"Id": "folder", "Name": "channel", "Type": "Folder"}]}
            if query.get("ParentId") == "folder":
                return {"Items": [{"Id": "video-1", "Type": "Video"}, {"Id": "video-2", "Type": "Video"}]}
            if query.get("IncludeItemTypes") == "BoxSet":
                return {"Items": [{"Id": "collection", "Name": "channel", "Type": "BoxSet"}]}
            if query.get("ParentId") == "collection":
                return {"Items": [{"Id": "folder", "Type": "Folder"}, {"Id": "video-1", "Type": "Video"}]}
        return None


class EmbySyncTest(unittest.TestCase):
    def test_adds_missing_videos_and_removes_folder_layer(self) -> None:
        sync = FakeEmbySync()

        added = sync.sync([Channel(id="channel", username="channel", output_dir="channel")])

        self.assertEqual(1, added)
        self.assertIn(
            ("POST", "/Collections/collection/Items", {"Ids": "video-2"}),
            sync.requests,
        )
        self.assertIn(
            ("DELETE", "/Collections/collection/Items", {"Ids": "folder"}),
            sync.requests,
        )


if __name__ == "__main__":
    unittest.main()
