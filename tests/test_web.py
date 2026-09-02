import asyncio

import httpx
import pytest

from video2knowledge.config import Settings
from video2knowledge.models import JobStatus, VideoItem
from video2knowledge.urls import extract_bilibili_bvid
from video2knowledge.web import create_app


def test_extract_bilibili_bvid_from_video_url():
    assert extract_bilibili_bvid("https://www.bilibili.com/video/BV1muzGBGEee") == "BV1muzGBGEee"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/video/BV1muzGBGEee",
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
    assert stylesheet.status_code == 200
    assert script.status_code == 200


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
