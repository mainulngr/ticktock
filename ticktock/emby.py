import json
import logging
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

from .models import Channel

logger = logging.getLogger(__name__)


class EmbySync:
    def __init__(self, url: str, api_key: str, library_path: Path) -> None:
        self.url = url.rstrip("/") + "/emby"
        self.api_key = api_key
        self.library_path = library_path.resolve()

    def _request(self, method: str, path: str, query: dict[str, str] | None = None) -> dict | list | None:
        url = self.url + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        request = urllib.request.Request(
            url,
            data=b"" if method != "GET" else None,
            headers={"X-Emby-Token": self.api_key},
            method=method,
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
        return json.loads(body) if body else None

    def _items(self, **query: str) -> list[dict]:
        response = self._request("GET", "/Items", query)
        return response.get("Items", []) if isinstance(response, dict) else []

    def _add_items(self, collection_id: str, item_ids: list[str]) -> None:
        for start in range(0, len(item_ids), 100):
            self._request(
                "POST",
                f"/Collections/{collection_id}/Items",
                {"Ids": ",".join(item_ids[start:start + 100])},
            )

    def _library_id(self) -> str:
        libraries = self._request("GET", "/Library/VirtualFolders")
        if not isinstance(libraries, list):
            raise RuntimeError("Emby returned an invalid library response")
        for library in libraries:
            locations = {Path(path).resolve() for path in library.get("Locations", [])}
            if self.library_path in locations:
                return str(library["ItemId"])
        raise RuntimeError(f"Emby library not found for {self.library_path}")

    def sync(self, channels: Iterable[Channel]) -> int:
        library_id = self._library_id()
        folders = self._items(ParentId=library_id, Recursive="false", IncludeItemTypes="Folder", Limit="1000")
        folders_by_name = {item["Name"]: item for item in folders}
        collections = self._items(Recursive="true", IncludeItemTypes="BoxSet", Limit="1000")
        collections_by_name = {item["Name"]: item for item in collections}
        added = 0

        for channel in channels:
            name = channel.output_dir
            folder = folders_by_name.get(name)
            if not folder:
                continue
            videos = self._items(
                ParentId=str(folder["Id"]),
                Recursive="true",
                IncludeItemTypes="Video",
                Limit="100000",
            )
            video_ids = [str(video["Id"]) for video in videos]
            if not video_ids:
                continue

            collection = collections_by_name.get(name)
            if not collection:
                collection = self._request(
                    "POST",
                    "/Collections",
                    {"Name": name, "Ids": ",".join(video_ids[:100]), "IsLocked": "false"},
                )
                if not isinstance(collection, dict) or not collection.get("Id"):
                    raise RuntimeError(f"Emby did not return the new collection for {name}")
                collections_by_name[name] = collection

            collection_id = str(collection["Id"])
            members = self._items(ParentId=collection_id, Recursive="false", Limit="100000")
            member_ids = {str(item["Id"]) for item in members}
            missing_ids = [video_id for video_id in video_ids if video_id not in member_ids]
            self._add_items(collection_id, missing_ids)
            added += len(missing_ids)

            folder_member_ids = [str(item["Id"]) for item in members if item.get("Type") == "Folder"]
            if folder_member_ids:
                self._request(
                    "DELETE",
                    f"/Collections/{collection_id}/Items",
                    {"Ids": ",".join(folder_member_ids)},
                )

        logger.info("Emby collections synchronized: %d video(s) added", added)
        return added
