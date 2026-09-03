from __future__ import annotations

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from . import __version__
from .adapters.bili_dl import BiliDlProvider
from .adapters.llm import create_enricher
from .config import Settings
from .mlx_service import MlxAudioServiceManager
from .models import JobStatus, VideoItem
from .pipeline import SerialJobRunner, find_cached_media_files
from .services import build_services
from .urls import extract_bilibili_bvid, extract_bilibili_creator_id

logger = logging.getLogger(__name__)
PACKAGE_DIR = Path(__file__).parent
TERMINAL_JOB_STATUSES = {JobStatus.COMPLETE, JobStatus.FAILED}


class JobRequest(BaseModel):
    video: VideoItem
    language: str = "zh-CN"
    synthesize: bool = False
    force_refresh: bool = False


class UrlJobRequest(BaseModel):
    url: str
    language: str = "zh-CN"
    synthesize: bool = False
    force_refresh: bool = False


class CollectionSelection(BaseModel):
    kind: Literal["season", "series"]
    id: int = Field(gt=0)


class CreatorBatchRequest(BaseModel):
    creator_id: int = Field(gt=0)
    all_collections: bool = False
    all_uploads: bool = False
    collections: list[CollectionSelection] = Field(default_factory=list, max_length=500)
    videos: list[VideoItem] = Field(default_factory=list, max_length=5000)
    language: str = "zh-CN"
    synthesize: bool = False
    force_refresh: bool = False


class RuntimeSettingsRequest(BaseModel):
    media_dir: str = Field(min_length=1)
    library_dir: str = Field(min_length=1)
    mlx_base_url: str = Field(min_length=1)
    mlx_audio_command: str = Field(min_length=1)
    llm_backend: Literal["codex_cli", "openai_compatible"] = "codex_cli"
    codex_cli_path: str = Field(default="codex", min_length=1)
    codex_model: str = ""
    codex_timeout_seconds: float = Field(default=900, gt=0)
    llm_base_url: str = Field(default="http://127.0.0.1:11434/v1", min_length=1)
    llm_model: str = Field(default="qwen3:8b", min_length=1)


def _runtime_path_value(path: Path, data_dir: Path) -> str:
    try:
        return str(path.resolve().relative_to(data_dir.resolve()))
    except ValueError:
        return str(path.resolve())


def _settings_payload(settings: Settings) -> dict[str, str | float]:
    return {
        "media_dir": _runtime_path_value(settings.media_dir, settings.data_dir),
        "library_dir": _runtime_path_value(settings.library_dir, settings.data_dir),
        "mlx_base_url": settings.mlx_base_url,
        "mlx_audio_command": settings.mlx_audio_command,
        "llm_backend": settings.llm_backend,
        "codex_cli_path": settings.codex_cli_path,
        "codex_model": settings.codex_model,
        "codex_timeout_seconds": settings.codex_timeout_seconds,
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
    }


