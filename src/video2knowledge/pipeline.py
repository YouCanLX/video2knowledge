from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

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

    async def run(
        self,
        job_id: str,
        item: VideoItem,
        language: str = "zh-CN",
        synthesize: bool = False,
        force_refresh: bool = False,
        checkpoint: PauseCheckpoint | None = None,
    ) -> dict[str, str]:
        try:
            if not force_refresh:
                previous = self.repository.find_completed_job(item.source_id, language, synthesize)
                cached_outputs = reusable_outputs(previous, synthesize) if previous else None
                if cached_outputs:
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
            audio = None if force_refresh else find_cached_media(self.media_dir, item.source_id)
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
                await self._set_stage(job_id, JobStatus.DOWNLOADING, 0.1, message, checkpoint)
                audio = await self.provider.download_audio(
                    item, self.media_dir / item.source_id, force_refresh=force_refresh
                )
            self.repository.mark_job_downloaded(job_id)
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
                job_id, JobStatus.ENRICHING, 0.65, "Generating summary", checkpoint
            )
            try:
                enrichment = await self.enricher.enrich(
                    item.title, "\n".join(s.text for s in segments), language
                )
            except Exception as exc:  # noqa: BLE001 - optional enrichment must not lose transcript
                logger.warning("enrichment failed: %s", exc)
                from .models import Enrichment

                enrichment = Enrichment(
                    summary=["LLM enrichment is unavailable; the full transcript was preserved."]
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
            outputs = {key: str(value) for key, value in write_bundle(document, output_dir).items()}
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
    resume_message: str = "Waiting in serial queue"

    def __post_init__(self) -> None:
        self.resume_event.set()


class SerialJobRunner:
    """One-worker queue: intentionally enforces one download at a time."""

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self.queue: asyncio.Queue[tuple[str, VideoItem, str, bool, bool]] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
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
        control.resume_message = str(job["message"] or "Waiting in serial queue")
        control.pause_requested = True
        control.resume_event.clear()
        if status == JobStatus.QUEUED:
            paused_status = JobStatus.PAUSED
            message = "Paused in serial queue"
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
            control = self._controls[job_id]
            try:
                await self._checkpoint(
                    job_id,
                    control,
                    JobStatus.QUEUED,
                    0,
                    "Waiting in serial queue",
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
