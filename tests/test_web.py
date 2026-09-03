import asyncio

import httpx
import pytest

import video2knowledge.web as web_module
from video2knowledge.config import Settings
from video2knowledge.models import JobStatus, VideoItem
from video2knowledge.urls import extract_bilibili_bvid, extract_bilibili_creator_id
from video2knowledge.web import (
    CollectionSelection,
    CreatorBatchRequest,
    _expand_creator_batch,
    create_app,
)


def test_extract_bilibili_bvid_from_video_url():
    assert extract_bilibili_bvid("https://www.bilibili.com/video/BV1T64y1Z7WJ") == "BV1T64y1Z7WJ"


@pytest.mark.parametrize(
    "url",
    [
        "https://space.bilibili.com/37090048",
        "https://space.bilibili.com/37090048/lists",
        "https://space.bilibili.com/37090048/upload/video",
    ],
)
def test_extract_bilibili_creator_id(url):
    assert extract_bilibili_creator_id(url) == 37090048


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/BV1T64y1Z7WJ",
        "https://www.bilibili.com/video/not-a-bvid",
        "javascript:alert(1)",
    ],
)
def test_extract_bilibili_bvid_rejects_invalid_urls(url):
    with pytest.raises(ValueError):
        extract_bilibili_bvid(url)


def test_web_app_serves_template_and_static_assets(tmp_path):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await asyncio.gather(
                client.get("/"),
                client.get("/static/app.css"),
                client.get("/static/app.js"),
            )

    page, stylesheet, script = asyncio.run(scenario())

    assert page.status_code == 200
    assert "Video2Knowledge" in page.text
    assert 'id="force-refresh"' in page.text
    assert 'id="creator-form"' in page.text
    assert 'id="add-videos-tab"' in page.text
    assert 'id="download-history-tab"' in page.text
    assert 'id="add-videos-page"' in page.text
    assert 'id="download-history-page"' in page.text
    assert 'id="download-history-page" role="tabpanel"' in page.text
    assert 'aria-labelledby="download-history-tab" hidden' in page.text
    assert 'id="download-history-toggle"' in page.text
    assert 'aria-controls="download-history-content"' in page.text
    assert 'id="queue-toggle"' in page.text
    assert 'aria-controls="queue-content"' in page.text
    assert 'id="queue-summary"' in page.text
    assert 'id="queue-creator-filter"' in page.text
    assert 'id="queue-collection-filter"' in page.text
    assert 'id="queue-status-filter"' in page.text
    assert '<option value="paused">Paused</option>' in page.text
    assert 'id="queue-year-filter"' in page.text
    assert 'id="queue-month-filter"' in page.text
    assert 'id="queue-day-filter"' in page.text
    assert 'id="expand-all-jobs"' in page.text
    assert 'id="collapse-all-jobs"' in page.text
    assert 'id="select-visible-jobs"' in page.text
    assert 'id="delete-selected-jobs"' in page.text
    assert 'id="settings-toggle"' in page.text
    assert 'aria-controls="settings-content"' in page.text
    assert 'id="settings-content" hidden' in page.text
    assert 'id="request-progress-stack"' in page.text
    assert 'id="download-history-list"' in page.text
    assert 'id="refresh-download-history"' in page.text
    assert 'href="../static/app.css"' in page.text
    assert 'id="preview-warning"' in page.text
    assert stylesheet.status_code == 200
    assert script.status_code == 200
    assert "Open File" in script.text
    assert "Show in Finder" in script.text
    assert "data-quick-delete-job" in script.text
    assert "data-copy-job-link" in script.text
    assert "data-pause-job" in script.text
    assert "data-resume-job" in script.text
    assert "data-restart-job" in script.text
    assert "`/api/jobs/${encodeURIComponent(jobId)}/${action}`" in script.text
    assert 'target="_blank" rel="noopener noreferrer"' in script.text
    assert 'navigator.clipboard.writeText(url)' in script.text
    assert '"/api/jobs/batch-delete"' in script.text
    assert 'requestJson("/api/jobs?limit=5000")' in script.text
    assert 'filter === "running"' in script.text
    assert "trackRequestJobs(progressRequestId, data.job_ids, requestLabel)" in script.text
    assert "renderRequestProgress(data)" in script.text
    assert "REQUEST_IDLE_TIMEOUT_MS = 60 * 60 * 1000" in script.text
    assert 'requestJson("/api/download-history?limit=5000")' in script.text
    assert 'addEventListener("mouseenter", expand)' in script.text
    assert 'fileList.matches(":hover")' in script.text
    assert 'data-batch-scope="all-collections"' in script.text
    assert "data-more-collections" in script.text
    assert "activateAppTab" in script.text
    assert "expandedQueueDates" in script.text
    assert "data-queue-date" in script.text
    assert "jobsByDate" in script.text
    assert 'window.location.protocol === "file:"' in script.text
    assert page.text.index('id="download-history-list"') < page.text.index('id="queue-toggle"')


