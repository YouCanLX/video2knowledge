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
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              downloaded_at TEXT,
              language TEXT NOT NULL DEFAULT 'zh-CN',
              synthesize INTEGER NOT NULL DEFAULT 0,
              force_refresh INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS documents (
              source_id TEXT PRIMARY KEY, title TEXT NOT NULL, author TEXT NOT NULL,
              tags_json TEXT NOT NULL, is_charging INTEGER NOT NULL, markdown_path TEXT NOT NULL,
              audio_path TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS download_history (
              source_id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
              source_json TEXT NOT NULL, status TEXT NOT NULL,
              progress REAL NOT NULL DEFAULT 0, message TEXT NOT NULL DEFAULT '',
              outputs_json TEXT NOT NULL DEFAULT '{}',
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              downloaded_at TEXT
            );
            CREATE TABLE IF NOT EXISTS app_metadata (
              key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            """
        )
        columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
        if "downloaded_at" not in columns:
            self.connection.execute("ALTER TABLE jobs ADD COLUMN downloaded_at TEXT")
        if "language" not in columns:
            self.connection.execute(
                "ALTER TABLE jobs ADD COLUMN language TEXT NOT NULL DEFAULT 'zh-CN'"
            )
        if "synthesize" not in columns:
            self.connection.execute(
                "ALTER TABLE jobs ADD COLUMN synthesize INTEGER NOT NULL DEFAULT 0"
            )
        if "force_refresh" not in columns:
            self.connection.execute(
                "ALTER TABLE jobs ADD COLUMN force_refresh INTEGER NOT NULL DEFAULT 0"
            )
        history_migrated = self.connection.execute(
            "SELECT value FROM app_metadata WHERE key='download_history_v1'"
        ).fetchone()
        if not history_migrated:
            self.connection.execute(
                """INSERT OR IGNORE INTO download_history(
                     source_id, job_id, source_json, status, progress, message,
                     outputs_json, created_at, updated_at, downloaded_at
                   )
                   SELECT json_extract(source_json, '$.source_id'), id, source_json, status,
                          progress, message, outputs_json, created_at, updated_at, downloaded_at
                   FROM jobs"""
            )
            self.connection.execute(
                "INSERT INTO app_metadata(key, value) VALUES ('download_history_v1', 'complete')"
            )
        self.connection.commit()

    def create_job(
        self,
        item: VideoItem,
        language: str = "zh-CN",
        synthesize: bool = False,
        force_refresh: bool = False,
    ) -> str:
        job_id = uuid.uuid4().hex
        self.connection.execute(
            """INSERT INTO jobs(
                 id, source_json, status, language, synthesize, force_refresh
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                job_id,
                json.dumps(item.to_dict(), ensure_ascii=False),
                JobStatus.QUEUED,
                language,
                int(synthesize),
                int(force_refresh),
            ),
        )
        self.connection.execute(
            """INSERT INTO download_history(job_id, source_id, source_json, status)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(source_id) DO UPDATE SET
                 job_id=excluded.job_id, source_json=excluded.source_json,
                 status=excluded.status, progress=0, message='', outputs_json='{}',
                 created_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP,
                 downloaded_at=NULL""",
            (
                job_id,
                item.source_id,
                json.dumps(item.to_dict(), ensure_ascii=False),
                JobStatus.QUEUED,
            ),
        )
        self.connection.commit()
        return job_id

    def restart_job(self, job_id: str) -> bool:
        row = self.connection.execute(
            "SELECT source_json, downloaded_at FROM jobs WHERE id=?", (job_id,)
        ).fetchone()
        if not row:
            return False
        self.connection.execute(
            """UPDATE jobs
               SET status=?, progress=0, message='Restarted and queued', outputs_json='{}',
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (JobStatus.QUEUED, job_id),
        )
        self.connection.execute(
            """INSERT INTO download_history(
                 source_id, job_id, source_json, status, progress, message,
                 outputs_json, downloaded_at
               ) VALUES (json_extract(?, '$.source_id'), ?, ?, ?, 0, ?, '{}', ?)
               ON CONFLICT(source_id) DO UPDATE SET
                 job_id=excluded.job_id, source_json=excluded.source_json,
                 status=excluded.status, progress=0, message=excluded.message,
                 outputs_json='{}', updated_at=CURRENT_TIMESTAMP,
                 downloaded_at=excluded.downloaded_at""",
            (
                row["source_json"],
                job_id,
                row["source_json"],
                JobStatus.QUEUED,
                "Restarted and queued",
                row["downloaded_at"],
            ),
        )
        self.connection.commit()
        return True

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
        self.connection.execute(
            """UPDATE download_history
               SET status=?, progress=?, message=?, outputs_json=?,
                   updated_at=CURRENT_TIMESTAMP
               WHERE job_id=?""",
            (
                status,
                min(1, max(0, progress)),
                message,
                json.dumps(outputs or {}, ensure_ascii=False),
                job_id,
            ),
        )
        self.connection.commit()

    def mark_job_downloaded(self, job_id: str) -> None:
        self.connection.execute(
            """UPDATE jobs
               SET downloaded_at=COALESCE(downloaded_at, CURRENT_TIMESTAMP),
                   updated_at=CURRENT_TIMESTAMP
               WHERE id=?""",
            (job_id,),
        )
        self.connection.execute(
            """UPDATE download_history
               SET downloaded_at=COALESCE(downloaded_at, CURRENT_TIMESTAMP),
                   updated_at=CURRENT_TIMESTAMP
               WHERE job_id=?""",
            (job_id,),
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

    def get_download_history(self, source_id: str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT * FROM download_history WHERE source_id=?", (source_id,)
        ).fetchone()
        return self._history_dict(row) if row else None

    def list_download_history(self, limit: int = 5000) -> list[dict[str, Any]]:
        rows = self.connection.execute(
            "SELECT * FROM download_history ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._history_dict(row) for row in rows]

    def delete_download_history(self, source_id: str) -> bool:
        cursor = self.connection.execute(
            "DELETE FROM download_history WHERE source_id=?", (source_id,)
        )
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
        data["synthesize"] = bool(data["synthesize"])
        data["force_refresh"] = bool(data["force_refresh"])
        return data

    @staticmethod
    def _history_dict(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        data["source"] = json.loads(data.pop("source_json"))
        data["outputs"] = json.loads(data.pop("outputs_json"))
        return data
