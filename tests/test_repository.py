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
    assert repo.get_job(job_id)["downloaded_at"] is None
    repo.mark_job_downloaded(job_id)
    repo.update_job(job_id, JobStatus.TRANSCRIBING, 0.5, "working")
    job = repo.get_job(job_id)
    assert job["status"] == "transcribing"
    assert job["downloaded_at"]
    assert job["source"]["source_id"] == "BV1"
    repo.save_document(item, {"markdown": "/tmp/BV1.md"})
    assert repo.list_documents(tag="Knowledge", charging=True)[0]["title"] == "Title"
    assert repo.delete_document("BV1") is True
    assert repo.list_documents() == []
    assert repo.delete_job(job_id) is True
    assert repo.get_job(job_id) is None
