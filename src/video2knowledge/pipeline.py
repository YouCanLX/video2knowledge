from __future__ import annotations

import asyncio
import hashlib
import logging
import shutil
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from .config import BILIBILI_DOWNLOAD_CONCURRENCY
from .exporters import write_bundle
from .models import JobStatus, KnowledgeDocument, VideoItem
from .naming import library_filename_stem, library_relative_directory
from .ports import SpeechToText, TextEnricher, TextToSpeech, VideoProvider
from .repository import LibraryRepository

logger = logging.getLogger(__name__)
PauseCheckpoint = Callable[[JobStatus, float, str], Awaitable[None]]
MEDIA_SUFFIXES = {
    ".aac",
    ".flac",
    ".m4a",
    ".mka",
    ".mp3",
    ".mp4",
    ".ogg",
    ".opus",
    ".wav",
    ".webm",
}
REQUIRED_REUSABLE_OUTPUTS = {"markdown", "lyrics", "timeline", "metadata", "source_media"}
TRANSCRIPTION_CONCURRENCY = 1
ENRICHMENT_CONCURRENCY = 3


def find_cached_media_files(media_dir: Path, source_id: str) -> list[Path]:
    """Find complete media files associated with a source ID."""
    if not media_dir.exists():
        return []
    needle = source_id.casefold()
    return [
        path
        for path in media_dir.rglob("*")
        if path.is_file()
        and path.stat().st_size > 0
        and path.suffix.casefold() in MEDIA_SUFFIXES
        and needle in "/".join(path.relative_to(media_dir).parts).casefold()
    ]


def find_cached_media(media_dir: Path, source_id: str) -> Path | None:
    """Find the newest complete media file associated with a source ID."""
    candidates = find_cached_media_files(media_dir, source_id)
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> tuple[str, int]:
    """Hash a media file with bounded memory and return its digest and byte size."""
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def reusable_outputs(job: dict, synthesize: bool = False) -> dict[str, str] | None:
    """Return prior outputs only when every artifact needed by this request still exists."""
    outputs = job.get("outputs") or {}
    required = REQUIRED_REUSABLE_OUTPUTS | ({"audio"} if synthesize else set())
    if not required.issubset(outputs):
        return None
    for key in required:
        try:
            path = Path(outputs[key]).expanduser()
            available = path.is_file() and path.stat().st_size > 0
        except (OSError, TypeError):
            available = False
        if not available:
            return None
    return {str(key): str(value) for key, value in outputs.items() if value}


