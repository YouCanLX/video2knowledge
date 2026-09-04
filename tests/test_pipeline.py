import asyncio
import threading
import time
from pathlib import Path

from video2knowledge.models import Enrichment, TranscriptSegment, VideoItem
from video2knowledge.pipeline import Pipeline, PipelineJobRunner
from video2knowledge.repository import LibraryRepository


class FakeProvider:
    def __init__(self):
        self.active = 0
        self.peak = 0
        self.download_count = 0

    async def download_audio(self, item, output_dir, force_refresh=False):
        self.download_count += 1
        self.active += 1
        self.peak = max(self.peak, self.active)
        await asyncio.sleep(0.01)
        output_dir.mkdir(parents=True, exist_ok=True)
        path = output_dir / "audio.wav"
        path.write_bytes(b"fake")
        self.active -= 1
        return path


class FakeSTT:
    def transcribe(self, path, language=None):
        return [TranscriptSegment(0, 1, "Content")]


class FakeLLM:
    async def enrich(self, title, text, language):
        return Enrichment(summary=["Summary"])


class FakeTTS:
    def synthesize(self, segments, output_path, language):
        output_path.write_bytes(b"audio")
        return output_path


class BlockingProvider(FakeProvider):
    def __init__(self):
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.started_count = 0

    async def download_audio(self, item, output_dir, force_refresh=False):
        self.started_count += 1
        self.started.set()
        await self.release.wait()
        return await super().download_audio(item, output_dir, force_refresh)


class FailOnceProvider(FakeProvider):
    async def download_audio(self, item, output_dir, force_refresh=False):
        if self.download_count == 0:
            self.download_count += 1
            raise RuntimeError("temporary download failure")
        return await super().download_audio(item, output_dir, force_refresh)


async def wait_for_job_status(repo, job_id, expected):
    async with asyncio.timeout(1):
        while repo.get_job(job_id)["status"] != expected:
            await asyncio.sleep(0.005)


def test_runner_limits_concurrent_downloads_to_three(tmp_path):
    async def scenario():
        provider = FakeProvider()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        runner = PipelineJobRunner(pipeline)
        items = [
            VideoItem("bilibili", source_id, source_id, f"https://{source_id.lower()}")
            for source_id in ("A", "B", "C", "D")
        ]
        ids = [await runner.submit(item) for item in items]
        await runner.queue.join()
        assert provider.peak == 3
        assert all(repo.get_job(job_id)["status"] == "complete" for job_id in ids)
        assert (
            tmp_path / "library" / "UnknownCreator" / "UnknownCreator_A_A" / "UnknownCreator_A_A.md"
        ).exists()
        runner._worker.cancel()

    asyncio.run(scenario())


def test_runner_pipelines_download_transcription_and_enrichment(tmp_path):
    class StagedProvider(FakeProvider):
        def __init__(self):
            super().__init__()
            self.fourth_download_started = threading.Event()

        async def download_audio(self, item, output_dir, force_refresh=False):
            self.download_count += 1
            self.active += 1
            self.peak = max(self.peak, self.active)
            if item.source_id == "D":
                self.fourth_download_started.set()
            await asyncio.sleep(0 if item.source_id == "A" else 0.02)
            output_dir.mkdir(parents=True, exist_ok=True)
            path = output_dir / "audio.wav"
            path.write_bytes(item.source_id.encode())
            self.active -= 1
            return path

    class StagedSTT(FakeSTT):
        def __init__(self, provider):
            self.provider = provider
            self.active = 0
            self.peak = 0
            self.calls = 0
            self.lock = threading.Lock()

        def transcribe(self, path, language=None):
            with self.lock:
                self.calls += 1
                first_call = self.calls == 1
                self.active += 1
                self.peak = max(self.peak, self.active)
            if first_call and not self.provider.fourth_download_started.wait(0.5):
                raise AssertionError("the next download did not start during the pipeline")
            time.sleep(0.02)
            with self.lock:
                self.active -= 1
            return super().transcribe(path, language)

    class StagedLLM(FakeLLM):
        def __init__(self):
            self.active = 0
            self.peak = 0

        async def enrich(self, title, text, language):
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return await super().enrich(title, text, language)

    async def scenario():
        provider = StagedProvider()
        stt = StagedSTT(provider)
        llm = StagedLLM()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            stt,
            llm,
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        runner = PipelineJobRunner(pipeline)
        ids = [
            await runner.submit(
                VideoItem("bilibili", source_id, source_id, f"https://{source_id.lower()}")
            )
            for source_id in ("A", "B", "C", "D")
        ]

        await runner.queue.join()

        assert provider.peak == 3
        assert stt.peak == 1
        assert 2 <= llm.peak <= 3
        assert all(repo.get_job(job_id)["status"] == "complete" for job_id in ids)
        runner._worker.cancel()

    asyncio.run(scenario())