def test_bilibili_image_proxy_rejects_non_bilibili_hosts(tmp_path):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get(
                "/api/bilibili/image", params={"url": "https://example.com/image.jpg"}
            )

    response = asyncio.run(scenario())

    assert response.status_code == 422


def test_creator_batch_expands_pages_and_removes_duplicate_videos():
    class FakeCreatorProvider:
        async def get_creator_collections(self, creator_id, page, page_size):
            items = (
                [{"kind": "season", "id": 10, "title": "Trading course"}]
                if page == 1
                else []
            )
            return {"items": items, "has_more": False}

        async def get_collection_videos(self, creator_id, kind, collection_id, page, page_size):
            rows = {
                1: [video("BV1T64y1Z7WJ", "First"), video("BV1rP4y117ap", "Second")],
                2: [video("BV1rP4y117ap", "Second")],
            }
            return {"items": rows.get(page, []), "has_more": page == 1}

        async def get_creator(self, creator_id):
            return {"id": creator_id, "name": "Creator"}

    def video(source_id, title):
        return VideoItem(
            "bilibili", source_id, title, f"https://example.test/{source_id}"
        ).to_dict()

    body = CreatorBatchRequest(
        creator_id=37090048,
        all_collections=True,
        videos=[
            VideoItem(
                "bilibili",
                "BV1T64y1Z7WJ",
                "Chosen",
                "https://www.bilibili.com/video/BV1T64y1Z7WJ",
            )
        ],
    )
    expanded = asyncio.run(_expand_creator_batch(FakeCreatorProvider(), body))

    assert {item.source_id for item in expanded} == {
        "BV1T64y1Z7WJ",
        "BV1rP4y117ap",
    }
    assert all(item.author == "Creator" for item in expanded)
    assert all(item.collection_title == "Trading course" for item in expanded)


def test_creator_batch_excludes_deselected_collection_video():
    class FakeCreatorProvider:
        async def get_collection_videos(self, creator_id, kind, collection_id, page, page_size):
            return {
                "items": [video("BV1T64y1Z7WJ", "First"), video("BV1rP4y117ap", "Second")],
                "has_more": False,
            }

        async def get_creator(self, creator_id):
            return {"id": creator_id, "name": "Creator"}

    def video(source_id, title):
        return VideoItem(
            "bilibili", source_id, title, f"https://example.test/{source_id}"
        ).to_dict()

    body = CreatorBatchRequest(
        creator_id=37090048,
        collections=[
            CollectionSelection(
                kind="season", id=10, excluded_video_ids=["BV1T64y1Z7WJ"]
            )
        ],
    )
    expanded = asyncio.run(_expand_creator_batch(FakeCreatorProvider(), body))

    assert [item.source_id for item in expanded] == ["BV1rP4y117ap"]


