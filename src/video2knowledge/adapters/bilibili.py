from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import VideoItem


class BilibiliProvider:
    """Bilibili adapter with a public search API and bili-dl/yt-dlp integration."""

    SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
    VIEW_URL = "https://api.bilibili.com/x/web-interface/view"
    NAV_URL = "https://api.bilibili.com/x/web-interface/nav"
    CREATOR_INFO_URL = "https://api.bilibili.com/x/space/wbi/acc/info"
    CREATOR_VIDEOS_URL = "https://api.bilibili.com/x/space/wbi/arc/search"
    COLLECTIONS_URL = "https://api.bilibili.com/x/polymer/web-space/seasons_series_list"
    SEASON_VIDEOS_URL = "https://api.bilibili.com/x/polymer/web-space/seasons_archives_list"
    SERIES_VIDEOS_URL = "https://api.bilibili.com/x/series/archives"
    MIXIN_KEY_ORDER = (
        46,
        47,
        18,
        2,
        53,
        8,
        23,
        32,
        15,
        50,
        10,
        31,
        58,
        3,
        45,
        35,
        27,
        43,
        5,
        49,
        33,
        9,
        42,
        19,
        29,
        28,
        14,
        39,
        12,
        38,
        41,
        13,
        37,
        48,
        7,
        16,
        24,
        55,
        40,
        61,
        26,
        17,
        0,
        1,
        60,
        51,
        30,
        4,
        22,
        25,
        54,
        21,
        56,
        59,
        6,
        63,
        57,
        62,
        11,
        36,
        20,
        34,
        44,
        52,
    )

    def __init__(self, bili_dl_dir: Path | None = None, cookie_file: Path | None = None):
        self.bili_dl_dir = bili_dl_dir
        self.cookie_file = cookie_file
        self._mixin_key = ""
        self._mixin_key_time = 0.0

    async def search(self, query: str, page: int = 1) -> list[VideoItem]:
        return await asyncio.to_thread(self._search_sync, query, page)

    async def resolve(self, source_id: str) -> VideoItem:
        return await asyncio.to_thread(self._resolve_sync, source_id)

    async def get_creator(self, creator_id: int) -> dict[str, str | int]:
        return await asyncio.to_thread(self._get_creator_sync, creator_id)

    async def get_creator_collections(
        self, creator_id: int, page: int = 1, page_size: int = 8
    ) -> dict:
        return await asyncio.to_thread(
            self._get_creator_collections_sync, creator_id, page, page_size
        )

    async def get_creator_videos(self, creator_id: int, page: int = 1, page_size: int = 12) -> dict:
        return await asyncio.to_thread(self._get_creator_videos_sync, creator_id, page, page_size)

    async def get_collection_videos(
        self,
        creator_id: int,
        collection_kind: str,
        collection_id: int,
        page: int = 1,
        page_size: int = 12,
    ) -> dict:
        return await asyncio.to_thread(
            self._get_collection_videos_sync,
            creator_id,
            collection_kind,
            collection_id,
            page,
            page_size,
        )

    def _headers(self, referer: str = "https://www.bilibili.com/") -> dict[str, str]:
        headers = {"User-Agent": "Mozilla/5.0", "Referer": referer}
        cookie = self._cookie_header()
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _cookie_header(self) -> str:
        if not self.cookie_file or not self.cookie_file.is_file():
            return ""
        cookies: list[str] = []
        for line in self.cookie_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line or line.startswith("#"):
                continue
            fields = line.split("\t")
            if len(fields) >= 7:
                cookies.append(f"{fields[-2]}={fields[-1]}")
        return "; ".join(cookies)

    def _request_data(
        self,
        url: str,
        params: dict[str, object] | None = None,
        *,
        wbi: bool = False,
        allow_error_data: bool = False,
    ) -> dict:
        query = dict(params or {})
        if wbi:
            query = self._sign_wbi(query)
        target = f"{url}?{urlencode(query)}" if query else url
        request = Request(target, headers=self._headers())
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
        if payload.get("code") != 0 and not (allow_error_data and payload.get("data")):
            detail = payload.get("message") or payload.get("msg") or "Bilibili request failed"
            raise RuntimeError(str(detail))
        return payload.get("data") or {}

    def _sign_wbi(self, params: dict[str, object]) -> dict[str, object]:
        if not self._mixin_key or time.time() - self._mixin_key_time > 43_200:
            # Logged-out nav responses use code -101 but still provide the public WBI keys.
            nav = self._request_data(self.NAV_URL, allow_error_data=True)
            wbi_img = nav.get("wbi_img") or {}
            keys = "".join(
                str(wbi_img.get(name, "")).rsplit("/", 1)[-1].split(".", 1)[0]
                for name in ("img_url", "sub_url")
            )
            self._mixin_key = "".join(
                keys[index] for index in self.MIXIN_KEY_ORDER if index < len(keys)
            )[:32]
            self._mixin_key_time = time.time()
        signed = {key: value for key, value in params.items() if value is not None}
        signed.setdefault("web_location", 1550101)
        signed["wts"] = int(time.time())
        encoded = urlencode(sorted(signed.items()))
        signed["w_rid"] = hashlib.md5((encoded + self._mixin_key).encode()).hexdigest()
        return signed

    def _get_creator_sync(self, creator_id: int) -> dict[str, str | int]:
        try:
            info = self._request_data(self.CREATOR_INFO_URL, {"mid": creator_id}, wbi=True)
        except (OSError, RuntimeError):
            data = self._request_data(
                self.COLLECTIONS_URL,
                {"mid": creator_id, "page_num": 1, "page_size": 1},
            )
            lists = data.get("items_lists") or {}
            rows = (lists.get("seasons_list") or []) + (lists.get("series_list") or [])
            archive = (rows[0].get("archives") or [None])[0] if rows else None
            if not archive or not archive.get("bvid"):
                return {
                    "id": creator_id,
                    "name": f"UP {creator_id}",
                    "avatar": "",
                    "description": "Public creator profile details are unavailable.",
                }
            video = self._resolve_sync(str(archive["bvid"]))
            return {
                "id": creator_id,
                "name": video.author or f"UP {creator_id}",
                "avatar": "",
                "description": f"Bilibili creator UID {creator_id}",
            }
        return {
            "id": creator_id,
            "name": str(info.get("name", f"UP {creator_id}")),
            "avatar": _image_url(str(info.get("face", ""))),
            "description": str(info.get("sign", "")),
        }

    def _get_creator_collections_sync(self, creator_id: int, page: int, page_size: int) -> dict:
        data = self._request_data(
            self.COLLECTIONS_URL,
            {"mid": creator_id, "page_num": page, "page_size": page_size},
        )
        return _collections_page_payload(data, page, page_size)

    def _get_creator_videos_sync(self, creator_id: int, page: int, page_size: int) -> dict:
        data = self._request_data(
            self.CREATOR_VIDEOS_URL,
            {
                "mid": creator_id,
                "pn": page,
                "ps": page_size,
                "tid": 0,
                "keyword": "",
                "order": "pubdate",
                "order_avoided": "true",
                "platform": "web",
            },
            wbi=True,
        )
        return _uploads_page_payload(data, creator_id, page, page_size)

    def _get_collection_videos_sync(
        self,
        creator_id: int,
        collection_kind: str,
        collection_id: int,
        page: int,
        page_size: int,
    ) -> dict:
        if collection_kind == "season":
            data = self._request_data(
                self.SEASON_VIDEOS_URL,
                {
                    "mid": creator_id,
                    "season_id": collection_id,
                    "sort_reverse": "false",
                    "page_num": page,
                    "page_size": page_size,
                },
            )
            page_info = data.get("page") or {}
            total = int(page_info.get("total", 0))
        elif collection_kind == "series":
            data = self._request_data(
                self.SERIES_VIDEOS_URL,
                {
                    "mid": creator_id,
                    "series_id": collection_id,
                    "only_normal": "true",
                    "sort": "asc",
                    "pn": page,
                    "ps": page_size,
                },
            )
            page_info = data.get("page") or {}
            total = int(page_info.get("total", 0))
        else:
            raise ValueError("Unknown Bilibili collection kind")
        items = [_archive_to_video(row, creator_id) for row in data.get("archives") or []]
        return _page_payload(items, page, page_size, total or len(items))

    def _resolve_sync(self, source_id: str) -> VideoItem:
        request = Request(
            f"{self.VIEW_URL}?{urlencode({'bvid': source_id})}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
        )
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
        if payload.get("code") != 0 or not payload.get("data"):
            detail = payload.get("message") or "Bilibili video metadata is unavailable"
            raise RuntimeError(str(detail))
        info = payload["data"]
        owner = info.get("owner") or {}
        rights = info.get("rights") or {}
        return VideoItem(
            platform="bilibili",
            source_id=source_id,
            title=str(info.get("title", source_id)),
            url=f"https://www.bilibili.com/video/{source_id}/",
            author=str(owner.get("name", "")),
            author_id=str(owner.get("mid", "")),
            description=str(info.get("desc", "")),
            cover_url=str(info.get("pic", "")),
            duration=float(info.get("duration", 0)),
            published_at=str(info.get("pubdate", "")),
            tags=[str(info.get("tname", ""))] if info.get("tname") else [],
            is_charging=bool(
                info.get("is_charging_arc")
                or info.get("is_charge_plus")
                or rights.get("ugc_pay")
                or rights.get("is_chargeable_season")
            ),
        )

    def _search_sync(self, query: str, page: int) -> list[VideoItem]:
        params = urlencode({"search_type": "video", "keyword": query, "page": page})
        request = Request(
            f"{self.SEARCH_URL}?{params}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
        )
        with urlopen(request, timeout=15) as response:
            payload = json.load(response)
        results = payload.get("data", {}).get("result") or []
        items: list[VideoItem] = []
        for row in results:
            badges = " ".join(str(x) for x in row.get("badges", []))
            title = re.sub(r"<[^>]+>", "", html.unescape(row.get("title", "")))
            bvid = str(row.get("bvid", ""))
            items.append(
                VideoItem(
                    platform="bilibili",
                    source_id=bvid,
                    title=title,
                    url=f"https://www.bilibili.com/video/{bvid}",
                    author=str(row.get("author", "")),
                    author_id=str(row.get("mid", "")),
                    description=str(row.get("description", "")),
                    cover_url="https:" + row["pic"]
                    if str(row.get("pic", "")).startswith("//")
                    else str(row.get("pic", "")),
                    duration=_parse_duration(str(row.get("duration", "0"))),
                    published_at=str(row.get("pubdate", "")),
                    tags=[query],
                    is_charging="\u5145\u7535" in (badges + title + str(row.get("typename", ""))),
                )
            )
        return items

    async def search_creators(self, query: str, page: int = 1) -> list[dict[str, str | int]]:
        return await asyncio.to_thread(self._search_creators_sync, query, page)

    def _search_creators_sync(self, query: str, page: int) -> list[dict[str, str | int]]:
        params = urlencode({"search_type": "bili_user", "keyword": query, "page": page})
        request = Request(
            f"{self.SEARCH_URL}?{params}",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"},
        )
        with urlopen(request, timeout=15) as response:
            rows = json.load(response).get("data", {}).get("result") or []
        return [
            {
                "id": int(row.get("mid", 0)),
                "name": str(row.get("uname", "")),
                "avatar": "https:" + row["upic"]
                if str(row.get("upic", "")).startswith("//")
                else str(row.get("upic", "")),
                "description": str(row.get("usign", "")),
                "fans": int(row.get("fans", 0)),
                "videos": int(row.get("videos", 0)),
            }
            for row in rows
        ]

    async def download_audio(
        self, item: VideoItem, output_dir: Path, force_refresh: bool = False
    ) -> Path:
        return await asyncio.to_thread(self._download_sync, item, output_dir, force_refresh)

    def _download_sync(
        self, item: VideoItem, output_dir: Path, force_refresh: bool = False
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        executable = shutil.which("yt-dlp")
        if not executable:
            raise RuntimeError("yt-dlp was not found; install the bilibili optional dependencies")
        template = str(output_dir / f"{item.source_id}.%(ext)s")
        command = [
            executable,
            "--no-playlist",
            "-f",
            "bestaudio[ext=m4a]/bestaudio",
            "-o",
            template,
        ]
        if force_refresh:
            command.append("--force-overwrites")
        if self.cookie_file:
            if not self.cookie_file.exists():
                raise RuntimeError(f"Cookie file does not exist: {self.cookie_file}")
            command.extend(["--cookies", str(self.cookie_file)])
        command.append(item.url)
        subprocess.run(command, check=True)
        candidates = [
            path
            for path in output_dir.glob(f"{item.source_id}.*")
            if path.suffix not in {".part", ".ytdl"}
        ]
        if not candidates:
            raise RuntimeError("The download command completed without producing an audio file")
        return max(candidates, key=lambda path: path.stat().st_mtime)

    async def login(self) -> str:
        if not self.bili_dl_dir or not (self.bili_dl_dir / "main.py").exists():
            raise RuntimeError("Set the bili-dl source directory in the configuration first")
        process = await asyncio.create_subprocess_exec(
            sys.executable, "main.py", cwd=self.bili_dl_dir
        )
        await process.wait()
        return "The bili-dl login flow has finished"


def _parse_duration(value: str) -> float:
    try:
        parts = [float(part) for part in value.split(":")]
        return sum(part * (60**index) for index, part in enumerate(reversed(parts)))
    except ValueError:
        return 0.0


def _image_url(value: str) -> str:
    if value.startswith("//"):
        return "https:" + value
    if value.startswith("http://"):
        value = "https://" + value.removeprefix("http://")
    if "/bfs/archive/" in value and "@" not in value:
        return value + "@320w_180h_1c.webp"
    return value


def _archive_to_video(row: dict, creator_id: int) -> dict:
    bvid = str(row.get("bvid", ""))
    author = str(row.get("author") or row.get("owner", {}).get("name") or "")
    duration = row.get("duration", 0)
    return VideoItem(
        platform="bilibili",
        source_id=bvid,
        title=str(row.get("title", bvid)),
        url=f"https://www.bilibili.com/video/{bvid}/",
        author=author,
        author_id=str(row.get("mid") or row.get("upMid") or creator_id),
        description=str(row.get("description") or row.get("desc") or ""),
        cover_url=_image_url(str(row.get("pic", ""))),
        duration=_parse_duration(str(duration)) if ":" in str(duration) else float(duration or 0),
        published_at=str(row.get("pubdate", "")),
        is_charging=bool(row.get("ugc_pay")),
    ).to_dict()


def _collections_page_payload(data: dict, page: int, page_size: int) -> dict:
    lists = data.get("items_lists") or {}
    page_info = lists.get("page") or {}
    items: list[dict] = []
    for kind, key, id_key in (
        ("season", "seasons_list", "season_id"),
        ("series", "series_list", "series_id"),
    ):
        for row in lists.get(key) or []:
            meta = row.get("meta") or {}
            items.append(
                {
                    "kind": kind,
                    "id": int(meta.get(id_key, 0)),
                    "title": str(meta.get("title") or meta.get("name") or "Untitled"),
                    "description": str(meta.get("description", "")),
                    "cover_url": _image_url(str(meta.get("cover", ""))),
                    "total": int(meta.get("total", 0)),
                }
            )
    total = int(page_info.get("total", len(items)))
    return _page_payload(items, page, page_size, total)


def _uploads_page_payload(data: dict, creator_id: int, page: int, page_size: int) -> dict:
    listing = data.get("list") or {}
    items = [_archive_to_video(row, creator_id) for row in listing.get("vlist") or []]
    total = int((data.get("page") or {}).get("count", len(items)))
    return _page_payload(items, page, page_size, total)


def _page_payload(items: list[dict], page: int, page_size: int, total: int) -> dict:
    return {
        "items": items,
        "page": page,
        "page_size": page_size,
        "total": total,
        "has_more": page * page_size < total,
    }