def test_runner_serializes_duplicate_source_ids(tmp_path):
    async def scenario():
        provider = FakeProvider()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        runner = PipelineJobRunner(pipeline)
        item = VideoItem("bilibili", "SAME", "Same", "https://same")
        ids = [await runner.submit(item), await runner.submit(item)]

        await runner.queue.join()

        assert provider.download_count == 1
        assert all(repo.get_job(job_id)["status"] == "complete" for job_id in ids)
        runner._worker.cancel()

    asyncio.run(scenario())


def test_runner_pauses_active_job_at_safe_stage_boundary_and_resumes(tmp_path):
    async def scenario():
        provider = BlockingProvider()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        runner = PipelineJobRunner(pipeline)
        item = VideoItem("bilibili", "PAUSE", "Pause", "https://example.test/pause")

        job_id = await runner.submit(item)
        await provider.started.wait()
        paused = runner.pause(job_id)
        assert paused["status"] == "pausing"

        provider.release.set()
        await wait_for_job_status(repo, job_id, "paused")
        assert repo.get_job(job_id)["progress"] == 0.32

        resumed = runner.resume(job_id)
        assert resumed["status"] == "transcribing"
        await runner.queue.join()
        assert repo.get_job(job_id)["status"] == "complete"
        runner._worker.cancel()

    asyncio.run(scenario())


def test_runner_pauses_queued_job_without_blocking_other_job(tmp_path):
    async def scenario():
        provider = BlockingProvider()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        runner = PipelineJobRunner(pipeline)
        first = [
            await runner.submit(
                VideoItem(
                    "bilibili",
                    f"FIRST{index}",
                    f"First {index}",
                    f"https://example.test/first/{index}",
                )
            )
            for index in range(3)
        ]
        async with asyncio.timeout(1):
            while provider.started_count < 3:
                await asyncio.sleep(0.005)
        second = await runner.submit(
            VideoItem("bilibili", "SECOND", "Second", "https://example.test/second")
        )

        assert runner.pause(second)["status"] == "paused"
        provider.release.set()
        for job_id in first:
            await wait_for_job_status(repo, job_id, "complete")
        await wait_for_job_status(repo, second, "paused")
        assert provider.download_count == 3

        runner.resume(second)
        await runner.queue.join()
        assert repo.get_job(second)["status"] == "complete"
        assert provider.download_count == 4
        runner._worker.cancel()

    asyncio.run(scenario())


def test_runner_restarts_failed_job_with_original_options(tmp_path):
    async def scenario():
        provider = FailOnceProvider()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        runner = PipelineJobRunner(pipeline)
        item = VideoItem("bilibili", "RESTART", "Restart", "https://example.test/restart")

        job_id = await runner.submit(item, language="en-US", synthesize=True, force_refresh=True)
        await runner.queue.join()
        assert repo.get_job(job_id)["status"] == "failed"

        restarted = await runner.restart(job_id)
        assert restarted["id"] == job_id
        assert restarted["status"] == "queued"
        await runner.queue.join()

        completed = repo.get_job(job_id)
        assert completed["status"] == "complete"
        assert completed["language"] == "en-US"
        assert completed["synthesize"] is True
        assert completed["force_refresh"] is True
        assert "audio" in completed["outputs"]
        runner._worker.cancel()

    asyncio.run(scenario())


def test_runner_batch_restart_validates_every_job_before_requeueing(tmp_path):
    async def scenario():
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            FakeProvider(),
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        runner = PipelineJobRunner(pipeline)
        runner.start = lambda: None
        failed = repo.create_job(
            VideoItem("bilibili", "FAILED", "Failed", "https://example.test/failed")
        )
        completed = repo.create_job(
            VideoItem("bilibili", "DONE", "Done", "https://example.test/done")
        )
        repo.update_job(failed, "failed", 0.4, "failed")
        repo.update_job(completed, "complete", 1)

        try:
            await runner.restart_many([failed, completed])
        except ValueError:
            pass
        else:
            raise AssertionError("mixed-status batch should be rejected")

        assert repo.get_job(failed)["status"] == "failed"
        assert runner.queue.empty()

        repo.update_job(completed, "failed", 0.7, "failed")
        restarted = await runner.restart_many([failed, completed, failed])
        assert [job["id"] for job in restarted] == [failed, completed]
        assert all(job["status"] == "queued" for job in restarted)
        assert runner.queue.qsize() == 2

    asyncio.run(scenario())


