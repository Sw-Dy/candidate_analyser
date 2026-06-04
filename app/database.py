import json
import sqlite3
from pathlib import Path
from typing import Any


def get_connection(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path)
    connection.row_factory = sqlite3.Row
    return connection


def initialize_database(database_path: Path) -> None:
    connection = get_connection(database_path)
    cursor = connection.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            candidate_id INTEGER NOT NULL,
            exam_id INTEGER NOT NULL,
            generated_at TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """
    )
    connection.commit()
    connection.close()


def save_snapshot(database_path: Path, payload: dict[str, Any]) -> int:
    connection = get_connection(database_path)
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO analytics_snapshots (
            candidate_id,
            exam_id,
            generated_at,
            payload_json
        ) VALUES (?, ?, ?, ?)
        """,
        (
            payload["student"]["candidate_id"],
            payload["exam"]["exam_id"],
            payload["generated_at"],
            json.dumps(payload),
        ),
    )
    connection.commit()
    snapshot_id = int(cursor.lastrowid)
    connection.close()
    return snapshot_id


def fetch_latest_snapshot(database_path: Path) -> dict[str, Any] | None:
    connection = get_connection(database_path)
    cursor = connection.cursor()
    cursor.execute(
        """
        SELECT id, payload_json
        FROM analytics_snapshots
        ORDER BY id DESC
        LIMIT 1
        """
    )
    row = cursor.fetchone()
    connection.close()
    if row is None:
        return None

    payload = json.loads(row["payload_json"])
    payload["snapshot_id"] = row["id"]
    return payload
