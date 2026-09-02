from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from pathlib import Path
from typing import Any

from .models import JobStatus, VideoItem


class LibraryRepository:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._local = threading.local()
        self.initialize()

    @property
    def connection(self) -> sqlite3.Connection:
        connection = getattr(self._local, "connection", None)
        if connection is None:
            connection = sqlite3.connect(self.path)
            connection.row_factory = sqlite3.Row
            self._local.connection = connection
        return connection

    def initialize(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
              id TEXT PRIMARY KEY, source_json TEXT NOT NULL, status TEXT NOT NULL,
              progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
              outputs_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS documents (
              source_id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL,
              tags_json TEXT NOT NULL, is_charging INTEGER NOT NULL, markdown_path TEXT NOT NULL,
              audio_path TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        self.connection.commit()

    def create_job(self, item: VideoItem) -> str:
        job_id = uuid.uuid4().hex
        self.connection.execute(
            "INSERT INTO jobs(id, source_json, status) VALUES (?, ?, ?)",
            (job_id, json.dumps(item.to_dict(), ensure_ascii=False), JobStatus.QUEUED),
        )
        self.connection.commit()
        return job_id

    def update_job(
        self,
        job_id: str,
        status: JobStatus,
        progress: float,
        message: str = "",
        outputs: dict[str, str] | None = None,
    ) -> None:
        self.connection.execute(
            """UPDATE jobs
               SET status=?, progress=?, message=?, outputs_json=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (
                status,
                min(1, max(0, progress)),
                message,
                json.dumps(outputs or {}, ensure_ascii=False),
                job_id,
            ),
        )
        self.connection.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        row = self.connection.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return self._job_dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._job_dict(row) for row in rows]

    def delete_job(self, job_id: str) -> bool:
        cursor = self.connection.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        self.connection.commit()
        return cursor.rowcount > 0

    def save_document(
        self, item: VideoItem, outputs: dict[str, str], audio_path: str | None = None
    ) -> None:
        self.connection.execute(
            """INSERT INTO documents(
                 source_id,title,author,tags_json,is_charging,markdown_path,audio_path
               )
               VALUES(?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET
               title=excluded.title,author=excluded.author,tags_json=excluded.tags_json,
               is_charging=excluded.is_charging,markdown_path=excluded.markdown_path,audio_path=excluded.audio_path""",
            (
                item.source_id,
                item.title,
                item.author,
                json.dumps(item.tags, ensure_ascii=False),
                int(item.is_charging),
                outputs["markdown"],
                audio_path,
            ),
        )
        self.connection.commit()

    def list_documents(
        self, query: str = "", tag: str = "", charging: bool | None = None
    ) -> list[dict[str, Any]]:
        sql, params = (
            "SELECT * FROM documents WHERE (title LIKE ? OR author LIKE ?)",
            [f"%{query}%", f"%{query}%"],
        )
        if tag:
            sql += " AND tags_json LIKE ?"
            params.append(f"%{tag}%")
        if charging is not None:
            sql += " AND is_charging=?"
            params.append(int(charging))
        sql += " ORDER BY created_at DESC"
        rows = self.connection.execute(sql, params).fetchall()
        return [{**dict(row), "tags": json.loads(row["tags_json"])} for row in rows]

    def delete_document(self, source_id: str) -> bool:
        cursor = self.connection.execute("DELETE FROM documents WHERE source_id=?", (source_id,))
        self.connection.commit()
        return cursor.rowcount > 0

    @staticmethod
    def _job_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["source"] = json.loads(data.pop("source_json"))
        data["outputs"] = json.loads(data.pop("outputs_json"))
        return data