def test_runtime_settings_are_exposed_and_persisted(tmp_path):
    async def scenario():
        settings = Settings.load(tmp_path)
        app = create_app(settings)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            initial = await client.get("/api/settings")
            payload = initial.json()
            payload.update(
                {
                    "media_dir": "custom-downloads",
                    "library_dir": "custom-library",
                    "mlx_audio_command": "python -m mlx_audio.server --port 9000",
                    "mlx_base_url": "http://127.0.0.1:9000",
                    "llm_backend": "openai_compatible",
                    "llm_base_url": "http://127.0.0.1:11434/v1",
                    "llm_model": "local-model",
                }
            )
            updated = await client.put("/api/settings", json=payload)
        return initial, updated, settings

    initial, updated, settings = asyncio.run(scenario())

    assert initial.status_code == 200
    assert initial.json()["llm_backend"] == "codex_cli"
    assert initial.json()["media_dir"] == "media"
    assert initial.json()["library_dir"] == "library"
    assert updated.status_code == 200
    assert updated.json()["media_dir"] == "custom-downloads"
    assert updated.json()["library_dir"] == "custom-library"
    assert settings.media_dir == (tmp_path / "custom-downloads").resolve()
    assert settings.library_dir == (tmp_path / "custom-library").resolve()
    assert Settings.load(tmp_path).llm_backend == "openai_compatible"


def test_mlx_status_and_invalid_start_command(tmp_path, monkeypatch):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        manager = app.state.mlx_manager
        monkeypatch.setattr(manager, "_is_reachable", _unreachable)
        manager.configure("definitely-missing-v2k-executable", manager.base_url)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/mlx/status"), await client.post("/api/mlx/start")

    async def _unreachable():
        return False

    status, start = asyncio.run(scenario())

    assert status.status_code == 200
    assert status.json()["state"] == "stopped"
    assert start.status_code == 400
    assert "executable was not found" in start.json()["detail"]


def test_delete_job_record_keeps_files(tmp_path):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        repo = app.state.services.repository
        item = VideoItem("bilibili", "BV1KEEP", "Keep", "https://example.test")
        output = tmp_path / "library" / "BV1KEEP.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("keep", encoding="utf-8")
        job_id = repo.create_job(item)
        repo.update_job(job_id, JobStatus.COMPLETE, 1, outputs={"markdown": str(output)})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/jobs/{job_id}")
        return response, repo, job_id, output

    response, repo, job_id, output = asyncio.run(scenario())

    assert response.status_code == 200
    assert repo.get_job(job_id) is None
    assert output.exists()


def test_delete_job_with_local_files_and_document(tmp_path):
    async def scenario():
        settings = Settings.load(tmp_path)
        app = create_app(settings)
        repo = app.state.services.repository
        item = VideoItem("bilibili", "BV1DELETE", "Delete", "https://example.test")
        output_dir = settings.library_dir / "Author_Delete_BV1DELETE"
        output_dir.mkdir(parents=True)
        markdown = output_dir / "Author_Delete_BV1DELETE.md"
        markdown.write_text("delete", encoding="utf-8")
        media = settings.media_dir / "Author" / "Delete_BV1DELETE.m4a"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"media")
        job_id = repo.create_job(item)
        outputs = {"markdown": str(markdown), "source_media": str(media)}
        repo.update_job(job_id, JobStatus.COMPLETE, 1, outputs=outputs)
        repo.save_document(item, outputs)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(f"/api/jobs/{job_id}?delete_files=true")
        return response, repo, job_id, markdown, media

    response, repo, job_id, markdown, media = asyncio.run(scenario())

    assert response.status_code == 200
    assert set(response.json()["removed_files"]) == {str(markdown), str(media)}
    assert repo.get_job(job_id) is None
    assert repo.list_documents() == []
    assert not markdown.exists()
    assert not media.exists()


def test_active_job_cannot_be_deleted(tmp_path):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        repo = app.state.services.repository
        item = VideoItem("bilibili", "BV1ACTIVE", "Active", "https://example.test")
        job_id = repo.create_job(item)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.delete(f"/api/jobs/{job_id}")

    response = asyncio.run(scenario())

    assert response.status_code == 409


