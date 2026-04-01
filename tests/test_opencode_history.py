"""Unit tests for OpenCode sqlite history parsing."""

import json
import sqlite3
from pathlib import Path

from opencode_orchestrator.opencode_history import load_session_messages


def _make_opencode_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE message (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE part (
            id TEXT PRIMARY KEY,
            message_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            time_created INTEGER NOT NULL,
            time_updated INTEGER NOT NULL,
            data TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def test_load_session_messages_reads_error_from_message_data_when_parts_missing(tmp_path: Path) -> None:
    db_path = tmp_path / "opencode.db"
    _make_opencode_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO message (id, session_id, time_created, time_updated, data)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            "msg_1",
            "ses_1",
            1774873142708,
            1774873143025,
            json.dumps(
                {
                    "role": "assistant",
                    "error": {
                        "name": "APIError",
                        "data": {"message": "Invalid API Key", "statusCode": 401},
                    },
                }
            ),
        ),
    )
    conn.commit()
    conn.close()

    rows = load_session_messages(db_path=db_path, session_id="ses_1")
    assert len(rows) == 1
    assert rows[0]["role"] == "assistant"
    assert "Invalid API Key" in rows[0]["content"]
    assert "status 401" in rows[0]["content"]

