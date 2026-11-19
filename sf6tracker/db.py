"""SQLite storage for matches, plus the local config file."""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    id             INTEGER PRIMARY KEY,
    source         TEXT NOT NULL,              -- 'buckler' or 'manual'
    replay_id      TEXT UNIQUE,
    played_at      INTEGER NOT NULL,           -- unix seconds
    my_character   TEXT NOT NULL,
    my_input_type  INTEGER,
    my_lp          INTEGER,
    my_mr          INTEGER,
    my_league_rank INTEGER,
    rating_timing  TEXT NOT NULL,              -- 'buckler' (auto-detected) or 'post'
    opp_name       TEXT,
    opp_sid        INTEGER,
    opp_platform   TEXT,
    opp_character  TEXT NOT NULL,
    opp_input_type INTEGER,
    opp_lp         INTEGER,
    opp_mr         INTEGER,
    result         TEXT NOT NULL CHECK (result IN ('W', 'L', 'D')),
    my_rounds      TEXT,                       -- JSON list of Buckler round codes
    opp_rounds     TEXT,
    rounds_won     INTEGER,
    rounds_lost    INTEGER,
    notes          TEXT,
    raw            TEXT,
    created_at     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS matches_played_at ON matches (played_at);

CREATE TABLE IF NOT EXISTS sync_log (
    id        INTEGER PRIMARY KEY,
    at        INTEGER NOT NULL,
    source    TEXT NOT NULL,
    status    TEXT NOT NULL,
    added     INTEGER NOT NULL DEFAULT 0,
    message   TEXT
);
"""

MATCH_FIELDS = [
    "source", "replay_id", "played_at", "my_character", "my_input_type", "my_lp",
    "my_mr", "my_league_rank", "rating_timing", "opp_name", "opp_sid", "opp_platform",
    "opp_character", "opp_input_type", "opp_lp", "opp_mr", "result", "my_rounds",
    "opp_rounds", "rounds_won", "rounds_lost", "notes", "raw",
]

DEFAULT_CONFIG = {
    "sid": "",
    "cookie": "",
    "auto_sync_minutes": 0,
    "lp_timing": "auto",          # 'auto', 'pre' or 'post'
    "session_gap_minutes": 30,
}


class Store:
    """Thread-safe wrapper around the SQLite database and config.json."""

    def __init__(self, data_dir: str | os.PathLike):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "tracker.db"
        self.config_path = self.data_dir / "config.json"
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ---- config -------------------------------------------------------------
    def config(self) -> dict:
        with self._lock:
            cfg = dict(DEFAULT_CONFIG)
            if self.config_path.exists():
                try:
                    cfg.update(json.loads(self.config_path.read_text()))
                except (OSError, ValueError):
                    pass
            if not cfg.get("import_token"):
                cfg["import_token"] = secrets.token_urlsafe(16)
                self._write_config(cfg)
            return cfg

    def update_config(self, changes: dict) -> dict:
        with self._lock:
            cfg = self.config()
            cfg.update(changes)
            self._write_config(cfg)
            return cfg

    def _write_config(self, cfg: dict) -> None:
        tmp = self.config_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(cfg, indent=2))
        os.chmod(tmp, 0o600)   # holds the Buckler cookie
        tmp.replace(self.config_path)

    # ---- matches ------------------------------------------------------------
    def known_replay_ids(self) -> set[str]:
        with self._lock:
            rows = self._conn.execute("SELECT replay_id FROM matches WHERE replay_id IS NOT NULL")
            return {r[0] for r in rows}

    def insert_matches(self, matches: list[dict]) -> int:
        """Insert matches, skipping replay IDs already stored. Returns how many were added."""
        added = 0
        now = int(time.time())
        cols = MATCH_FIELDS + ["created_at"]
        sql = (f"INSERT OR IGNORE INTO matches ({', '.join(cols)}) "
               f"VALUES ({', '.join('?' for _ in cols)})")
        with self._lock:
            for m in matches:
                values = [_db_value(m.get(f)) for f in MATCH_FIELDS] + [now]
                cur = self._conn.execute(sql, values)
                added += cur.rowcount
            self._conn.commit()
        return added

    def all_matches(self) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM matches ORDER BY played_at, id").fetchall()
        out = []
        for r in rows:
            m = dict(r)
            m.pop("raw", None)
            for key in ("my_rounds", "opp_rounds"):
                m[key] = json.loads(m[key]) if m[key] else None
            out.append(m)
        return out

    def delete_match(self, match_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM matches WHERE id = ?", (match_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def match_count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]

    # ---- sync log -----------------------------------------------------------
    def log_sync(self, source: str, status: str, added: int = 0, message: str = "") -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO sync_log (at, source, status, added, message) VALUES (?, ?, ?, ?, ?)",
                (int(time.time()), source, status, added, message),
            )
            self._conn.commit()

    def recent_syncs(self, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(r) for r in rows]


def _db_value(v):
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    return v