def test_queued_job_can_be_paused_and_resumed_through_api(tmp_path, monkeypatch):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        runner = app.state.runner
        monkeypatch.setattr(runner, "start", lambda: None)
        job_id = await runner.submit(
            VideoItem("bilibili", "BV1PAUSE", "Pause", "https://example.test/pause")
        )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            paused = await client.post(f"/api/jobs/{job_id}/pause")
            resumed = await client.post(f"/api/jobs/{job_id}/resume")
            invalid = await client.post(f"/api/jobs/{job_id}/resume")
            missing = await client.post("/api/jobs/missing/pause")
        return paused, resumed, invalid, missing

    paused, resumed, invalid, missing = asyncio.run(scenario())

    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "queued"
    assert invalid.status_code == 409
    assert missing.status_code == 404


def test_failed_job_can_be_restarted_through_api(tmp_path, monkeypatch):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        runner = app.state.runner
        monkeypatch.setattr(runner, "start", lambda: None)
        item = VideoItem("bilibili", "BV1RESTART", "Restart", "https://example.test/restart")
        job_id = runner.pipeline.repository.create_job(
            item, "en-US", synthesize=True, force_refresh=True
        )
        runner.pipeline.repository.update_job(job_id, JobStatus.FAILED, 1, "failed")
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            restarted = await client.post(f"/api/jobs/{job_id}/restart")
            invalid = await client.post(f"/api/jobs/{job_id}/restart")
            missing = await client.post("/api/jobs/missing/restart")
        return restarted, invalid, missing

    restarted, invalid, missing = asyncio.run(scenario())

    assert restarted.status_code == 202
    assert restarted.json()["status"] == "queued"
    assert restarted.json()["language"] == "en-US"
    assert restarted.json()["synthesize"] is True
    assert restarted.json()["force_refresh"] is True
    assert invalid.status_code == 409
    assert missing.status_code == 404


def test_failed_jobs_can_be_batch_restarted_through_api(tmp_path, monkeypatch):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        runner = app.state.runner
        repo = runner.pipeline.repository
        monkeypatch.setattr(runner, "start", lambda: None)
        failed_ids = []
        for index in range(2):
            job_id = repo.create_job(
                VideoItem(
                    "bilibili",
                    f"BV1BATCH{index}",
                    f"Failed {index}",
                    f"https://example.test/failed-{index}",
                )
            )
            repo.update_job(job_id, JobStatus.FAILED, 0.5, "failed")
            failed_ids.append(job_id)

        completed = repo.create_job(
            VideoItem("bilibili", "BV1DONE", "Done", "https://example.test/done")
        )
        repo.update_job(completed, JobStatus.COMPLETE, 1)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            restarted = await client.post(
                "/api/jobs/batch-restart",
                json={"job_ids": [failed_ids[0], failed_ids[1], failed_ids[0]]},
            )

            atomic_failed = repo.create_job(
                VideoItem(
                    "bilibili",
                    "BV1ATOMIC",
                    "Atomic",
                    "https://example.test/atomic",
                )
            )
            repo.update_job(atomic_failed, JobStatus.FAILED, 0.5, "failed")
            invalid = await client.post(
                "/api/jobs/batch-restart",
                json={"job_ids": [atomic_failed, completed]},
            )
        return restarted, invalid, repo, failed_ids, atomic_failed

    restarted, invalid, repo, failed_ids, atomic_failed = asyncio.run(scenario())

    assert restarted.status_code == 202
    assert restarted.json() == {"restarted": failed_ids, "count": 2}
    assert all(repo.get_job(job_id)["status"] == "queued" for job_id in failed_ids)
    assert invalid.status_code == 409
    assert repo.get_job(atomic_failed)["status"] == "failed"


def test_batch_delete_completed_and_failed_jobs(tmp_path):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        repo = app.state.services.repository
        completed = repo.create_job(
            VideoItem("bilibili", "BV1BATCH1", "One", "https://example.test/1")
        )
        failed = repo.create_job(
            VideoItem("bilibili", "BV1BATCH2", "Two", "https://example.test/2")
        )
        repo.update_job(completed, JobStatus.COMPLETE, 1)
        repo.update_job(failed, JobStatus.FAILED, 0.5)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/jobs/batch-delete", json={"job_ids": [completed, failed, completed]}
            )
        return response, repo, completed, failed

    response, repo, completed, failed = asyncio.run(scenario())

    assert response.status_code == 200
    assert response.json()["count"] == 2
    assert response.json()["deleted"] == [completed, failed]
    assert repo.get_job(completed) is None
    assert repo.get_job(failed) is None