def _resolve_runtime_path(data_dir: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return (path if path.is_absolute() else data_dir / path).resolve()


def _job_file_candidates(job: dict, media_dir: Path) -> list[Path]:
    source_id = str(job["source"]["source_id"])
    paths = {Path(value).expanduser() for value in job["outputs"].values() if value}
    paths.update(find_cached_media_files(media_dir, source_id))
    return sorted(paths, key=str)


def _delete_job_files(job: dict, media_dir: Path) -> tuple[list[str], list[str]]:
    source_id = str(job["source"]["source_id"])
    removed: list[str] = []
    skipped: list[str] = []
    for path in _job_file_candidates(job, media_dir):
        if source_id.casefold() not in str(path).casefold():
            skipped.append(str(path))
            continue
        if not path.exists() and not path.is_symlink():
            continue
        path.unlink()
        removed.append(str(path))
        with suppress(OSError):
            path.parent.rmdir()
    return removed, skipped


def _fetch_bilibili_image(url: str) -> tuple[bytes, str]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    allowed = host.endswith(".hdslb.com") or host.endswith(".biliimg.com")
    if parsed.scheme != "https" or not allowed or parsed.port not in {None, 443}:
        raise ValueError("Only Bilibili image CDN URLs are allowed")
    request = UrlRequest(url, headers={"User-Agent": "Mozilla/5.0", "Referer": ""})
    with urlopen(request, timeout=15) as upstream:
        final = urlparse(upstream.geturl())
        final_host = (final.hostname or "").lower()
        if not (
            final.scheme == "https"
            and (final_host.endswith(".hdslb.com") or final_host.endswith(".biliimg.com"))
        ):
            raise ValueError("The Bilibili image redirected to an unsupported host")
        content_type = upstream.headers.get_content_type()
        content = upstream.read(5_000_001)
    if not content_type.startswith("image/") or len(content) > 5_000_000:
        raise ValueError("The Bilibili image response is invalid or too large")
    return content, content_type


async def _fetch_all_pages(fetch_page, page_size: int = 30) -> list[dict]:
    items: list[dict] = []
    for page in range(1, 1001):
        payload = await fetch_page(page, page_size)
        page_items = payload.get("items") or []
        items.extend(page_items)
        if not payload.get("has_more") or not page_items:
            return items
    raise RuntimeError("Bilibili returned too many pages to import safely")


async def _expand_creator_batch(provider, body: CreatorBatchRequest) -> list[VideoItem]:
    selected: dict[str, VideoItem] = {video.source_id: video for video in body.videos}
    collections = list(body.collections)
    if body.all_collections:
        rows = await _fetch_all_pages(
            lambda page, size: provider.get_creator_collections(body.creator_id, page, size),
            page_size=20,
        )
        collections = [CollectionSelection(kind=row["kind"], id=row["id"]) for row in rows]
    if body.all_uploads:
        rows = await _fetch_all_pages(
            lambda page, size: provider.get_creator_videos(body.creator_id, page, size)
        )
        selected.update((row["source_id"], VideoItem(**row)) for row in rows)
    creator: dict[str, str | int] | None = None
    for collection in collections:
        rows = await _fetch_all_pages(
            lambda page, size, current=collection: provider.get_collection_videos(
                body.creator_id, current.kind, current.id, page, size
            )
        )
        if creator is None:
            creator = await provider.get_creator(body.creator_id)
        for row in rows:
            video = VideoItem(**row)
            video.author = video.author or str(creator["name"])
            selected[video.source_id] = video
    return list(selected.values())


async def _open_local_path(path: Path, reveal: bool) -> None:
    opener = shutil.which("open")
    if not opener:
        raise RuntimeError("Opening local files requires the macOS 'open' command")
    arguments = [opener]
    if reveal:
        arguments.append("-R")
    arguments.append(str(path))
    process = await asyncio.create_subprocess_exec(
        *arguments,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode:
        detail = stderr.decode(errors="replace").strip()
        raise RuntimeError(detail or f"The open command exited with status {process.returncode}")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.load()
    services = build_services(settings)
    provider = services.provider
    repository = services.repository
    runner = SerialJobRunner(services.pipeline)
    mlx_manager = MlxAudioServiceManager(
        settings.mlx_audio_command,
        settings.mlx_base_url,
        settings.data_dir / "logs" / "mlx-audio.log",
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        await mlx_manager.shutdown()

    app = FastAPI(title="Video2Knowledge", version=__version__, lifespan=lifespan)
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(PACKAGE_DIR / "static")), name="static")
    app.state.services = services
    app.state.runner = runner
    app.state.mlx_manager = mlx_manager

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request):
        return templates.TemplateResponse(request=request, name="index.html")

    @app.get("/api/bilibili/image")
    async def bilibili_image(url: str = Query(min_length=1)):
        try:
            content, content_type = await asyncio.to_thread(_fetch_bilibili_image, url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(502, f"Bilibili image loading failed: {exc}") from exc
        return Response(
            content=content,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/api/search")
    async def search(q: str = Query(min_length=1), page: int = Query(1, ge=1)):
        try:
            return [item.to_dict() for item in await provider.search(q, page)]
        except Exception as exc:
            raise HTTPException(502, f"Bilibili search failed: {exc}") from exc

    @app.get("/api/creators")
    async def creators(q: str = Query(min_length=1), page: int = Query(1, ge=1)):
        try:
            return await provider.search_creators(q, page)
        except Exception as exc:
            raise HTTPException(502, f"Creator search failed: {exc}") from exc

    @app.get("/api/creators/from-url")
    async def creator_from_url(url: str = Query(min_length=1)):
        try:
            creator_id = extract_bilibili_creator_id(url)
            return await provider.get_creator(creator_id)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(502, f"Bilibili creator resolution failed: {exc}") from exc

    @app.get("/api/creators/{creator_id}/collections")
    async def creator_collections(
        creator_id: int,
        page: int = Query(1, ge=1),
        page_size: int = Query(8, ge=1, le=20),
    ):
        try:
            return await provider.get_creator_collections(creator_id, page, page_size)
        except Exception as exc:
            raise HTTPException(502, f"Bilibili collection loading failed: {exc}") from exc

    @app.get("/api/creators/{creator_id}/videos")
    async def creator_videos(
        creator_id: int,
        page: int = Query(1, ge=1),
        page_size: int = Query(12, ge=1, le=30),
    ):
        try:
            return await provider.get_creator_videos(creator_id, page, page_size)
        except Exception as exc:
            raise HTTPException(502, f"Bilibili upload loading failed: {exc}") from exc

    @app.get("/api/creators/{creator_id}/collections/{kind}/{collection_id}/videos")
    async def collection_videos(
        creator_id: int,
        kind: Literal["season", "series"],
        collection_id: int,
        page: int = Query(1, ge=1),
        page_size: int = Query(12, ge=1, le=30),
    ):
        try:
            return await provider.get_collection_videos(
                creator_id, kind, collection_id, page, page_size
            )
        except Exception as exc:
            raise HTTPException(502, f"Bilibili collection videos failed: {exc}") from exc

    @app.post("/api/jobs", status_code=202)
    async def create_job(body: JobRequest):
        return {
            "id": await runner.submit(
                body.video, body.language, body.synthesize, body.force_refresh
            )
        }

    @app.post("/api/jobs/creator-batch", status_code=202)
    async def create_creator_batch(body: CreatorBatchRequest):
        if not (body.all_collections or body.all_uploads or body.collections or body.videos):
            raise HTTPException(422, "Select at least one collection or video")
        try:
            videos = await _expand_creator_batch(provider, body)
        except Exception as exc:
            raise HTTPException(502, f"Bilibili batch expansion failed: {exc}") from exc
        if not videos:
            raise HTTPException(422, "The selection does not contain any available videos")
        job_ids = [
            await runner.submit(video, body.language, body.synthesize, body.force_refresh)
            for video in videos
        ]
        return {"submitted": len(job_ids), "job_ids": job_ids}

    @app.post("/api/jobs/url", status_code=202)
    async def create_url_job(body: UrlJobRequest):
        try:
            source_id = extract_bilibili_bvid(body.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        try:
            video = await provider.resolve(source_id)
        except Exception as exc:
            raise HTTPException(502, f"Bilibili video resolution failed: {exc}") from exc
        return {
            "id": await runner.submit(video, body.language, body.synthesize, body.force_refresh),
            "video": video.to_dict(),
        }

    @app.get("/api/jobs")
    async def list_jobs():
        return repository.list_jobs()

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        job = repository.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    def output_path(job_id: str, output_key: str) -> Path:
        job = repository.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job["status"] != JobStatus.COMPLETE:
            raise HTTPException(409, "Files can only be opened for completed jobs")
        value = job["outputs"].get(output_key)
        if not value:
            raise HTTPException(404, "Job output not found")
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = (settings.data_dir / path).resolve()
        if not path.is_file():
            raise HTTPException(404, f"Local output file does not exist: {path}")
        return path

    @app.post("/api/jobs/{job_id}/outputs/{output_key}/open")
    async def open_job_output(job_id: str, output_key: str):
        path = output_path(job_id, output_key)
        try:
            await _open_local_path(path, reveal=False)
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"action": "opened", "path": str(path)}

    @app.post("/api/jobs/{job_id}/outputs/{output_key}/reveal")
    async def reveal_job_output(job_id: str, output_key: str):
        path = output_path(job_id, output_key)
        try:
            await _open_local_path(path, reveal=True)
        except RuntimeError as exc:
            raise HTTPException(500, str(exc)) from exc
        return {"action": "revealed", "path": str(path)}

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str, delete_files: bool = False):
        job = repository.get_job(job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job["status"] not in TERMINAL_JOB_STATUSES:
            raise HTTPException(409, "Only completed or failed jobs can be deleted")

        removed: list[str] = []
        skipped: list[str] = []
        if delete_files:
            try:
                removed, skipped = _delete_job_files(job, settings.media_dir)
            except OSError as exc:
                raise HTTPException(500, f"Could not delete a local file: {exc}") from exc
            repository.delete_document(str(job["source"]["source_id"]))
        repository.delete_job(job_id)
        return {"deleted": job_id, "removed_files": removed, "skipped_files": skipped}

    @app.get("/api/library")
    async def library(q: str = "", tag: str = "", charging: bool | None = None):
        return repository.list_documents(q, tag, charging)

    @app.get("/api/settings")
    async def get_settings():
        return _settings_payload(settings)

    @app.put("/api/settings")
    async def update_settings(body: RuntimeSettingsRequest):
        new_mlx_url = body.mlx_base_url.rstrip("/")
        mlx_changed = (
            body.mlx_audio_command != settings.mlx_audio_command
            or new_mlx_url != settings.mlx_base_url.rstrip("/")
        )
        if mlx_changed and mlx_manager.is_managed_running:
            raise HTTPException(409, "Stop the managed MLX Audio service before changing it")

        settings.media_dir = _resolve_runtime_path(settings.data_dir, body.media_dir)
        settings.library_dir = _resolve_runtime_path(settings.data_dir, body.library_dir)
        settings.mlx_base_url = new_mlx_url
        settings.mlx_audio_command = body.mlx_audio_command.strip()
        settings.llm_backend = body.llm_backend
        settings.codex_cli_path = body.codex_cli_path.strip()
        settings.codex_model = body.codex_model.strip()
        settings.codex_timeout_seconds = body.codex_timeout_seconds
        settings.llm_base_url = body.llm_base_url.rstrip("/")
        settings.llm_model = body.llm_model.strip()
        settings.ensure_dirs()
        settings.save()

        services.pipeline.media_dir = settings.media_dir
        services.pipeline.library_dir = settings.library_dir
        services.pipeline.enricher = create_enricher(settings)
        services.audio.base_url = settings.mlx_base_url
        if isinstance(provider, BiliDlProvider):
            provider.set_download_dir(settings.media_dir)
        mlx_manager.configure(settings.mlx_audio_command, settings.mlx_base_url)
        return _settings_payload(settings)

    @app.get("/api/mlx/status")
    async def mlx_status():
        return (await mlx_manager.status()).to_dict()

    @app.post("/api/mlx/start", status_code=202)
    async def start_mlx():
        try:
            return (await mlx_manager.start()).to_dict()
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/mlx/stop")
    async def stop_mlx():
        return (await mlx_manager.stop()).to_dict()

    @app.post("/api/login", status_code=202)
    async def login():
        async def run_login() -> None:
            try:
                await provider.login()
            except Exception:
                logger.exception("bili-dl login failed")

        asyncio.create_task(run_login())
        return {"message": "The bili-dl QR login flow started in the server terminal"}

    return app