def test_pipeline_reuses_cached_media_unless_forced(tmp_path):
    async def scenario():
        provider = FakeProvider()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        item = VideoItem("bilibili", "BV1CACHE", "Cached", "https://example.test/video")

        first_job = repo.create_job(item)
        await pipeline.run(first_job, item)
        second_job = repo.create_job(item)
        await pipeline.run(second_job, item)

        assert provider.download_count == 1
        assert repo.get_job(second_job)["message"] == (
            "Media, transcription, summary, and exports already complete"
        )
        assert Path(repo.get_job(second_job)["outputs"]["source_media"]).is_file()

        refresh_job = repo.create_job(item)
        await pipeline.run(refresh_job, item, force_refresh=True)

        assert provider.download_count == 2

    asyncio.run(scenario())


def test_pipeline_reuses_all_completed_outputs_unless_missing_or_forced(tmp_path):
    class CountingSTT(FakeSTT):
        def __init__(self):
            self.count = 0

        def transcribe(self, path, language=None):
            self.count += 1
            return super().transcribe(path, language)

    class CountingLLM(FakeLLM):
        def __init__(self):
            self.count = 0

        async def enrich(self, title, text, language):
            self.count += 1
            return await super().enrich(title, text, language)

    async def scenario():
        provider = FakeProvider()
        stt = CountingSTT()
        llm = CountingLLM()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            stt,
            llm,
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        item = VideoItem("bilibili", "BV1COMPLETE", "Complete", "https://example.test/video")

        first_job = repo.create_job(item)
        first_outputs = await pipeline.run(first_job, item)
        second_job = repo.create_job(item)
        second_outputs = await pipeline.run(second_job, item)

        assert second_outputs == first_outputs
        assert provider.download_count == 1
        assert stt.count == 1
        assert llm.count == 1
        assert repo.get_job(second_job)["message"] == (
            "Media, transcription, summary, and exports already complete"
        )

        # An incomplete bundle reuses the source download but rebuilds processing outputs.
        Path(first_outputs["lyrics"]).unlink()
        incomplete_job = repo.create_job(item)
        await pipeline.run(incomplete_job, item)
        assert provider.download_count == 1
        assert stt.count == 2
        assert llm.count == 2

        refresh_job = repo.create_job(item, force_refresh=True)
        await pipeline.run(refresh_job, item, force_refresh=True)
        assert provider.download_count == 2
        assert stt.count == 3
        assert llm.count == 3

    asyncio.run(scenario())


def test_pipeline_keeps_media_inside_each_video_bundle(tmp_path):
    async def scenario():
        provider = FakeProvider()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        first = VideoItem("bilibili", "BV1FIRST", "First", "https://example.test/first")
        second = VideoItem("bilibili", "BV1SECOND", "Second", "https://example.test/second")

        first_job = repo.create_job(first)
        first_outputs = await pipeline.run(first_job, first)
        second_job = repo.create_job(second)
        second_outputs = await pipeline.run(second_job, second)

        first_media = Path(first_outputs["source_media"])
        second_media = Path(second_outputs["source_media"])
        assert second_media != first_media
        assert first_media.is_file()
        assert second_media.is_file()
        assert first_media.parent.name == "assets"
        assert second_media.parent.name == "assets"
        assert first.source_id in first_media.name
        assert second.source_id in second_media.name

    asyncio.run(scenario())


def test_collection_outputs_use_author_and_collection_directory_hierarchy(tmp_path):
    async def scenario():
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            FakeProvider(),
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        item = VideoItem(
            "bilibili",
            "BV1COLLECTION",
            "Lesson",
            "https://example.test/video",
            "Creator",
            collection_id=9,
            collection_title="Course",
        )
        job_id = repo.create_job(item)

        return await pipeline.run(job_id, item, synthesize=True)

    outputs = asyncio.run(scenario())
    output_directory = (
        tmp_path / "library" / "Creator" / "Course" / "Creator_Course_Lesson_BV1COLLECTION"
    )

    assert output_directory.is_dir()
    assert outputs["audio"] == str(
        output_directory / "assets" / "Creator_Course_Lesson_BV1COLLECTION-tts.wav"
    )
    assert outputs["markdown"] == str(output_directory / "Creator_Course_Lesson_BV1COLLECTION.md")
    assert outputs["source_media"] == str(
        output_directory / "assets" / "Creator_Course_Lesson_BV1COLLECTION.wav"
    )


def test_pipeline_ignores_empty_cached_media(tmp_path):
    async def scenario():
        provider = FakeProvider()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "library",
        )
        item = VideoItem("bilibili", "BV1EMPTY", "Empty", "https://example.test/video")
        empty_cache = (
            tmp_path
            / "library"
            / "UnknownCreator"
            / "UnknownCreator_Empty_BV1EMPTY"
            / "assets"
            / "UnknownCreator_Empty_BV1EMPTY.m4a"
        )
        empty_cache.parent.mkdir(parents=True)
        empty_cache.touch()

        job_id = repo.create_job(item)
        await pipeline.run(job_id, item)

        assert provider.download_count == 1

    asyncio.run(scenario())
