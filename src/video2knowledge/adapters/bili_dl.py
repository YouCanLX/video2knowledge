from __future__ import annotations

import sys
from pathlib import Path

from ..models import VideoItem
from .bilibili import (
    BilibiliProvider,
    _archive_to_video,
    _collections_page_payload,
    _image_url,
    _page_payload,
    _uploads_page_payload,
)


class BiliDlProvider(BilibiliProvider):
    """Adapter over war-ning/bili-dl's native API and downloader."""

    def __init__(self, bili_dl_dir: Path, cookie_file: Path | None = None):
        super().__init__(bili_dl_dir, cookie_file)
        self.data_dir = bili_dl_dir / "data"
        if not (bili_dl_dir / "bili_dl").exists():
            raise FileNotFoundError(f"Invalid bili-dl directory: {bili_dl_dir}")
        if str(bili_dl_dir) not in sys.path:
            sys.path.insert(0, str(bili_dl_dir))

    def _native_services(self):
        from bili_dl.api.client import BiliClient
        from bili_dl.config import ConfigManager

        manager = ConfigManager(str(self.data_dir))
        config = manager.load()
        if not config.sessdata:
            raise RuntimeError("bili-dl is not logged in; run v2k login first")
        config.max_concurrent = 1
        return manager, config, BiliClient(config)

    def set_download_dir(self, download_dir: Path) -> None:
        """Keep bili-dl's native output directory aligned with application settings."""
        from bili_dl.config import ConfigManager

        manager = ConfigManager(str(self.data_dir))
        config = manager.load()
        config.download_dir = str(download_dir)
        config.max_concurrent = 1
        manager.save(config)

    async def resolve(self, bvid: str) -> VideoItem:
        from bili_dl.api.video import get_video_info

        _, _, client = self._native_services()
        info = await get_video_info(client, bvid)
        owner = info.get("owner") or {}
        rights = info.get("rights") or {}
        return VideoItem(
            platform="bilibili",
            source_id=bvid,
            title=str(info.get("title", bvid)),
            url=f"https://www.bilibili.com/video/{bvid}/",
            author=str(owner.get("name", "")),
            author_id=str(owner.get("mid", "")),
            description=str(info.get("desc", "")),
            cover_url=str(info.get("pic", "")),
            duration=float(info.get("duration", 0)),
            published_at=str(info.get("pubdate", "")),
            tags=[],
            is_charging=bool(
                info.get("is_charging_arc")
                or info.get("is_charge_plus")
                or rights.get("ugc_pay")
                or rights.get("is_chargeable_season")
            ),
            creator_avatar_url=_image_url(str(owner.get("face", ""))),
        )

    async def get_creator(self, creator_id: int) -> dict[str, str | int]:
        from bili_dl.api.client import with_risk_retry
        from bilibili_api.user import User

        _, _, client = self._native_services()
        await client.throttle()
        info = await with_risk_retry(
            lambda: User(uid=creator_id, credential=client.credential).get_user_info(),
            op_name="UP 主资料",
        )
        return {
            "id": creator_id,
            "name": str(info.get("name", f"UP {creator_id}")),
            "avatar": _image_url(str(info.get("face", ""))),
            "description": str(info.get("sign", "")),
        }

    async def get_creator_collections(
        self, creator_id: int, page: int = 1, page_size: int = 8
    ) -> dict:
        from bili_dl.api.client import with_risk_retry
        from bilibili_api.user import User

        _, _, client = self._native_services()
        await client.throttle()
        data = await with_risk_retry(
            lambda: User(uid=creator_id, credential=client.credential).get_channel_list(
                pn=page, ps=page_size
            ),
            op_name="合集列表",
        )
        return _collections_page_payload(data, page, page_size)

    async def get_creator_videos(self, creator_id: int, page: int = 1, page_size: int = 12) -> dict:
        from bili_dl.api.client import with_risk_retry
        from bilibili_api.user import User

        _, _, client = self._native_services()
        await client.throttle()
        data = await with_risk_retry(
            lambda: User(uid=creator_id, credential=client.credential).get_videos(
                pn=page, ps=page_size
            ),
            op_name="投稿列表",
        )
        return _uploads_page_payload(data, creator_id, page, page_size)

    async def get_collection_videos(
        self,
        creator_id: int,
        collection_kind: str,
        collection_id: int,
        page: int = 1,
        page_size: int = 12,
    ) -> dict:
        from bili_dl.api.client import with_risk_retry
        from bilibili_api.channel_series import ChannelOrder
        from bilibili_api.user import User

        _, _, client = self._native_services()
        user = User(uid=creator_id, credential=client.credential)
        await client.throttle()
        if collection_kind == "season":
            data = await with_risk_retry(
                lambda: user.get_channel_videos_season(
                    sid=collection_id,
                    sort=ChannelOrder.DEFAULT,
                    pn=page,
                    ps=page_size,
                ),
                op_name="合集视频",
            )
        elif collection_kind == "series":
            data = await with_risk_retry(
                lambda: user.get_channel_videos_series(
                    sid=collection_id,
                    sort=ChannelOrder.CHANGE,
                    pn=page,
                    ps=page_size,
                ),
                op_name="系列视频",
            )
        else:
            raise ValueError("Unknown Bilibili collection kind")
        items = [_archive_to_video(row, creator_id) for row in data.get("archives") or []]
        total = int((data.get("page") or {}).get("total", len(items)))
        return _page_payload(items, page, page_size, total)

    async def download_audio(
        self, item: VideoItem, output_dir: Path, force_refresh: bool = False
    ) -> Path:
        from bili_dl.core.downloader import BatchDownloader
        from bili_dl.core.history import DownloadHistory
        from bili_dl.models import DownloadStatus, DownloadTask, DownloadType, VideoInfo

        manager, config, client = self._native_services()
        resolved = await self.resolve(item.source_id)
        native = VideoInfo(
            bvid=resolved.source_id,
            title=resolved.title,
            pic_url=resolved.cover_url,
            duration=int(resolved.duration),
            play_count=0,
            publish_time=int(resolved.published_at or 0),
            is_charge_plus=resolved.is_charging,
            author_name=resolved.author,
            author_mid=int(resolved.author_id or 0),
        )
        task = DownloadTask(
            video_info=native,
            download_type=DownloadType.AUDIO_FAST,
            merge_pages=True,
        )
        downloader = BatchDownloader(config, client, DownloadHistory(manager.get_history_path()))
        result = await downloader.execute_task(task)
        if result.status != DownloadStatus.COMPLETED or not result.file_path:
            raise RuntimeError(result.error_msg or "bili-dl audio download failed")
        path = Path(result.file_path)
        if not path.exists():
            raise RuntimeError(f"The audio returned by bili-dl does not exist: {path}")
        return path
