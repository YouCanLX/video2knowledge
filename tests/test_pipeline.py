import asyncio

from video2knowledge.models import Enrichment, TranscriptSegment, VideoItem
from video2knowledge.pipeline import Pipeline, SerialJobRunner
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


def test_serial_runner_never_downloads_concurrently(tmp_path):
    async def scenario():
        provider = FakeProvider()
        repo = LibraryRepository(tmp_path / "db.sqlite")
        pipeline = Pipeline(
            provider,
            FakeSTT(),
            FakeLLM(),
            FakeTTS(),
            repo,
            tmp_path / "media",
            tmp_path / "library",
        )
        runner = SerialJobRunner(pipeline)
        a = VideoItem("bilibili", "A", "A", "https://a")
        b = VideoItem("bilibili", "B", "B", "https://b")
        ids = [await runner.submit(a), await runner.submit(b)]
        await runner.queue.join()
        assert provider.peak == 1
        assert all(repo.get_job(job_id)["status"] == "complete" for job_id in ids)
        assert (tmp_path / "library" / "UnknownCreator_A_A" / "UnknownCreator_A_A.md").exists()
        runner._worker.cancel()

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
            tmp_path / "media",
            tmp_path / "library",
        )
        item = VideoItem("bilibili", "BV1CACHE", "Cached", "https://example.test/video")

        first_job = repo.create_job(item)
        await pipeline.run(first_job, item)
        second_job = repo.create_job(item)
        await pipeline.run(second_job, item)

        assert provider.download_count == 1
        assert repo.get_job(second_job)["message"] == "Processing complete"
        assert repo.get_job(second_job)["outputs"]["source_media"].endswith("audio.wav")

        refresh_job = repo.create_job(item)
        await pipeline.run(refresh_job, item, force_refresh=True)

        assert provider.download_count == 2

    asyncio.run(scenario())


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
            tmp_path / "media",
            tmp_path / "library",
        )
        item = VideoItem("bilibili", "BV1EMPTY", "Empty", "https://example.test/video")
        empty_cache = tmp_path / "media" / "BV1EMPTY" / "audio.m4a"
        empty_cache.parent.mkdir(parents=True)
        empty_cache.touch()

        job_id = repo.create_job(item)
        await pipeline.run(job_id, item)

        assert provider.download_count == 1

    asyncio.run(scenario())
