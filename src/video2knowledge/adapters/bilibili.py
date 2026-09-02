from __future__ import annotations

import asyncio
import html
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..models import VideoItem


class BilibiliProvider:
    """Bilibili adapter with a public search API and bili-dl/yt-dlp integration."""

    SEARCH_URL = "https://api.bilibili.com/x/web-interface/search/type"
    VIEW_URL = "https://api.bilibili.com/x/web-interface/view"

    def __init__(self, bili_dl_dir: Path | None = None, cookie_file: Path | None = None):
        self.bili_dl_dir = bili_dl_dir
        self.cookie_file = cookie_file

    async def search(self, query: str, page: int = 1) -> list[VideoItem]:
        return await asyncio.to_thread(self._search_sync, query, page)

    async def resolve(self, source_id: str) -> VideoItem:
        return await asyncio.to_thread(self._resolve_sync, source_id)

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
