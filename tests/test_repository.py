import sqlite3

from video2knowledge.models import JobStatus, VideoItem
from video2knowledge.repository import LibraryRepository


def test_job_and_document_round_trip(tmp_path):
    repo = LibraryRepository(tmp_path / "data.db")
    item = VideoItem(
        "bilibili",
        "BV1",
        "Title",
        "https://example.test",
        "Author",
        tags=["Knowledge"],
        is_charging=True,
    )
    job_id = repo.create_job(item)
    history = repo.get_download_history("BV1")
    assert history["job_id"] == job_id
    assert history["status"] == "queued"
    assert repo.get_job(job_id)["downloaded_at"] is None
    repo.mark_job_downloaded(job_id)
    repo.update_job(job_id, JobStatus.TRANSCRIBING, 0.5, "working")
    job = repo.get_job(job_id)
    assert job["status"] == "transcribing"
    assert job["downloaded_at"]
    assert job["source"]["source_id"] == "BV1"
    assert repo.get_download_history("BV1")["status"] == "transcribing"
    repo.save_document(item, {"markdown": "/tmp/BV1.md"})
    assert repo.list_documents(tag="Knowledge", charging=True)[0]["title"] == "Title"
    assert repo.delete_document("BV1") is True
    assert repo.list_documents() == []
    assert repo.delete_job(job_id) is True
    assert repo.get_job(job_id) is None
    assert repo.get_download_history("BV1") is not None
    assert repo.delete_download_history("BV1") is True
    assert repo.list_download_history() == []

    reopened = LibraryRepository(tmp_path / "data.db")
    assert reopened.list_download_history() == []


def test_job_restart_parameters_are_persisted_and_history_is_restored(tmp_path):
    repo = LibraryRepository(tmp_path / "data.db")
    item = VideoItem("bilibili", "BVRETRY", "Retry", "https://example.test/retry")
    job_id = repo.create_job(item, "en-US", synthesize=True, force_refresh=True)
    repo.update_job(job_id, JobStatus.FAILED, 1, "temporary error")
    repo.delete_download_history(item.source_id)

    stored = repo.get_job(job_id)
    assert stored["language"] == "en-US"
    assert stored["synthesize"] is True
    assert stored["force_refresh"] is True
    assert repo.restart_job(job_id) is True

    restarted = repo.get_job(job_id)
    assert restarted["status"] == "queued"
    assert restarted["progress"] == 0
    assert restarted["outputs"] == {}
    assert repo.get_download_history(item.source_id)["job_id"] == job_id


def test_existing_jobs_database_gains_restart_parameter_columns(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """CREATE TABLE jobs (
             id TEXT PRIMARY KEY, source_json TEXT NOT NULL, status TEXT NOT NULL,
             progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
             outputs_json TEXT NOT NULL DEFAULT '{}',
             created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
             updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
             downloaded_at TEXT
           )"""
    )
    connection.commit()
    connection.close()

    repo = LibraryRepository(database)
    columns = {
        row["name"] for row in repo.connection.execute("PRAGMA table_info(jobs)").fetchall()
    }

    assert {"language", "synthesize", "force_refresh"}.issubset(columns)
