from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from .config import settings
from .models import Question, Upload, UploadState, UploadSummary

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
  id TEXT PRIMARY KEY,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  state TEXT NOT NULL,
  error_message TEXT,
  raw_notebooklm_response TEXT
);

CREATE TABLE IF NOT EXISTS questions (
  id TEXT PRIMARY KEY,
  upload_id TEXT NOT NULL REFERENCES uploads(id),
  number INTEGER NOT NULL,
  type TEXT NOT NULL,
  stem TEXT NOT NULL,
  options_json TEXT,
  correct_answer_json TEXT,
  reasoning TEXT,
  confidence TEXT,
  flagged INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_questions_upload ON questions(upload_id);
CREATE INDEX IF NOT EXISTS idx_uploads_created ON uploads(created_at DESC);
"""

HISTORY_CAP = 50


def _db_path() -> str:
    return settings.db_path


async def init_db() -> None:
    Path(_db_path()).parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


async def health_check() -> bool:
    try:
        Path(_db_path()).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(_db_path()) as conn:
            await conn.execute("CREATE TEMP TABLE IF NOT EXISTS healthcheck (ok INTEGER)")
            await conn.execute("DELETE FROM healthcheck")
            await conn.execute("INSERT INTO healthcheck (ok) VALUES (1)")
            async with conn.execute("SELECT ok FROM healthcheck LIMIT 1") as cur:
                row = await cur.fetchone()
            await conn.commit()
        return bool(row and row[0] == 1)
    except Exception:
        logger.exception("SQLite health check failed")
        return False


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace(" ", "T"))


def _row_to_question(row: aiosqlite.Row) -> Question:
    options = json.loads(row["options_json"]) if row["options_json"] else None
    correct = json.loads(row["correct_answer_json"]) if row["correct_answer_json"] else None
    return Question(
        id=row["id"],
        upload_id=row["upload_id"],
        number=row["number"],
        type=row["type"],
        stem=row["stem"],
        options=options,
        correct_answer=correct,
        reasoning=row["reasoning"],
        confidence=row["confidence"],
        flagged=bool(row["flagged"]),
    )


async def create_upload(state: UploadState = "extracting") -> str:
    upload_id = str(uuid.uuid4())
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            "INSERT INTO uploads (id, state) VALUES (?, ?)",
            (upload_id, state),
        )
        await conn.commit()
    return upload_id


async def update_state(
    upload_id: str,
    state: UploadState,
    *,
    error_message: str | None = None,
    raw_notebooklm_response: str | None = None,
) -> None:
    sets = ["state = ?"]
    args: list[Any] = [state]
    if error_message is not None:
        sets.append("error_message = ?")
        args.append(error_message)
    if raw_notebooklm_response is not None:
        sets.append("raw_notebooklm_response = ?")
        args.append(raw_notebooklm_response)
    args.append(upload_id)
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(f"UPDATE uploads SET {', '.join(sets)} WHERE id = ?", args)
        await conn.commit()


async def insert_questions(
    upload_id: str,
    questions: list[dict[str, Any]],
) -> list[str]:
    """Insert extracted questions. Each dict needs: number, type, stem, options (optional)."""
    ids: list[str] = []
    async with aiosqlite.connect(_db_path()) as conn:
        for q in questions:
            qid = str(uuid.uuid4())
            ids.append(qid)
            await conn.execute(
                """
                INSERT INTO questions
                  (id, upload_id, number, type, stem, options_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    qid,
                    upload_id,
                    q["number"],
                    q["type"],
                    q["stem"],
                    json.dumps(q["options"]) if q.get("options") else None,
                ),
            )
        await conn.commit()
    return ids


async def update_question_answer(
    question_id: str,
    *,
    correct_answer: str | list[str] | None,
    reasoning: str | None,
    confidence: str | None,
    flagged: bool = False,
) -> None:
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            UPDATE questions
               SET correct_answer_json = ?,
                   reasoning = ?,
                   confidence = ?,
                   flagged = ?
             WHERE id = ?
            """,
            (
                json.dumps(correct_answer) if correct_answer is not None else None,
                reasoning,
                confidence,
                1 if flagged else 0,
                question_id,
            ),
        )
        await conn.commit()


async def list_uploads(limit: int = HISTORY_CAP) -> list[UploadSummary]:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            """
            SELECT u.id, u.created_at, u.state,
                   (SELECT COUNT(*) FROM questions q WHERE q.upload_id = u.id) AS qc
              FROM uploads u
             ORDER BY u.created_at DESC
             LIMIT ?
            """,
            (limit,),
        ) as cur:
            rows = await cur.fetchall()
    return [
        UploadSummary(
            id=r["id"],
            created_at=_parse_dt(r["created_at"]),
            state=r["state"],
            question_count=r["qc"],
        )
        for r in rows
    ]


async def get_upload_full(upload_id: str) -> Upload | None:
    async with aiosqlite.connect(_db_path()) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT * FROM uploads WHERE id = ?", (upload_id,)
        ) as cur:
            urow = await cur.fetchone()
        if urow is None:
            return None
        async with conn.execute(
            "SELECT * FROM questions WHERE upload_id = ? ORDER BY number ASC",
            (upload_id,),
        ) as cur:
            qrows = await cur.fetchall()
    return Upload(
        id=urow["id"],
        created_at=_parse_dt(urow["created_at"]),
        state=urow["state"],
        error_message=urow["error_message"],
        raw_notebooklm_response=urow["raw_notebooklm_response"],
        questions=[_row_to_question(r) for r in qrows],
    )


async def cleanup_old_uploads(keep: int = HISTORY_CAP) -> int:
    """Delete uploads (and their questions) beyond the `keep` most recent. Returns count deleted."""
    async with aiosqlite.connect(_db_path()) as conn:
        await conn.execute(
            """
            DELETE FROM questions
             WHERE upload_id IN (
               SELECT id FROM uploads
                ORDER BY created_at DESC
                LIMIT -1 OFFSET ?
             )
            """,
            (keep,),
        )
        cur = await conn.execute(
            """
            DELETE FROM uploads
             WHERE id IN (
               SELECT id FROM uploads
                ORDER BY created_at DESC
                LIMIT -1 OFFSET ?
             )
            """,
            (keep,),
        )
        deleted = cur.rowcount or 0
        await conn.commit()
    return deleted


async def nightly_cleanup_loop(interval_seconds: float = 24 * 60 * 60) -> None:
    """Run cleanup once per interval. Started as an asyncio background task."""
    while True:
        try:
            await cleanup_old_uploads()
        except Exception:
            logger.exception("nightly_cleanup_loop iteration failed")
        await asyncio.sleep(interval_seconds)