def test_batch_delete_is_atomic_when_selection_contains_active_job(tmp_path):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        repo = app.state.services.repository
        completed = repo.create_job(
            VideoItem("bilibili", "BV1DONE", "Done", "https://example.test/done")
        )
        active = repo.create_job(
            VideoItem("bilibili", "BV1LIVE", "Live", "https://example.test/live")
        )
        repo.update_job(completed, JobStatus.COMPLETE, 1)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/jobs/batch-delete", json={"job_ids": [completed, active]}
            )
        return response, repo, completed

    response, repo, completed = asyncio.run(scenario())

    assert response.status_code == 409
    assert repo.get_job(completed) is not None


def test_download_history_is_independent_and_can_delete_local_files(tmp_path):
    async def scenario():
        settings = Settings.load(tmp_path)
        app = create_app(settings)
        repo = app.state.services.repository
        item = VideoItem(
            "bilibili",
            "BV1HISTORY",
            "History",
            "https://example.test/history",
            "Creator",
            collection_id=7,
            collection_title="Course",
        )
        output = settings.library_dir / "Creator" / "Course" / "BV1HISTORY.md"
        output.parent.mkdir(parents=True)
        output.write_text("content", encoding="utf-8")
        job_id = repo.create_job(item)
        repo.update_job(job_id, JobStatus.COMPLETE, 1, outputs={"markdown": str(output)})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            listed = await client.get("/api/download-history")
            deleted = await client.post(
                "/api/download-history/batch-delete",
                json={"source_ids": [item.source_id], "delete_files": True},
            )
        return listed, deleted, repo, job_id, output

    listed, deleted, repo, job_id, output = asyncio.run(scenario())

    assert listed.status_code == 200
    assert listed.json()[0]["source"]["collection_title"] == "Course"
    assert deleted.status_code == 200
    assert deleted.json()["removed_files"] == [str(output)]
    assert repo.get_download_history("BV1HISTORY") is None
    assert repo.get_job(job_id) is not None
    assert not output.exists()


def test_active_download_history_can_be_removed_but_its_files_cannot(tmp_path):
    async def scenario():
        app = create_app(Settings.load(tmp_path))
        repo = app.state.services.repository
        item = VideoItem("bilibili", "BV1ACTIVEHISTORY", "Active", "https://example.test")
        repo.create_job(item)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            blocked = await client.post(
                "/api/download-history/batch-delete",
                json={"source_ids": [item.source_id], "delete_files": True},
            )
            record_only = await client.post(
                "/api/download-history/batch-delete",
                json={"source_ids": [item.source_id], "delete_files": False},
            )
        return blocked, record_only

    blocked, record_only = asyncio.run(scenario())

    assert blocked.status_code == 409
    assert record_only.status_code == 200


def test_completed_job_output_can_be_opened_or_revealed(tmp_path, monkeypatch):
    actions = []

    async def fake_open(path, reveal):
        actions.append((path, reveal))

    monkeypatch.setattr(web_module, "_open_local_path", fake_open)

    async def scenario():
        app = create_app(Settings.load(tmp_path))
        repo = app.state.services.repository
        item = VideoItem("bilibili", "BV1OPEN", "Open", "https://example.test")
        output = tmp_path / "library" / "Open_BV1OPEN.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("content", encoding="utf-8")
        job_id = repo.create_job(item)
        repo.update_job(job_id, JobStatus.COMPLETE, 1, outputs={"markdown": str(output)})
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            opened = await client.post(f"/api/jobs/{job_id}/outputs/markdown/open")
            revealed = await client.post(f"/api/jobs/{job_id}/outputs/markdown/reveal")
            missing = await client.post(f"/api/jobs/{job_id}/outputs/audio/open")
        return opened, revealed, missing, output

    opened, revealed, missing, output = asyncio.run(scenario())

    assert opened.status_code == 200
    assert revealed.status_code == 200
    assert missing.status_code == 404
    assert actions == [(output, False), (output, True)]