class Pipeline:
    def __init__(
        self,
        provider: VideoProvider,
        stt: SpeechToText,
        enricher: TextEnricher,
        tts: TextToSpeech,
        repository: LibraryRepository,
        media_dir: Path,
        library_dir: Path,
    ):
        self.provider, self.stt, self.enricher, self.tts = provider, stt, enricher, tts
        self.repository, self.media_dir, self.library_dir = repository, media_dir, library_dir
        self._download_slots = asyncio.Semaphore(BILIBILI_DOWNLOAD_CONCURRENCY)
        self._speech_slots = asyncio.Semaphore(TRANSCRIPTION_CONCURRENCY)
        self._enrichment_slots = asyncio.Semaphore(ENRICHMENT_CONCURRENCY)
        self._source_locks: dict[str, asyncio.Lock] = {}

    async def _deduplicate_media(self, source_id: str, path: Path) -> tuple[Path, bool]:
        sha256, size_bytes = await asyncio.to_thread(sha256_file, path)
        if size_bytes <= 0:
            raise RuntimeError("The downloaded media file is empty")
        existing = self.repository.get_media_asset(sha256)
        if existing:
            existing_path = Path(existing["path"]).expanduser()
            if existing_path.is_file() and existing_path.stat().st_size == size_bytes:
                if path.absolute() != existing_path.absolute():
                    path.unlink()
                    with suppress(OSError):
                        path.parent.rmdir()
                self.repository.save_media_asset(
                    source_id, sha256, str(existing_path.resolve()), size_bytes
                )
                return existing_path, True

        suffix = path.suffix.casefold() or ".media"
        asset_dir = self.media_dir / ".assets" / sha256[:2]
        asset_dir.mkdir(parents=True, exist_ok=True)
        asset_path = asset_dir / f"{sha256}{suffix}"
        if path.absolute() != asset_path.absolute():
            target_is_valid = asset_path.is_file() and asset_path.stat().st_size == size_bytes
            if target_is_valid:
                path.unlink()
            else:
                if asset_path.exists() or asset_path.is_symlink():
                    asset_path.unlink()
                shutil.move(str(path), str(asset_path))
            with suppress(OSError):
                path.parent.rmdir()
        self.repository.save_media_asset(source_id, sha256, str(asset_path.resolve()), size_bytes)
        return asset_path, False

    async def run(
        self,
        job_id: str,
        item: VideoItem,
        language: str = "zh-CN",
        synthesize: bool = False,
        force_refresh: bool = False,
        checkpoint: PauseCheckpoint | None = None,
    ) -> dict[str, str]:
        source_lock = self._source_locks.setdefault(item.source_id, asyncio.Lock())
        async with source_lock:
            return await self._run_one(
                job_id, item, language, synthesize, force_refresh, checkpoint
            )

    async def _run_one(
        self,
        job_id: str,
        item: VideoItem,
        language: str,
        synthesize: bool,
        force_refresh: bool,
        checkpoint: PauseCheckpoint | None,
    ) -> dict[str, str]:
        try:
            if not force_refresh:
                previous = self.repository.find_completed_job(item.source_id, language, synthesize)
                cached_outputs = reusable_outputs(previous, synthesize) if previous else None
                if cached_outputs:
                    media_path = str(Path(cached_outputs["source_media"]).expanduser().resolve())
                    asset = self.repository.get_media_asset_by_path(media_path)
                    if asset:
                        self.repository.save_media_asset(
                            item.source_id,
                            asset["sha256"],
                            media_path,
                            asset["size_bytes"],
                        )
                    self.repository.mark_job_downloaded(job_id)
                    self.repository.save_document(item, cached_outputs, cached_outputs.get("audio"))
                    self.repository.update_job(
                        job_id,
                        JobStatus.COMPLETE,
                        1,
                        "Media, transcription, summary, and exports already complete",
                        cached_outputs,
                    )
                    return cached_outputs
            registered = (
                None
                if force_refresh
                else self.repository.get_media_asset_for_source(item.source_id)
            )
            audio = Path(registered["path"]) if registered else None
            if audio and (not audio.is_file() or audio.stat().st_size != registered["size_bytes"]):
                audio = None
                registered = None
            if audio is None and not force_refresh:
                audio = find_cached_media(self.media_dir, item.source_id)
            if audio:
                await self._set_stage(
                    job_id,
                    JobStatus.DOWNLOADING,
                    0.25,
                    "Using cached audio",
                    checkpoint,
                )
            else:
                message = "Refreshing audio download" if force_refresh else "Downloading audio"
                await self._set_stage(
                    job_id,
                    JobStatus.QUEUED,
                    0.05,
                    "Waiting for download slot",
                    checkpoint,
                )
                async with self._download_slots:
                    await self._set_stage(job_id, JobStatus.DOWNLOADING, 0.1, message, checkpoint)
                    audio = await self.provider.download_audio(
                        item, self.media_dir / item.source_id, force_refresh=force_refresh
                    )
            if not registered or force_refresh:
                await self._set_stage(
                    job_id,
                    JobStatus.DOWNLOADING,
                    0.28,
                    "Checking media SHA-256",
                    checkpoint,
                )
                audio, duplicate = await self._deduplicate_media(item.source_id, audio)
                if duplicate:
                    await self._set_stage(
                        job_id,
                        JobStatus.DOWNLOADING,
                        0.3,
                        "Reusing identical media asset",
                        checkpoint,
                    )
            self.repository.mark_job_downloaded(job_id)
            await self._set_stage(
                job_id,
                JobStatus.TRANSCRIBING,
                0.32,
                "Waiting for transcription slot",
                checkpoint,
            )
            async with self._speech_slots:
                await self._set_stage(
                    job_id,
                    JobStatus.TRANSCRIBING,
                    0.35,
                    "Transcribing locally",
                    checkpoint,
                )
                segments = await asyncio.to_thread(self.stt.transcribe, audio, language)
            if not segments:
                raise RuntimeError("The transcription result is empty")
            await self._set_stage(
                job_id, JobStatus.ENRICHING, 0.62, "Waiting for enrichment slot", checkpoint
            )
            async with self._enrichment_slots:
                await self._set_stage(
                    job_id, JobStatus.ENRICHING, 0.65, "Generating summary", checkpoint
                )
                try:
                    enrichment = await self.enricher.enrich(
                        item.title, "\n".join(s.text for s in segments), language
                    )
                except Exception as exc:  # noqa: BLE001 - preserve transcript
                    logger.warning("enrichment failed: %s", exc)
                    from .models import Enrichment

                    enrichment = Enrichment(
                        summary=[
                            "LLM enrichment is unavailable; the full transcript was preserved."
                        ]
                    )
            document = KnowledgeDocument(item, segments, enrichment, language)
            filename_stem = library_filename_stem(item)
            output_dir = self.library_dir / library_relative_directory(item)
            output_dir.mkdir(parents=True, exist_ok=True)
            synthesized: Path | None = None
            if synthesize:
                await self._set_stage(
                    job_id,
                    JobStatus.SYNTHESIZING,
                    0.8,
                    "Waiting for speech synthesis slot",
                    checkpoint,
                )
                async with self._speech_slots:
                    await self._set_stage(
                        job_id,
                        JobStatus.SYNTHESIZING,
                        0.82,
                        "Synthesizing speech locally",
                        checkpoint,
                    )
                    synthesized = await asyncio.to_thread(
                        self.tts.synthesize,
                        segments,
                        output_dir / f"{filename_stem}-tts.wav",
                        language,
                    )
            await self._set_stage(
                job_id,
                JobStatus.SYNTHESIZING if synthesize else JobStatus.ENRICHING,
                0.95,
                "Writing library files",
                checkpoint,
            )
            written = await asyncio.to_thread(write_bundle, document, output_dir)
            outputs = {key: str(value) for key, value in written.items()}
            outputs["source_media"] = str(audio)
            if synthesized:
                outputs["audio"] = str(synthesized)
            audio_path = str(synthesized) if synthesized else None
            self.repository.save_document(item, outputs, audio_path)
            self.repository.update_job(
                job_id, JobStatus.COMPLETE, 1, "Processing complete", outputs
            )
            return outputs
        except Exception as exc:
            self.repository.update_job(job_id, JobStatus.FAILED, 1, str(exc))
            raise

    async def _set_stage(
        self,
        job_id: str,
        status: JobStatus,
        progress: float,
        message: str,
        checkpoint: PauseCheckpoint | None,
    ) -> None:
        self.repository.update_job(job_id, status, progress, message)
        if checkpoint:
            await checkpoint(status, progress, message)


