from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
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
from .urls import extract_bilibili_bvid

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

    @app.post("/api/jobs", status_code=202)
    async def create_job(body: JobRequest):
        return {
            "id": await runner.submit(
                body.video, body.language, body.synthesize, body.force_refresh
            )
        }

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
