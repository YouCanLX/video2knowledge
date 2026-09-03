from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .exporters import write_bundle
from .models import JobStatus, KnowledgeDocument, VideoItem
from .naming import library_filename_stem, library_stem
from .ports import SpeechToText, TextEnricher, TextToSpeech, VideoProvider
from .repository import LibraryRepository

logger = logging.getLogger(__name__)
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
    ) -> dict[str, str]:
        try:
            audio = None if force_refresh else find_cached_media(self.media_dir, item.source_id)
            if audio:
                self.repository.update_job(
                    job_id, JobStatus.DOWNLOADING, 0.25, "Using cached audio"
                )
            else:
                message = "Refreshing audio download" if force_refresh else "Downloading audio"
                self.repository.update_job(job_id, JobStatus.DOWNLOADING, 0.1, message)
                audio = await self.provider.download_audio(
                    item, self.media_dir / item.source_id, force_refresh=force_refresh
                )
            self.repository.update_job(job_id, JobStatus.TRANSCRIBING, 0.35, "Transcribing locally")
            segments = await asyncio.to_thread(self.stt.transcribe, audio, language)
            if not segments:
                raise RuntimeError("The transcription result is empty")
            self.repository.update_job(job_id, JobStatus.ENRICHING, 0.65, "Generating summary")
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
            stem = library_stem(item)
            filename_stem = library_filename_stem(item)
            output_dir = self.library_dir / stem
            output_dir.mkdir(parents=True, exist_ok=True)
            synthesized: Path | None = None
            if synthesize:
                self.repository.update_job(
                    job_id, JobStatus.SYNTHESIZING, 0.82, "Synthesizing speech locally"
                )
                synthesized = await asyncio.to_thread(
                    self.tts.synthesize,
                    segments,
                    output_dir / f"{filename_stem}-tts.wav",
                    language,
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


class SerialJobRunner:
    """One-worker queue: intentionally enforces one download at a time."""

    def __init__(self, pipeline: Pipeline):
        self.pipeline = pipeline
        self.queue: asyncio.Queue[tuple[str, VideoItem, str, bool, bool]] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None

    def start(self) -> None:
        if not self._worker or self._worker.done():
            self._worker = asyncio.create_task(self._work())

    async def submit(
        self,
        item: VideoItem,
        language: str = "zh-CN",
        synthesize: bool = False,
        force_refresh: bool = False,
    ) -> str:
        self.start()
        job_id = self.pipeline.repository.create_job(item)
        await self.queue.put((job_id, item, language, synthesize, force_refresh))
        return job_id

    async def _work(self) -> None:
        while True:
            job_id, item, language, synthesize, force_refresh = await self.queue.get()
            try:
                await self.pipeline.run(job_id, item, language, synthesize, force_refresh)
            except Exception:
                logger.exception("job %s failed", job_id)
            finally:
                self.queue.task_done()