@dataclass(slots=True)
class _JobControl:
    resume_event: asyncio.Event = field(default_factory=asyncio.Event)
    pause_requested: bool = False
    resume_status: JobStatus = JobStatus.QUEUED
    resume_progress: float = 0
    resume_message: str = "Waiting in processing pipeline"

    def __post_init__(self) -> None:
        self.resume_event.set()


class PipelineJobRunner:
    """Run jobs concurrently while Pipeline semaphores bound each resource stage."""

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self.queue: asyncio.Queue[tuple[str, VideoItem, str, bool, bool]] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()
        self._controls: dict[str, _JobControl] = {}

    def start(self) -> None:
        if not self._worker or self._worker.done():
            self._worker = asyncio.create_task(self._work())

    @property
    def active_job_ids(self) -> set[str]:
        """Jobs owned by this runner session, including its queued item."""
        return set(self._controls)

    async def submit(
        self,
        item: VideoItem,
        language: str = "zh-CN",
        synthesize: bool = False,
        force_refresh: bool = False,
    ) -> str:
        self.start()
        job_id = self.pipeline.repository.create_job(item, language, synthesize, force_refresh)
        self._controls[job_id] = _JobControl()
        await self.queue.put((job_id, item, language, synthesize, force_refresh))
        return job_id

    async def restart(self, job_id: str) -> dict:
        return (await self.restart_many([job_id]))[0]

    async def restart_many(self, job_ids: list[str]) -> list[dict]:
        unique_ids = list(dict.fromkeys(job_ids))
        jobs: list[dict] = []
        for job_id in unique_ids:
            job = self.pipeline.repository.get_job(job_id)
            if not job:
                raise KeyError(job_id)
            jobs.append(job)

        invalid = [job["id"] for job in jobs if JobStatus(job["status"]) != JobStatus.FAILED]
        if invalid:
            raise ValueError(f"Only failed jobs can be restarted: {invalid[0]}")

        self.start()
        restarted: list[dict] = []
        for job in jobs:
            job_id = str(job["id"])
            item = VideoItem(**job["source"])
            language = str(job.get("language") or "zh-CN")
            synthesize = bool(job.get("synthesize"))
            force_refresh = bool(job.get("force_refresh"))
            self._controls[job_id] = _JobControl()
            self.pipeline.repository.restart_job(job_id)
            await self.queue.put((job_id, item, language, synthesize, force_refresh))
            restarted.append(self.pipeline.repository.get_job(job_id) or job)
        return restarted

    def pause(self, job_id: str) -> dict:
        job = self.pipeline.repository.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        status = JobStatus(job["status"])
        if status in {JobStatus.COMPLETE, JobStatus.FAILED}:
            raise ValueError("Completed or failed jobs cannot be paused")
        control = self._controls.get(job_id)
        if not control:
            raise ValueError("This job is not active in the current app session")
        if status in {JobStatus.PAUSED, JobStatus.PAUSING}:
            return job

        control.resume_status = status
        control.resume_progress = float(job["progress"])
        control.resume_message = str(job["message"] or "Waiting in processing pipeline")
        control.pause_requested = True
        control.resume_event.clear()
        if status == JobStatus.QUEUED:
            paused_status = JobStatus.PAUSED
            message = "Paused in processing pipeline"
        else:
            paused_status = JobStatus.PAUSING
            message = "Pause requested; finishing the current step safely"
        self.pipeline.repository.update_job(job_id, paused_status, control.resume_progress, message)
        return self.pipeline.repository.get_job(job_id) or job

    def resume(self, job_id: str) -> dict:
        job = self.pipeline.repository.get_job(job_id)
        if not job:
            raise KeyError(job_id)
        status = JobStatus(job["status"])
        if status not in {JobStatus.PAUSED, JobStatus.PAUSING}:
            raise ValueError("Only paused jobs can be resumed")
        control = self._controls.get(job_id)
        if not control:
            raise ValueError("This paused job belongs to an earlier app session")

        control.pause_requested = False
        control.resume_event.set()
        self.pipeline.repository.update_job(
            job_id,
            control.resume_status,
            control.resume_progress,
            f"Resuming: {control.resume_message}",
        )
        return self.pipeline.repository.get_job(job_id) or job

    async def _checkpoint(
        self,
        job_id: str,
        control: _JobControl,
        status: JobStatus,
        progress: float,
        message: str,
    ) -> None:
        control.resume_status = status
        control.resume_progress = progress
        control.resume_message = message
        if not control.pause_requested:
            return
        self.pipeline.repository.update_job(
            job_id, JobStatus.PAUSED, progress, f"Paused before: {message}"
        )
        await control.resume_event.wait()
        self.pipeline.repository.update_job(job_id, status, progress, f"Resuming: {message}")

    async def _work(self) -> None:
        while True:
            job_id, item, language, synthesize, force_refresh = await self.queue.get()
            task = asyncio.create_task(
                self._run_job(job_id, item, language, synthesize, force_refresh)
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run_job(
        self,
        job_id: str,
        item: VideoItem,
        language: str,
        synthesize: bool,
        force_refresh: bool,
    ) -> None:
        control = self._controls[job_id]
        try:
            await self._checkpoint(
                job_id,
                control,
                JobStatus.QUEUED,
                0,
                "Waiting in processing pipeline",
            )
            await self.pipeline.run(
                job_id,
                item,
                language,
                synthesize,
                force_refresh,
                checkpoint=partial(self._checkpoint, job_id, control),
            )
        except Exception:
            logger.exception("job %s failed", job_id)
        finally:
            self._controls.pop(job_id, None)
            self.queue.task_done()


# Backward-compatible import for integrations built before the pipelined runner.
SerialJobRunner = PipelineJobRunner
